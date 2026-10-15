"""Temperature sensors (for long-term statistics)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DCB_HEATING, SIGNAL_UPDATE
from .entity import HeatmiserEntity, HeatmiserHubEntity
from .protocol import current_temp, floor_temp


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub = entry.runtime_data
    entities = [HeatmiserTemperature(hub, a) for a in hub.addresses]
    entities += [
        HeatmiserFloorTemperature(hub, a)
        for a in hub.addresses
        if hub.dcb.get(a) is not None and floor_temp(hub.dcb[a]) is not None
    ]
    entities.append(HeatmiserRoomsHeating(hub))
    async_add_entities(entities)


class HeatmiserTemperature(HeatmiserEntity, SensorEntity):
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 0

    def __init__(self, hub, addr) -> None:
        super().__init__(hub, addr, "temperature")

    @property
    def native_value(self):
        return current_temp(self._d) if self._d else None


class HeatmiserFloorTemperature(HeatmiserEntity, SensorEntity):
    _attr_name = "Floor temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 0

    def __init__(self, hub, addr) -> None:
        super().__init__(hub, addr, "floor_temperature")

    @property
    def native_value(self):
        return floor_temp(self._d) if self._d else None


class HeatmiserRoomsHeating(HeatmiserHubEntity, SensorEntity):
    """How many rooms are calling for heat right now."""

    _attr_name = "Rooms heating"
    _attr_icon = "mdi:radiator"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "rooms"

    def __init__(self, hub) -> None:
        super().__init__(hub, "rooms_heating")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for addr in self._hub.addresses:
            self.async_on_remove(
                async_dispatcher_connect(self.hass, SIGNAL_UPDATE.format(addr), self.async_write_ha_state)
            )

    @property
    def available(self) -> bool:
        return self._hub.connected and bool(self._hub.dcb)

    @property
    def native_value(self):
        return sum(1 for a in self._hub.addresses if self._hub.available(a) and self._hub.dcb[a][DCB_HEATING])

    @property
    def extra_state_attributes(self):
        return {
            "rooms": [
                self._hub.names.get(a, str(a))
                for a in self._hub.addresses
                if self._hub.available(a) and self._hub.dcb[a][DCB_HEATING]
            ]
        }
