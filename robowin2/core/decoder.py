"""Decodificación DBC (cantools) con catálogo de señales para la UI."""
from __future__ import annotations

from dataclasses import dataclass

import cantools


@dataclass(frozen=True, slots=True)
class SignalInfo:
    key: str
    label: str
    unit: str
    message: str
    group: str
    y_range: tuple[float, float] | None


def _classify_group(message_name: str) -> str:
    name = (message_name or "").lower()
    if name.startswith("engine"):
        return "MOTOR"
    if name.startswith("currents"):
        return "ELECTRICO"
    if name in {"steering", "dampers"}:
        return "CHASIS"
    return "OTROS"


class DbcDecoder:
    """Envuelve cantools: decodifica frames y expone el catálogo de señales."""

    def __init__(self, dbc_path: str):
        self._db = cantools.database.load_file(dbc_path)
        self._by_id = {msg.frame_id: msg for msg in self._db.messages}

    def name_for(self, can_id: int) -> str | None:
        msg = self._by_id.get(can_id)
        return msg.name if msg is not None else None

    def decode(self, can_id: int, data: bytes) -> dict[str, float] | None:
        """Señales decodificadas, o None si el ID es desconocido o el payload
        no decodifica. Nunca lanza: la corrupción no debe parar el pipeline."""
        if can_id not in self._by_id:
            return None
        try:
            decoded = self._db.decode_message(can_id, data)
        except Exception:
            return None
        return {k: float(v) for k, v in decoded.items() if isinstance(v, (int, float))}

    def signal_catalog(self) -> list[SignalInfo]:
        catalog: list[SignalInfo] = []
        for msg in self._db.messages:
            group = _classify_group(getattr(msg, "name", ""))
            for sig in msg.signals:
                y_range = None
                if sig.minimum is not None and sig.maximum is not None and sig.minimum < sig.maximum:
                    y_range = (float(sig.minimum), float(sig.maximum))
                catalog.append(
                    SignalInfo(
                        key=sig.name,
                        label=sig.name.replace("_", " ").upper(),
                        unit=sig.unit or "",
                        message=getattr(msg, "name", ""),
                        group=group,
                        y_range=y_range,
                    )
                )
        return catalog

    def units(self) -> dict[str, str]:
        return {info.key: info.unit for info in self.signal_catalog()}
