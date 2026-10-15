"""Binary sensors: heating demand per room, bus connectivity."""

from __future__ import annotations

import time

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .const import DCB_HEATING
from .entity import HeatmiserEntity, HeatmiserHubEntity

SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub = entry.runtime_data
    entities = [HeatmiserHeating(hub, a) for a in hub.addresses]
    entities.append(HeatmiserBusConnected(hub))
    async_add_entities(entities)


class HeatmiserHeating(HeatmiserEntity, BinarySensorEntity):
    _attr_name = "Heating"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, hub, addr) -> None:
        super().__init__(hub, addr, "heating")

    @property
    def is_on(self):
        return bool(self._d[DCB_HEATING]) if self._d else None


class HeatmiserBusConnected(HeatmiserHubEntity, BinarySensorEntity):
    _attr_name = "Bus"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True  # refresh the traffic counters once a minute
    _unrecorded_attributes = frozenset({"frames", "writes", "write_retries", "write_failures", "own_polls"})

    def __init__(self, hub) -> None:
        super().__init__(hub, "bus")

    @property
    def is_on(self):
        return self._hub.connected

    @property
    def extra_state_attributes(self):
        tp = self._hub.touchpad_seen
        return {
            "thermostats_heard": sum(1 for a in self._hub.addresses if self._hub.available(a)),
            "touchpad_polling": bool(tp) and time.monotonic() - tp < 30,
            **self._hub.stats,
        }
