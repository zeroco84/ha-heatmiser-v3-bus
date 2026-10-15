"""Heatmiser V3 bus (RS-485 via a TCP converter) integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import CONF_THERMOSTATS, DOMAIN
from .hub import HeatmiserBus

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CLIMATE, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
SYNC_SCHEMA = vol.Schema({vol.Optional("force", default=False): cv.boolean})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the clock-sync service once."""

    async def _svc_sync(call: ServiceCall) -> None:
        hubs = [e.runtime_data for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
        if not hubs:
            raise HomeAssistantError("No Heatmiser bus is loaded")
        for hub in hubs:
            await hub.async_sync_clocks(force=call.data["force"])

    hass.services.async_register(DOMAIN, "sync_clocks", _svc_sync, schema=SYNC_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    names = {int(k): v for k, v in entry.data[CONF_THERMOSTATS].items()}
    hub = HeatmiserBus(hass, entry.data[CONF_HOST], entry.data[CONF_PORT], names)
    await hub.async_start()
    # Give the Touchpad one polling cycle so thermostat models and readings are known
    await hub.async_wait_first_data(15)
    entry.runtime_data = hub
    entry.async_on_unload(hub.async_stop)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "hub")},
        name="Heatmiser Network",
        manufacturer="Heatmiser",
        model="V3 RS-485 bus via RS485-to-Ethernet converter",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _nightly(_now) -> None:
        try:
            await hub.async_sync_clocks()
        except HomeAssistantError as err:
            _LOGGER.warning("%s", err)

    entry.async_on_unload(async_track_time_change(hass, _nightly, hour=3, minute=30, second=0))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
