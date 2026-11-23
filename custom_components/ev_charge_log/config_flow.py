"""Config flow for EV Charge Log."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EvccApi, EvccApiError
from .const import (
    CONF_FUEL_CONSUMPTION,
    CONF_FUEL_PRICE,
    CONF_FUEL_PRICE_ENTITY,
    CONF_SCAN_INTERVAL,
    CONF_START_ODOMETER,
    CONF_URL,
    CONF_VEHICLE_FILTER,
    DEFAULT_FUEL_CONSUMPTION,
    DEFAULT_FUEL_PRICE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_START_ODOMETER,
    DEFAULT_URL,
    DOMAIN,
)


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    price_entity = current.get(CONF_FUEL_PRICE_ENTITY)
    return vol.Schema(
        {
            vol.Required(
                CONF_FUEL_CONSUMPTION,
                default=current.get(CONF_FUEL_CONSUMPTION, DEFAULT_FUEL_CONSUMPTION),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, step=0.1, unit_of_measurement="l/100 km",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_FUEL_PRICE,
                default=current.get(CONF_FUEL_PRICE, DEFAULT_FUEL_PRICE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.001, unit_of_measurement="€/l",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_FUEL_PRICE_ENTITY,
                description={"suggested_value": price_entity} if price_entity else None,
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_START_ODOMETER,
                default=current.get(CONF_START_ODOMETER, DEFAULT_START_ODOMETER),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1_000_000, step=1, unit_of_measurement="km",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_VEHICLE_FILTER,
                description={"suggested_value": current.get(CONF_VEHICLE_FILTER, "")},
            ): selector.TextSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=120, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


class EvChargeLogConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def _test(self, url: str) -> str | None:
        try:
            await EvccApi(async_get_clientsession(self.hass), url).sessions()
        except EvccApiError:
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            self._async_abort_entries_match({CONF_URL: url})
            if (err := await self._test(url)) is None:
                return self.async_create_entry(
                    title="EV Ladebuch",
                    data={CONF_URL: url},
                    options={k: v for k, v in user_input.items() if k != CONF_URL},
                )
            errors["base"] = err
        schema = vol.Schema(
            {vol.Required(CONF_URL, default=DEFAULT_URL): str}
        ).extend(_options_schema(user_input or {}).schema)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            if (err := await self._test(url)) is None:
                return self.async_update_reload_and_abort(entry, data={CONF_URL: url})
            errors["base"] = err
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_URL, default=entry.data[CONF_URL]): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EvChargeLogOptionsFlow()


class EvChargeLogOptionsFlow(OptionsFlow):
    """Options: fuel comparison, start odometer, polling."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(dict(self.config_entry.options))
        )
