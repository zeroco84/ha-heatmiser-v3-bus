"""Whole-house away switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .entity import HeatmiserHubEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([HeatmiserAway(entry.runtime_data)])


class HeatmiserAway(HeatmiserHubEntity, SwitchEntity):
    """On: every room to Frost. Off: rooms that were heating go back to Heat."""

    _attr_name = "Heating away"
    _attr_icon = "mdi:home-export-outline"

    def __init__(self, hub) -> None:
        super().__init__(hub, "away")

    @property
    def is_on(self) -> bool:
        return bool(self._hub.away_saved)

    @property
    def extra_state_attributes(self):
        saved = self._hub.away_saved or {}
        return {
            "rooms_to_restore": [self._hub.names.get(int(a), a) for a, m in saved.items() if m == 0],
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.async_set_away(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_set_away(False)
