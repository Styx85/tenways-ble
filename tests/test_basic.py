from tenways_ble.const import (
    BATTERY_LEVEL_UUID,
    TENWAYS_NOTIFY_UUID,
    TENWAYS_SERVICE_UUID,
)


def test_known_uuids() -> None:
    assert BATTERY_LEVEL_UUID == "00002a19-0000-1000-8000-00805f9b34fb"
    assert TENWAYS_SERVICE_UUID.startswith("43480001-")
    assert TENWAYS_NOTIFY_UUID.startswith("43480003-")
