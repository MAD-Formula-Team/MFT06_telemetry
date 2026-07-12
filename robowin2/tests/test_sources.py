"""Tests de RobotellSource con un bus falso (sin hardware ni python-can real)."""
from __future__ import annotations

import time

from robowin2.core.sources import RobotellSource


class FakeMsg:
    def __init__(self, arbitration_id: int, data: bytes, is_error_frame: bool = False):
        self.arbitration_id = arbitration_id
        self.data = data
        self.is_error_frame = is_error_frame


class FakeBus:
    def __init__(self, messages: list[FakeMsg]):
        self._messages = list(messages)
        self.shutdown_called = False

    def recv(self, timeout: float = 0.0):
        if self._messages:
            return self._messages.pop(0)
        time.sleep(0.01)  # simular timeout de recv sin datos
        return None

    def shutdown(self) -> None:
        self.shutdown_called = True


def _wait_for(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_robotell_convierte_mensajes_a_rawframe(monkeypatch):
    bus = FakeBus([
        FakeMsg(0x3A1, bytes([0x00, 0x1F, 0x5A, 0x00])),
        FakeMsg(0x100, bytes([0xFF])),
        FakeMsg(0x7FF, b"", is_error_frame=True),  # los error frames se descartan
    ])
    frames = []
    source = RobotellSource("FAKE", on_frame=frames.append)
    monkeypatch.setattr(source, "_open_bus", lambda: bus)

    source.start()
    assert _wait_for(lambda: len(frames) >= 2)
    source.stop()

    assert len(frames) == 2
    assert frames[0].can_id == 0x3A1
    assert frames[0].data == bytes([0x00, 0x1F, 0x5A, 0x00])
    assert frames[1].can_id == 0x100
    assert frames[0].t_us > 0
    assert bus.shutdown_called


class FakeConfigBus:
    """Bus falso con la interfaz de configuración de filtros del driver robotell."""

    _CAN_FILTER_BASE_ID = 0x01FFFEE0

    def __init__(self, filters: dict[int, bytes]):
        self._filters = dict(filters)  # configid -> 8 bytes (valor LE + máscara LE)
        self.writes = []

    def _readconfig(self, configid, timeout):
        return self._filters.get(configid)

    def set_hw_filter(self, filterid, enabled, msgid_value, msgid_mask, extended_msg):
        self.writes.append((filterid, enabled, msgid_value, msgid_mask, extended_msg))


def test_robotell_no_reescribe_filtros_de_fabrica(monkeypatch):
    import can

    bus = FakeConfigBus({
        0x01FFFEE0: RobotellSource._FACTORY_FILTER_STD,
        0x01FFFEE1: RobotellSource._FACTORY_FILTER_EXT,
    })
    monkeypatch.setattr(can, "Bus", lambda **kwargs: bus)
    source = RobotellSource("FAKE", on_frame=lambda f: None)
    source._open_bus()

    assert bus.writes == []  # ya aceptan todo: no tocar la flash


def test_robotell_repara_filtros_que_bloquean(monkeypatch):
    import can

    # Estado dañado: filtros 1-2 deshabilitados (whitelist vacía = no se recibe nada)
    bus = FakeConfigBus({
        0x01FFFEE0: bytes(8),
        0x01FFFEE1: bytes(8),
    })
    monkeypatch.setattr(can, "Bus", lambda **kwargs: bus)
    statuses = []
    source = RobotellSource("FAKE", on_frame=lambda f: None, on_status=lambda m, lvl: statuses.append(m))
    source._open_bus()

    # Se restaura el estado de fábrica: 1 = todo estándar, 2 = todo extendido
    assert bus.writes == [(1, True, 0, 0, False), (2, True, 0, 0, True)]
    assert len(statuses) == 2


def test_robotell_reintenta_si_no_abre(monkeypatch):
    statuses = []
    source = RobotellSource("FAKE", on_frame=lambda f: None, on_status=lambda m, lvl: statuses.append(lvl))

    def fail_open():
        raise OSError("puerto ocupado")

    monkeypatch.setattr(source, "_open_bus", fail_open)
    source.start()
    assert _wait_for(lambda: len(statuses) >= 1)
    source.stop()

    assert all(lvl == "warn" for lvl in statuses)
