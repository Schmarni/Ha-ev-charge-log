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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EvccApi, EvccApiError
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_FUEL_CONSUMPTION,
    CONF_FUEL_PRICE,
    CONF_FUEL_PRICE_ENTITY,
    CONF_FUEL_TYPE,
    CONF_GRID_CO2,
    CONF_NAME,
    CONF_ODOMETER_ENTITY,
    CONF_SCAN_INTERVAL,
    CONF_START_ODOMETER,
    CONF_URL,
    CONF_USE_EVCC,
    CONF_VEHICLE_FILTER,
    CONF_VEHICLES,
    CONF_WLTP_CONSUMPTION,
    DEFAULT_FUEL_CONSUMPTION,
    DEFAULT_FUEL_PRICE,
    DEFAULT_FUEL_TYPE,
    DEFAULT_GRID_CO2,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_START_ODOMETER,
    DEFAULT_URL,
    DOMAIN,
    FUEL_TYPES,
)


def _box(min_: float, max_: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_, max=max_, step=step, unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _suggested(current: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = current.get(key)
    return {"suggested_value": value} if value not in (None, "") else None


def _vehicle_schema(
    current: dict[str, Any], titles: list[str], *, with_name: bool
) -> dict[Any, Any]:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME))] = (
            selector.TextSelector()
        )
    if titles:
        fields[vol.Optional(CONF_VEHICLES, default=current.get(CONF_VEHICLES, []))] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=titles,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        )
    fields[vol.Optional(CONF_BATTERY_CAPACITY, description=_suggested(current, CONF_BATTERY_CAPACITY))] = (
        _box(1, 250, 0.1, "kWh")
    )
    fields[vol.Optional(CONF_WLTP_CONSUMPTION, description=_suggested(current, CONF_WLTP_CONSUMPTION))] = (
        _box(5, 50, 0.1, "kWh/100 km")
    )
    fields[vol.Optional(CONF_ODOMETER_ENTITY, description=_suggested(current, CONF_ODOMETER_ENTITY))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    )
    return fields


def _comparison_schema(current: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Required(CONF_FUEL_TYPE, default=current.get(CONF_FUEL_TYPE, DEFAULT_FUEL_TYPE)): (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=FUEL_TYPES,
                    translation_key=CONF_FUEL_TYPE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        ),
        vol.Required(
            CONF_FUEL_CONSUMPTION,
            default=current.get(CONF_FUEL_CONSUMPTION, DEFAULT_FUEL_CONSUMPTION),
        ): _box(1, 30, 0.1, "l/100 km"),
        vol.Required(
            CONF_FUEL_PRICE, default=current.get(CONF_FUEL_PRICE, DEFAULT_FUEL_PRICE)
        ): _box(0, 5, 0.001, "€/l"),
        vol.Optional(CONF_FUEL_PRICE_ENTITY, description=_suggested(current, CONF_FUEL_PRICE_ENTITY)): (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
        ),
        vol.Required(
            CONF_START_ODOMETER,
            default=current.get(CONF_START_ODOMETER, DEFAULT_START_ODOMETER),
        ): _box(0, 1_000_000, 1, "km"),
        vol.Required(
            CONF_GRID_CO2, default=current.get(CONF_GRID_CO2, DEFAULT_GRID_CO2)
        ): _box(0, 1500, 1, "g/kWh"),
    }


async def _evcc_vehicles(hass: HomeAssistant, url: str) -> tuple[list[dict[str, Any]], list[str]]:
    return await EvccApi(async_get_clientsession(hass), url).vehicles()


def _titles(configured: list[dict[str, Any]], seen: list[str]) -> list[str]:
    titles = [v["title"] for v in configured]
    return titles + [t for t in seen if t not in titles]


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, "")}


class EvChargeLogConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup: evcc → vehicle → comparison car."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._url: str | None = None
        self._configured: list[dict[str, Any]] = []
        self._seen: list[str] = []
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_USE_EVCC, True):
                url = (user_input.get(CONF_URL) or "").rstrip("/")
                try:
                    self._configured, self._seen = await _evcc_vehicles(self.hass, url)
                except EvccApiError:
                    errors["base"] = "cannot_connect"
                else:
                    self._url = url
                    return await self.async_step_vehicle()
            else:
                self._url = None
                return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USE_EVCC, default=True): selector.BooleanSelector(),
                    vol.Optional(CONF_URL, default=DEFAULT_URL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_vehicle(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        titles = _titles(self._configured, self._seen)
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_comparison()
        first = self._configured[0] if self._configured else {}
        defaults: dict[str, Any] = {
            CONF_NAME: first.get("title") or DEFAULT_NAME,
            # one car in evcc: take every title it ever had (names change over time)
            CONF_VEHICLES: titles if len(self._configured) <= 1 else [first["title"]],
        }
        if first.get("capacity"):
            defaults[CONF_BATTERY_CAPACITY] = first["capacity"]
        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema(_vehicle_schema(defaults, titles, with_name=True)),
            description_placeholders={"count": str(len(self._configured))},
        )

    async def async_step_comparison(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = _clean({**self._options, **user_input})
            name = options.pop(CONF_NAME, DEFAULT_NAME)
            options.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            vehicles = sorted(options.get(CONF_VEHICLES, []))
            await self.async_set_unique_id(
                f"{self._url}|{','.join(vehicles)}" if self._url else f"manual|{name.lower()}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=name, data={CONF_URL: self._url}, options=options
            )
        return self.async_show_form(
            step_id="comparison", data_schema=vol.Schema(_comparison_schema({}))
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_USE_EVCC, True):
                url = (user_input.get(CONF_URL) or "").rstrip("/")
                try:
                    await EvccApi(async_get_clientsession(self.hass), url).sessions()
                except EvccApiError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(entry, data={CONF_URL: url})
            else:
                return self.async_update_reload_and_abort(entry, data={CONF_URL: None})
        url = entry.data.get(CONF_URL)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USE_EVCC, default=bool(url)): selector.BooleanSelector(),
                    vol.Optional(CONF_URL, default=url or DEFAULT_URL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EvChargeLogOptionsFlow()


class EvChargeLogOptionsFlow(OptionsFlow):
    """All settings except the evcc connection."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = dict(self.config_entry.options)
        if user_input is not None:
            data = _clean(user_input)
            data.pop(CONF_VEHICLE_FILTER, None)
            return self.async_create_entry(data=data)

        titles: list[str] = []
        url = self.config_entry.data.get(CONF_URL)
        if url:
            try:
                configured, seen = await _evcc_vehicles(self.hass, url)
                titles = _titles(configured, seen)
            except EvccApiError:
                titles = []
        titles += [t for t in current.get(CONF_VEHICLES, []) if t not in titles]

        schema = {
            **_vehicle_schema(current, titles, with_name=False),
            **_comparison_schema(current),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): _box(1, 120, 1, "min"),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
