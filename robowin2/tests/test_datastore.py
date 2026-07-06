import numpy as np

from robowin2.core.datastore import DataStore


def test_append_and_snapshot():
    store = DataStore()
    for i in range(100):
        store.add_sample("rpm", i * 0.1, 4000 + i)

    t, v = store.snapshot("rpm")
    assert len(t) == len(v) == 100
    assert v[0] == 4000 and v[-1] == 4099
    assert not t.flags.writeable  # vistas de solo lectura


def test_snapshot_stable_after_more_appends():
    store = DataStore()
    for i in range(10):
        store.add_sample("ect", float(i), float(i))
    t_before, v_before = store.snapshot("ect")
    n_before = len(t_before)

    for i in range(10, 5000):
        store.add_sample("ect", float(i), float(i))

    # La vista antigua no cambia de tamaño ni de contenido
    assert len(t_before) == n_before
    assert np.array_equal(v_before, np.arange(10, dtype=np.float64))


def test_compaction_keeps_recent_half_and_old_views_intact():
    store = DataStore(max_points_per_signal=1000)
    for i in range(1000):
        store.add_sample("x", float(i), float(i))
    t_full, v_full = store.snapshot("x")

    store.add_sample("x", 1000.0, 1000.0)  # fuerza compactación
    t_new, v_new = store.snapshot("x")

    assert len(t_new) == 501            # mitad reciente + el nuevo punto
    assert v_new[0] == 500.0 and v_new[-1] == 1000.0
    # La vista antigua sigue intacta (arrays nuevos al compactar)
    assert len(v_full) == 1000 and v_full[0] == 0.0


def test_latest_and_missing_key():
    store = DataStore()
    assert store.latest("nada") is None
    t, v = store.snapshot("nada")
    assert len(t) == 0
    store.add_sample("a", 1.5, 42.0)
    assert store.latest("a") == (1.5, 42.0)
