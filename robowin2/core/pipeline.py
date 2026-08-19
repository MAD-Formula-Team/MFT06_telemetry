"""Pipeline: fuente -> rawlog -> stats -> decodificación -> datastore/laptimer.

Se ejecuta en el hilo de la fuente (los callbacks deben ser rápidos). La UI
no participa: lee snapshots de datastore/bus_stats a su propio ritmo.
"""
from __future__ import annotations

from collections.abc import Callable

from .bus_stats import BusStats
from .datastore import DataStore
from .decoder import DbcDecoder
from .frames import LAPTIMER_CAN_ID, LORA_METRICS_CAN_ID, RawFrame, laptimer_timestamp_s, lora_metrics
from .lapstore import Lap, LapTimer
from .rawlog import RawLogWriter

LapCallback = Callable[[Lap], None]


class Pipeline:
    def __init__(
        self,
        decoder: DbcDecoder,
        datastore: DataStore,
        bus_stats: BusStats,
        rawlog: RawLogWriter | None = None,
        laptimer: LapTimer | None = None,
        on_lap: LapCallback | None = None,
        on_trigger: Callable[[], None] | None = None,
        session_id_provider: Callable[[], int | None] | None = None,
    ):
        self._decoder = decoder
        self._datastore = datastore
        self._bus_stats = bus_stats
        self._rawlog = rawlog
        self._laptimer = laptimer
        self._on_lap = on_lap
        self._on_trigger = on_trigger
        self._session_id_provider = session_id_provider
        self.frames_processed = 0
        self.frames_unknown = 0

    def on_frame(self, frame: RawFrame) -> None:
        """Callback para las fuentes. No lanza: un frame malo no para el flujo."""
        try:
            self._process(frame)
        except Exception:
            # Nunca dejar que un error puntual mate el hilo de la fuente
            pass

    def _process(self, frame: RawFrame) -> None:
        self.frames_processed += 1

        # 1) Log crudo SIEMPRE primero: pase lo que pase después, está en disco
        if self._rawlog is not None:
            self._rawlog.write(frame)

        # 2) Estadísticas de bus (conocidos y desconocidos)
        name = self._decoder.name_for(frame.can_id)
        if frame.can_id == LAPTIMER_CAN_ID:
            name = "laptimer"
        elif frame.can_id == LORA_METRICS_CAN_ID:
            name = "lora_metrics"
        self._bus_stats.on_frame(frame.t_us, frame.can_id, frame.data, name)

        # 3) Métricas LoRa (fuera del DBC, pseudo-ID de la base)
        if frame.can_id == LORA_METRICS_CAN_ID:
            metrics = lora_metrics(frame)
            if metrics is not None:
                rssi, snr = metrics
                self._datastore.add_sample("lora_rssi", frame.t_s, rssi)
                self._datastore.add_sample("lora_snr", frame.t_s, snr)
            return

        # 4) Laptimer (fuera del DBC)
        if frame.can_id == LAPTIMER_CAN_ID:
            trigger_s = laptimer_timestamp_s(frame)
            if trigger_s is not None and self._laptimer is not None:
                if self._on_trigger is not None:
                    self._on_trigger()
                lap = self._laptimer.on_trigger(trigger_s)
                if lap is not None:
                    self._datastore.add_sample("laptimer_last_lap_s", frame.t_s, lap.lap_time_s)
                    if self._rawlog is not None:
                        session_id = self._session_id_provider() if self._session_id_provider else None
                        self._rawlog.write_lap(lap.number, frame.t_us, lap.lap_time_s, session_id=session_id)
                    if self._on_lap is not None:
                        self._on_lap(lap)
            return

        # 5) Señales DBC
        signals = self._decoder.decode(frame.can_id, frame.data)
        if signals is None:
            if name is None:
                self.frames_unknown += 1
            return
        for key, value in signals.items():
            self._datastore.add_sample(key, frame.t_s, value)

    def flush(self) -> None:
        if self._rawlog is not None:
            self._rawlog.flush()
