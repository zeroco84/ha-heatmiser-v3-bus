"""Base entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DCB_MODEL, DOMAIN, MODELS, SIGNAL_STATUS, SIGNAL_UPDATE
from .hub import HeatmiserBus


class HeatmiserEntity(Entity):
    """Entity for one thermostat."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: HeatmiserBus, addr: int, key: str) -> None:
        self._hub = hub
        self._addr = addr
        self._attr_unique_id = f"{DOMAIN}_{addr}_{key}"
        data = hub.dcb.get(addr)
        model = MODELS.get(data[DCB_MODEL], "V3") if data else "V3"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"stat_{addr}")},
            name=hub.names.get(addr, f"Heatmiser {addr}"),
            manufacturer="Heatmiser",
            model=f"{model} thermostat",
            serial_number=f"Bus address {addr}",
        )

    @property
    def _d(self) -> bytes | None:
        return self._hub.dcb.get(self._addr)

    @property
    def available(self) -> bool:
        return self._hub.available(self._addr) and self._d is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE.format(self._addr), self.async_write_ha_state)
        )


class HeatmiserHubEntity(Entity):
    """Entity on the bus/hub device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: HeatmiserBus, key: str) -> None:
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "hub")})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_STATUS, self.async_write_ha_state))
