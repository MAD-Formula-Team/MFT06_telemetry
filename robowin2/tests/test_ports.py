from robowin2.core.ports import classify_port, sort_candidates


def test_classification_and_ordering():
    esp32 = classify_port("COM7", "USB Serial Device", 0x303A, 0x1001)
    cp210x = classify_port("COM5", "Silicon Labs CP210x UART Bridge", 0x10C4, 0xEA60)
    bluetooth = classify_port("COM3", "Standard Serial over Bluetooth link", None, None)
    unknown = classify_port("COM9", "Puerto serie", None, None)

    assert esp32.preferred and not esp32.bluetooth
    assert cp210x.preferred
    assert bluetooth.bluetooth and not bluetooth.preferred

    ordered = sort_candidates([bluetooth, unknown, esp32, cp210x])
    devices = [p.device for p in ordered]
    # Adaptadores conocidos primero, Bluetooth el último
    assert devices[:2] == ["COM5", "COM7"]
    assert devices[-1] == "COM3"


def test_label_shows_chip_name():
    esp32 = classify_port("COM7", "USB Serial Device", 0x303A, None)
    assert "Espressif" in esp32.label
