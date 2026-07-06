"""Almacén de señales sobre ring buffers numpy.

Diseño para lecturas baratas desde la UI: append O(1) amortizado; snapshot()
devuelve VISTAS de solo lectura sin copiar. Las vistas son estables porque:
- dentro de la capacidad solo se añade por el final (una vista [:n] no ve
  los appends posteriores), y
- al compactar se crean arrays NUEVOS, así que las vistas antiguas siguen
  apuntando a los datos antiguos intactos.
"""
from __future__ import annotations

import threading

import numpy as np

_INITIAL_CAPACITY = 4_096


class _SignalBuffer:
    def __init__(self, max_points: int):
        self.max_points = max_points
        cap = min(_INITIAL_CAPACITY, max_points)
        self._t = np.empty(cap, dtype=np.float64)
        self._v = np.empty(cap, dtype=np.float64)
        self._n = 0

    def append(self, t_s: float, value: float) -> None:
        if self._n == len(self._t):
            self._grow_or_compact()
        self._t[self._n] = t_s
        self._v[self._n] = value
        self._n += 1

    def _grow_or_compact(self) -> None:
        cap = len(self._t)
        if cap < self.max_points:
            new_cap = min(cap * 2, self.max_points)
            new_t = np.empty(new_cap, dtype=np.float64)
            new_v = np.empty(new_cap, dtype=np.float64)
            new_t[: self._n] = self._t[: self._n]
            new_v[: self._n] = self._v[: self._n]
            self._t, self._v = new_t, new_v
        else:
            # Lleno: conservar la mitad más reciente en arrays NUEVOS para
            # que las vistas ya entregadas no se corrompan.
            half = self._n // 2
            new_t = np.empty(cap, dtype=np.float64)
            new_v = np.empty(cap, dtype=np.float64)
            new_t[: self._n - half] = self._t[half : self._n]
            new_v[: self._n - half] = self._v[half : self._n]
            self._t, self._v = new_t, new_v
            self._n -= half

    def view(self) -> tuple[np.ndarray, np.ndarray]:
        t = self._t[: self._n]
        v = self._v[: self._n]
        t.flags.writeable = False
        v.flags.writeable = False
        return t, v


class DataStore:
    """Series temporales por señal, thread-safe."""

    def __init__(self, max_points_per_signal: int = 500_000):
        self._max_points = max_points_per_signal
        self._lock = threading.Lock()
        self._buffers: dict[str, _SignalBuffer] = {}

    def add_sample(self, key: str, t_s: float, value: float) -> None:
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = _SignalBuffer(self._max_points)
                self._buffers[key] = buf
            buf.append(t_s, value)

    def snapshot(self, key: str) -> tuple[np.ndarray, np.ndarray]:
        """(timestamps_s, valores) como vistas de solo lectura (sin copia)."""
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                empty = np.empty(0, dtype=np.float64)
                return empty, empty
            return buf.view()

    def latest(self, key: str) -> tuple[float, float] | None:
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None or buf._n == 0:
                return None
            i = buf._n - 1
            return float(buf._t[i]), float(buf._v[i])

    def keys(self) -> list[str]:
        with self._lock:
            return sorted(self._buffers.keys())

    def clear(self) -> None:
        with self._lock:
            self._buffers.clear()
