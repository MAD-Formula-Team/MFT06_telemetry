"""Estadísticas en vivo del bus CAN, por ID: la base de la página Bus CAN.

Por cada ID: contador, frecuencia rodante (ventana de 5 s), jitter de periodo,
último payload con máscara de bytes cambiados, staleness y cuota de ancho de
banda. Thread-safe: on_frame() desde el hilo del pipeline, snapshot() desde
la UI.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

ROLLING_WINDOW_US = 5_000_000  # 5 s


@dataclass
class _IdState:
    can_id: int
    name: str | None = None
    count: int = 0
    bytes_total: int = 0
    last_t_us: int = 0
    last_data: bytes = b""
    changed_mask: int = 0            # bit i = byte i cambió en el último frame
    period_ema_us: float = 0.0
    jitter_ema_us: float = 0.0
    window: deque = field(default_factory=deque)          # t_us recientes
    window_bytes: deque = field(default_factory=deque)    # (t_us, nbytes)


@dataclass(frozen=True, slots=True)
class IdStatsView:
    """Snapshot inmutable de un ID para la UI."""

    can_id: int
    name: str | None
    count: int
    freq_hz: float
    period_ms: float
    jitter_ms: float
    last_t_us: int
    age_s: float
    last_data: bytes
    changed_mask: int
    bandwidth_share: float  # 0..1 dentro de la ventana rodante


class BusStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._ids: dict[int, _IdState] = {}

    def on_frame(self, t_us: int, can_id: int, data: bytes, name: str | None) -> None:
        with self._lock:
            st = self._ids.get(can_id)
            if st is None:
                st = _IdState(can_id=can_id, name=name)
                self._ids[can_id] = st

            if st.count > 0:
                period = float(t_us - st.last_t_us)
                if st.period_ema_us == 0.0:
                    st.period_ema_us = period
                else:
                    st.jitter_ema_us += 0.2 * (abs(period - st.period_ema_us) - st.jitter_ema_us)
                    st.period_ema_us += 0.2 * (period - st.period_ema_us)

                # Máscara de bytes cambiados respecto al payload anterior
                mask = 0
                for i in range(max(len(data), len(st.last_data))):
                    old = st.last_data[i] if i < len(st.last_data) else None
                    new = data[i] if i < len(data) else None
                    if old != new:
                        mask |= 1 << i
                st.changed_mask = mask

            st.count += 1
            st.bytes_total += len(data)
            st.last_t_us = t_us
            st.last_data = data
            st.name = name or st.name
            st.window.append(t_us)
            st.window_bytes.append((t_us, len(data)))
            self._prune(st, t_us)

    @staticmethod
    def _prune(st: _IdState, now_us: int) -> None:
        horizon = now_us - ROLLING_WINDOW_US
        while st.window and st.window[0] < horizon:
            st.window.popleft()
        while st.window_bytes and st.window_bytes[0][0] < horizon:
            st.window_bytes.popleft()

    def snapshot(self, now_us: int) -> list[IdStatsView]:
        with self._lock:
            total_window_bytes = 0
            per_id_window_bytes: dict[int, int] = {}
            for st in self._ids.values():
                self._prune(st, now_us)
                nbytes = sum(n for _t, n in st.window_bytes)
                per_id_window_bytes[st.can_id] = nbytes
                total_window_bytes += nbytes

            views = []
            for st in self._ids.values():
                # Frecuencia sobre el intervalo REAL cubierto por la ventana
                # (dividir por los 5 s fijos infraestima con ráfagas cortas)
                if len(st.window) >= 2:
                    span_s = (st.window[-1] - st.window[0]) / 1_000_000.0
                    freq = (len(st.window) - 1) / span_s if span_s > 0 else 0.0
                else:
                    freq = 0.0
                share = (per_id_window_bytes[st.can_id] / total_window_bytes) if total_window_bytes else 0.0
                views.append(
                    IdStatsView(
                        can_id=st.can_id,
                        name=st.name,
                        count=st.count,
                        freq_hz=freq,
                        period_ms=st.period_ema_us / 1000.0,
                        jitter_ms=st.jitter_ema_us / 1000.0,
                        last_t_us=st.last_t_us,
                        age_s=max(0.0, (now_us - st.last_t_us) / 1_000_000.0),
                        last_data=st.last_data,
                        changed_mask=st.changed_mask,
                        bandwidth_share=share,
                    )
                )
            views.sort(key=lambda v: v.can_id)
            return views

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()
