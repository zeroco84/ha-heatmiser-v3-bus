"""Button to set every thermostat clock now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import HeatmiserHubEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([HeatmiserSyncClocks(entry.runtime_data)])


class HeatmiserSyncClocks(HeatmiserHubEntity, ButtonEntity):
    _attr_name = "Sync thermostat clocks"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub) -> None:
        super().__init__(hub, "sync_clocks")

    async def async_press(self) -> None:
        await self._hub.async_sync_clocks(force=True)
