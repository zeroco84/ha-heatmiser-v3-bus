"""Config flow: connect to the converter, listen for thermostats, name them."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import CONF_THERMOSTATS, DEFAULT_PORT, DOMAIN
from .protocol import discover

DISCOVERY_SECONDS = 20


def parse_thermostats(text: str) -> dict[str, str]:
    """Manual list: JSON {"3": "Kitchen"} or one 'address=Name' per line / semicolon."""
    text = text.strip()
    if text.startswith("{"):
        data = json.loads(text)
        out = {str(int(k)): str(v).strip() for k, v in data.items()}
    else:
        out = {}
        for part in text.replace("\n", ";").split(";"):
            if not part.strip():
                continue
            addr, name = part.split("=", 1)
            out[str(int(addr.strip()))] = name.strip()
    if not out or not all(1 <= int(a) <= 32 and n for a, n in out.items()):
        raise ValueError
    return out


class HeatmiserBusConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._found: list[int] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            self._port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{self._host}:{self._port}")
            self._abort_if_unique_id_configured()
            manual = (user_input.get(CONF_THERMOSTATS) or "").strip()
            if manual:
                try:
                    stats = parse_thermostats(manual)
                except (ValueError, json.JSONDecodeError):
                    errors[CONF_THERMOSTATS] = "bad_thermostats"
                else:
                    return self._create(stats)
            else:
                try:
                    self._found = await discover(self._host, self._port, DISCOVERY_SECONDS)
                except (OSError, TimeoutError):
                    errors["base"] = "cannot_connect"
                else:
                    if self._found:
                        return await self.async_step_name()
                    errors["base"] = "none_heard"
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host): str,
                vol.Required(CONF_PORT, default=self._port): int,
                vol.Optional(CONF_THERMOSTATS, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            stats = {
                str(addr): (user_input.get(f"Address {addr}") or "").strip() or f"Thermostat {addr}"
                for addr in self._found
            }
            return self._create(stats)
        schema = vol.Schema({vol.Optional(f"Address {a}", default=f"Thermostat {a}"): str for a in self._found})
        return self.async_show_form(
            step_id="name",
            data_schema=schema,
            description_placeholders={"count": str(len(self._found)), "addresses": ", ".join(map(str, self._found))},
        )

    def _create(self, stats: dict[str, str]) -> ConfigFlowResult:
        return self.async_create_entry(
            title="Heatmiser",
            data={CONF_HOST: self._host, CONF_PORT: self._port, CONF_THERMOSTATS: stats},
        )
