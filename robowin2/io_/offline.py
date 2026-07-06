"""Conjuntos de datos offline: cargar .db propios, importar CSV de ROBOWIN 1
y exportar CSV compatible.

Un OfflineDataset es autocontenido: señales decodificadas (DataStore propio),
vueltas y sesiones. Del .db se reconstruye decodificando los frames crudos
(el log crudo es la fuente de verdad); del CSV legado se importan las señales
ya decodificadas.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from robowin2.core.datastore import DataStore
from robowin2.core.decoder import DbcDecoder
from robowin2.core.frames import LAPTIMER_CAN_ID, laptimer_timestamp_s
from robowin2.core.lapstore import MIN_LAP_S, format_lap_time
from robowin2.core.rawlog import RawLogReader

# Columnas de metadatos laptime del CSV combinado de ROBOWIN 1 (no son señales)
LEGACY_LAPTIME_COLUMNS = {
    "name", "mode", "started_at", "ended_at", "laps", "total_time", "best", "avg",
    "last", "consistency_ms", "lap_number", "lap_time_s", "lap_time_fmt",
    "delta_s", "delta_fmt", "state",
}


@dataclass(frozen=True, slots=True)
class OfflineLap:
    number: int
    lap_time_s: float
    t_end_s: float          # fin de vuelta en el timeline de la telemetría
    session_name: str = ""
    session_mode: str = ""

    @property
    def t_start_s(self) -> float:
        return max(0.0, self.t_end_s - self.lap_time_s)


@dataclass
class OfflineDataset:
    description: str
    datastore: DataStore = field(default_factory=DataStore)
    laps: list[OfflineLap] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)

    @property
    def signal_keys(self) -> list[str]:
        return self.datastore.keys()


# ---------------------------------------------------------------- .db propio

def load_db(db_path: str | Path, decoder: DbcDecoder, run_id: int | None = None) -> OfflineDataset:
    """Reconstruye señales y vueltas decodificando el log crudo (último run
    por defecto)."""
    reader = RawLogReader(db_path)
    try:
        runs = reader.runs()
        if not runs:
            raise ValueError("El log no contiene ningún run")
        if run_id is None:
            run_id = runs[-1]["id"]

        dataset = OfflineDataset(description=f"{Path(db_path).name} (run {run_id})")
        lap_reference_device_s: float | None = None

        for frame in reader.frames(run_id):
            if frame.can_id == LAPTIMER_CAN_ID:
                trigger = laptimer_timestamp_s(frame)
                if trigger is not None:
                    if lap_reference_device_s is not None:
                        lap_s = trigger - lap_reference_device_s
                        if 0 < lap_s < MIN_LAP_S:
                            continue  # pulso fantasma: no mover referencia
                    lap_reference_device_s = trigger
                continue
            signals = decoder.decode(frame.can_id, frame.data)
            if signals:
                for key, value in signals.items():
                    dataset.datastore.add_sample(key, frame.t_s, value)

        # Vueltas y sesiones desde las tablas (ya filtradas al grabar)
        sessions_by_id = {s["id"]: s for s in reader.sessions(run_id)}
        dataset.sessions = list(sessions_by_id.values())
        for lap_row in reader.laps(run_id):
            session = sessions_by_id.get(lap_row["session_id"], {})
            dataset.laps.append(
                OfflineLap(
                    number=lap_row["lap_no"],
                    lap_time_s=lap_row["lap_time_s"],
                    t_end_s=lap_row["t_us"] / 1e6,
                    session_name=session.get("name", ""),
                    session_mode=session.get("mode", ""),
                )
            )
        return dataset
    finally:
        reader.close()


# ------------------------------------------------------- CSV legado (R1)

def load_legacy_csv(csv_path: str | Path) -> OfflineDataset:
    """Importa el CSV combinado de ROBOWIN 1 (tolerante por celda, como el
    cargador corregido del propio R1)."""
    dataset = OfflineDataset(description=Path(csv_path).name)
    seen_laps: set[tuple] = set()

    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or header[0] != "timestamp":
            raise ValueError("Formato CSV inválido (falta columna timestamp)")

        signal_cols = [
            (i, name) for i, name in enumerate(header[1:], start=1)
            if name and name not in LEGACY_LAPTIME_COLUMNS
        ]
        col_index = {name: i for i, name in enumerate(header)}

        def cell(row: list[str], column: str) -> str:
            idx = col_index.get(column)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        for row in reader:
            if not row:
                continue
            try:
                timestamp = float(row[0])
            except (ValueError, IndexError):
                continue

            for i, signal in signal_cols:
                if i >= len(row):
                    continue
                text = row[i].strip()
                if not text:
                    continue
                try:
                    dataset.datastore.add_sample(signal, timestamp, float(text))
                except ValueError:
                    continue

            lap_text = cell(row, "lap_number")
            if lap_text:
                key = (lap_text, cell(row, "name"), cell(row, "mode"))
                if key not in seen_laps:
                    seen_laps.add(key)
                    try:
                        dataset.laps.append(
                            OfflineLap(
                                number=int(lap_text),
                                lap_time_s=float(cell(row, "lap_time_s") or 0.0),
                                t_end_s=timestamp,
                                session_name=cell(row, "name"),
                                session_mode=cell(row, "mode"),
                            )
                        )
                    except ValueError:
                        pass

    return dataset


# ------------------------------------------------- CSV del data logger

def _parse_logger_time(text: str) -> float | None:
    """Timestamp absoluto del data logger ('04/07/2026 14:32:13.013') -> epoch s."""
    for fmt in ("%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def load_datalogger_csv(csv_path: str | Path) -> OfflineDataset:
    """Importa el CSV del data logger de a bordo.

    Formato: línea 'Creation Time', cabecera que empieza por 'Time', filas
    vacías, una fila de unidades ('sec,g,...') y datos DISPERSOS: cada fila
    solo rellena algunas columnas. Los timestamps absolutos se convierten a
    segundos relativos al primero.
    """
    dataset = OfflineDataset(description=f"{Path(csv_path).name} (data logger)")
    header: list[str] | None = None
    signal_cols: list[tuple[int, str]] = []
    t0: float | None = None

    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = (row[0] or "").strip()

            if header is None:
                if first.lower().startswith("creation time"):
                    continue
                if first == "Time" and len(row) > 1:
                    header = [c.strip() for c in row]
                    signal_cols = [(i, name) for i, name in enumerate(header) if i > 0 and name]
                continue

            # Con cabecera: solo son datos las filas cuyo primer campo es una
            # fecha (esto descarta las filas vacías y la fila de unidades).
            ts_abs = _parse_logger_time(first)
            if ts_abs is None:
                continue
            if t0 is None:
                t0 = ts_abs
            t_rel = ts_abs - t0

            for i, name in signal_cols:
                if i >= len(row):
                    continue
                text = row[i].strip()
                if not text:
                    continue
                try:
                    dataset.datastore.add_sample(name, t_rel, float(text))
                except ValueError:
                    continue

    if header is None:
        raise ValueError("No se encontró la cabecera 'Time,...' del data logger")
    return dataset


def load_csv_auto(csv_path: str | Path) -> OfflineDataset:
    """Detecta el formato del CSV y lo importa: combinado de ROBOWIN 1 o
    data logger de a bordo."""
    with open(csv_path, "r", newline="") as f:
        for row in csv.reader(f):
            if not row or not (row[0] or "").strip():
                continue
            first = row[0].strip().lower()
            if first == "timestamp":
                return load_legacy_csv(csv_path)
            if first.startswith("creation time") or row[0].strip() == "Time":
                return load_datalogger_csv(csv_path)
            break
    raise ValueError("Formato CSV no reconocido (ni ROBOWIN 1 ni data logger)")


# ----------------------------------------------------------------- export

def export_csv(dataset: OfflineDataset, out_path: str | Path) -> int:
    """Exporta el dataset al CSV combinado compatible con ROBOWIN 1.

    Señales en formato ancho con forward-fill (vacío antes de la primera
    muestra: el cargador tolerante lo ignora); columnas laptime rellenas a
    partir de la última vuelta cerrada en cada instante. Devuelve nº de filas.
    """
    keys = dataset.signal_keys
    series = {key: dataset.datastore.snapshot(key) for key in keys}

    timeline = np.unique(np.concatenate([t for t, _v in series.values()])) if keys else np.empty(0)
    laps_sorted = sorted(dataset.laps, key=lambda lap: lap.t_end_s)

    lap_columns = [
        "name", "mode", "started_at", "ended_at", "laps", "total_time", "best", "avg",
        "last", "consistency_ms", "lap_number", "lap_time_s", "lap_time_fmt",
        "delta_s", "delta_fmt", "state",
    ]

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp"] + keys + lap_columns)

        lap_idx = -1
        running_best: float | None = None
        cumulative = 0.0

        for ts in timeline:
            row: list = [f"{ts:.3f}"]
            for key in keys:
                t, v = series[key]
                pos = int(np.searchsorted(t, ts, side="right")) - 1
                row.append(f"{v[pos]:g}" if pos >= 0 else "")

            while lap_idx + 1 < len(laps_sorted) and laps_sorted[lap_idx + 1].t_end_s <= ts:
                lap_idx += 1
                lap = laps_sorted[lap_idx]
                cumulative += lap.lap_time_s
                running_best = lap.lap_time_s if running_best is None else min(running_best, lap.lap_time_s)

            if lap_idx >= 0:
                lap = laps_sorted[lap_idx]
                delta = lap.lap_time_s - (running_best or lap.lap_time_s)
                laps_so_far = lap_idx + 1
                row.extend([
                    lap.session_name or "session", lap.session_mode or "", "", "",
                    laps_so_far,
                    format_lap_time(cumulative),
                    format_lap_time(running_best),
                    format_lap_time(cumulative / laps_so_far),
                    format_lap_time(lap.lap_time_s),
                    "0.0",
                    lap.number,
                    f"{lap.lap_time_s:.6f}",
                    format_lap_time(lap.lap_time_s),
                    f"{delta:.6f}",
                    f"+{delta:.3f}s" if delta > 0 else "0.000s",
                    "BEST" if abs(delta) < 1e-9 else "",
                ])
            else:
                row.extend([""] * len(lap_columns))
            writer.writerow(row)

    return int(len(timeline))
