"""Genera un log .db de demostración para probar la app sin hardware.

Uso: python -m robowin2.demo
Crea ~5 minutos de telemetría sintética (temperaturas, RPM, batería) con una
sesión de vueltas, y lo deja en el directorio de datos. Ábrelo con ABRIR LOG.
"""
from __future__ import annotations

import math
import random

import cantools

from robowin2 import paths
from robowin2.core.frames import RawFrame
from robowin2.core.rawlog import RawLogWriter

DURATION_S = 300
LAP_TIMES_S = [52.3, 49.8, 51.1, 48.9, 50.4]


def _rpm_message(db):
    """Mensaje que contiene engine_rpm (sin acoplarse al layout del DBC)."""
    for msg in db.messages:
        if any(sig.name == "engine_rpm" for sig in msg.signals):
            return msg
    return None


def generate(db_path=None) -> str:
    dbc = paths.find_dbc()
    if dbc is None:
        raise SystemExit("No se encontró mft06.dbc")
    db = cantools.database.load_file(str(dbc))
    rpm_msg = _rpm_message(db)

    out_path = db_path or (paths.data_dir() / "robowin_demo.db")
    writer = RawLogWriter(out_path, app_version="demo")
    rng = random.Random(6)
    frames: list[RawFrame] = []

    for tick in range(DURATION_S * 2):  # 2 Hz
        t_us = tick * 500_000
        t_s = t_us / 1e6

        ect = min(103.0, 70.0 + t_s * 0.18) + rng.uniform(-0.6, 0.6)
        oil = min(122.0, 78.0 + t_s * 0.22) + rng.uniform(-0.8, 0.8)
        payload = db.encode_message(929, {"iat": 28 + rng.uniform(-1, 1), "ect": ect, "oil_temp": oil})
        frames.append(RawFrame(t_us=t_us, can_id=929, data=payload))

        if tick % 2 == 0:
            batt = 12.6 - t_s * 0.0015 + rng.uniform(-0.05, 0.05)
            payload = db.encode_message(
                933, {"batt_volt": batt, "ecu_temp": 45, "engine_in": 40, "carter_temp": 80}
            )
            frames.append(RawFrame(t_us=t_us + 1000, can_id=933, data=payload))

        if rpm_msg is not None:
            rpm = 5500 + 3500 * math.sin(t_s * 1.4) + rng.uniform(-150, 150)
            values = {sig.name: 0 for sig in rpm_msg.signals}
            values["engine_rpm"] = max(1100.0, rpm)
            payload = db.encode_message(rpm_msg.frame_id, values)
            frames.append(RawFrame(t_us=t_us + 2000, can_id=rpm_msg.frame_id, data=payload))

    # Pasadas del laptimer (timestamps del dispositivo en µs)
    device_us = 20_000_000
    passes = [device_us]
    for lap in LAP_TIMES_S:
        device_us += int(lap * 1_000_000)
        passes.append(device_us)
    for device in passes:
        frames.append(RawFrame(t_us=device, can_id=0x777, data=device.to_bytes(8, "little")))

    frames.sort(key=lambda f: f.t_us)
    for frame in frames:
        writer.write(frame)
    writer.close()
    return str(out_path)


if __name__ == "__main__":
    path = generate()
    print(f"Demo generado: {path}")
    print("Arranca la app (python -m robowin2.main) y usa ABRIR LOG para reproducirlo.")
