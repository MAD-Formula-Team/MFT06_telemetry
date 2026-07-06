"""Fuentes de frames: puerto serie real y replay de logs.

Ambas fuentes empujan RawFrame a un callback desde su propio hilo. El
callback (el pipeline) debe ser rápido y no lanzar excepciones.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from . import ports
from .frames import RawFrame, parse_line

FrameCallback = Callable[[RawFrame], None]
StatusCallback = Callable[[str, str], None]  # (mensaje, nivel: info|warn|error)


def _now_us() -> int:
    return time.monotonic_ns() // 1_000


class SerialSource:
    """Lee el protocolo CSV del receptor por USB serie.

    - Reconecta al MISMO dispositivo con backoff si el puerto desaparece.
    - Nunca cierra el puerto por silencio: sin datos != sin conexión.
    - No imprime en el bucle de lectura (retrasaría la lectura).
    """

    def __init__(
        self,
        device: str,
        on_frame: FrameCallback,
        on_status: StatusCallback | None = None,
        baudrate: int = ports.DEFAULT_BAUDRATE,
    ):
        self.device = device
        self.baudrate = baudrate
        self._on_frame = on_frame
        self._on_status = on_status or (lambda msg, level: None)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._serial = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name=f"SerialSource({self.device})", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def _run(self) -> None:
        backoff_s = 0.5
        while self._running.is_set():
            if self._serial is None:
                try:
                    self._serial = ports.open_port_no_reset(self.device, self.baudrate)
                    self._on_status(f"Conectado a {self.device}", "info")
                    backoff_s = 0.5
                except Exception as exc:
                    self._on_status(f"No se pudo abrir {self.device}: {exc}", "warn")
                    if self._sleep_interruptible(backoff_s):
                        continue
                    return
                continue

            try:
                raw = self._serial.readline()
            except Exception as exc:
                self._on_status(f"Conexión perdida en {self.device}: {exc}", "error")
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                backoff_s = min(backoff_s * 2.0, 5.0)
                continue

            if not raw:
                continue  # timeout de lectura: seguir esperando, NUNCA cerrar

            line = raw.decode("utf-8", errors="ignore")
            frame = parse_line(line, _now_us())
            if frame is not None:
                self._on_frame(frame)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Duerme en trozos cortos; devuelve False si hay que parar."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self._running.is_set():
                return False
            time.sleep(0.05)
        return True


class ReplaySource:
    """Reproduce frames grabados por el mismo pipeline que los datos en vivo.

    speed: multiplicador de velocidad (2.0 = doble de rápido). realtime=False
    reproduce tan rápido como sea posible (para tests).
    """

    def __init__(
        self,
        frames: Iterable[RawFrame],
        on_frame: FrameCallback,
        on_status: StatusCallback | None = None,
        speed: float = 1.0,
        realtime: bool = False,
    ):
        self._frames = frames
        self._on_frame = on_frame
        self._on_status = on_status or (lambda msg, level: None)
        self._speed = max(speed, 1e-6)
        self._realtime = realtime
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self.finished = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running.set()
        self.finished.clear()
        self._thread = threading.Thread(target=self._run, name="ReplaySource", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def join(self, timeout: float | None = None) -> bool:
        """Espera a que termine la reproducción (para tests)."""
        return self.finished.wait(timeout)

    def _run(self) -> None:
        self._on_status("Replay iniciado", "info")
        prev_t_us: int | None = None
        for frame in self._frames:
            if not self._running.is_set():
                break
            if self._realtime and prev_t_us is not None:
                dt_s = max(0.0, (frame.t_us - prev_t_us) / 1_000_000.0) / self._speed
                if dt_s > 0:
                    time.sleep(min(dt_s, 5.0))
            prev_t_us = frame.t_us
            self._on_frame(frame)
        self._on_status("Replay terminado", "info")
        self.finished.set()
