"""Climate entity per Heatmiser thermostat."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature

from .const import (
    DCB_ERROR,
    DCB_FROST_TEMP,
    DCB_HEATING,
    DCB_HOLD,
    DCB_HOLIDAY,
    DCB_KEY_LOCK,
    DCB_ON_OFF,
    DCB_PROGRAM_MODE,
    DCB_RUN_MODE,
    DCB_SENSOR,
    DCB_SET_TEMP,
    DCB_WEEKDAY,
    DCB_WEEKEND,
    REG_ON_OFF,
    REG_RUN_MODE,
    REG_SET_TEMP,
)
from .entity import HeatmiserEntity
from .protocol import SENSOR_NAMES, current_temp, floor_temp, schedule, word

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub = entry.runtime_data
    async_add_entities(HeatmiserClimate(hub, addr) for addr in hub.addresses)


class HeatmiserClimate(HeatmiserEntity, ClimateEntity):
    """A room thermostat. Off = Frost (frost protection stays active)."""

    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1
    _attr_min_temp = 5
    _attr_max_temp = 35

    def __init__(self, hub, addr) -> None:
        super().__init__(hub, addr, "climate")

    @property
    def hvac_mode(self) -> HVACMode | None:
        d = self._d
        if d is None:
            return None
        return HVACMode.OFF if (d[DCB_ON_OFF] == 0 or d[DCB_RUN_MODE] == 1) else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        d = self._d
        if d is None:
            return None
        if d[DCB_HEATING]:
            return HVACAction.HEATING
        return HVACAction.OFF if self.hvac_mode == HVACMode.OFF else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return current_temp(self._d) if self._d else None

    @property
    def target_temperature(self) -> float | None:
        # The thermostat keeps its set temperature in Frost mode too; it applies when switched back to Heat
        d = self._d
        return None if d is None else d[DCB_SET_TEMP]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self._d
        if d is None:
            return None
        if d[DCB_HEATING]:
            status = "Heating"
        elif d[DCB_ON_OFF] == 0:
            status = "Thermostat off"
        elif d[DCB_RUN_MODE] == 1:
            status = "Frost"
        else:
            status = "Idle"
        return {
            "status": status,
            "set_temperature": d[DCB_SET_TEMP],
            "frost_temperature": d[DCB_FROST_TEMP],
            "mode": "Frost" if d[DCB_RUN_MODE] == 1 else "Heat",
            "thermostat_power": "on" if d[DCB_ON_OFF] else "off",
            "floor_temperature": floor_temp(d),
            "sensor": SENSOR_NAMES.get(d[DCB_SENSOR], d[DCB_SENSOR]),
            # Program slots are only decoded in 5/2-day mode (7-day mode uses a longer, different layout)
            "weekday_program": schedule(d, DCB_WEEKDAY) if d[DCB_PROGRAM_MODE] == 0 else None,
            "weekend_program": schedule(d, DCB_WEEKEND) if d[DCB_PROGRAM_MODE] == 0 else None,
            "program_mode": "5/2 day" if d[DCB_PROGRAM_MODE] == 0 else "7 day",
            "holiday_hours": word(d, DCB_HOLIDAY),
            "hold_minutes": word(d, DCB_HOLD),
            "keys_locked": bool(d[DCB_KEY_LOCK]),
            "error_code": d[DCB_ERROR],
            "bus_address": self._addr,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(mode)
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            value = int(round(float(temp)))
            value = max(self._attr_min_temp, min(self._attr_max_temp, value))
            await self._hub.async_write(self._addr, REG_SET_TEMP, [value])

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        d = self._d
        if hvac_mode == HVACMode.HEAT:
            if d is not None and d[DCB_ON_OFF] == 0:
                await self._hub.async_write(self._addr, REG_ON_OFF, [1])
            if d is None or d[DCB_RUN_MODE] != 0:
                await self._hub.async_write(self._addr, REG_RUN_MODE, [0])
        elif hvac_mode == HVACMode.OFF:
            # Frost mode, not power-off, so frost protection stays on
            if d is None or d[DCB_RUN_MODE] != 1:
                await self._hub.async_write(self._addr, REG_RUN_MODE, [1])

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
