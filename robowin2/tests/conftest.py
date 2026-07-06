import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DBC_PATH = REPO_ROOT / "UI" / "mft06.dbc"


@pytest.fixture(scope="session")
def dbc_path() -> str:
    assert DBC_PATH.exists(), f"DBC no encontrado: {DBC_PATH}"
    return str(DBC_PATH)


@pytest.fixture(scope="session")
def decoder(dbc_path):
    from robowin2.core.decoder import DbcDecoder

    return DbcDecoder(dbc_path)
