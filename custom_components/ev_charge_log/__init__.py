"""EV Charge Log – combines evcc charging sessions with manually logged public charges."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CHARGE_TYPE,
    ATTR_COST,
    ATTR_DATE,
    ATTR_DURATION,
    ATTR_ENERGY,
    ATTR_ENTRY_ID,
    ATTR_LOCATION,
    ATTR_NOTE,
    ATTR_ODOMETER,
    ATTR_SESSION_ID,
    ATTR_WAITING_TIME,
    CONF_FUEL_PRICE_ENTITY,
    DOMAIN,
    SERVICE_ADD_SESSION,
    SERVICE_DELETE_SESSION,
    SERVICE_LIST_SESSIONS,
    SERVICE_UPDATE_SESSION,
)
from .coordinator import EvChargeLogCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EvChargeLogConfigEntry = ConfigEntry[EvChargeLogCoordinator]

_SESSION_FIELDS = {
    vol.Optional(ATTR_DATE): cv.datetime,
    vol.Optional(ATTR_ODOMETER): vol.Coerce(float),
    vol.Optional(ATTR_DURATION): vol.Coerce(float),
    vol.Optional(ATTR_WAITING_TIME): vol.Coerce(float),
    vol.Optional(ATTR_CHARGE_TYPE): vol.In(["AC", "DC"]),
    vol.Optional(ATTR_NOTE): cv.string,
    vol.Optional(ATTR_ENTRY_ID): cv.string,
}

ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LOCATION): cv.string,
        vol.Required(ATTR_ENERGY): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Required(ATTR_COST): vol.All(vol.Coerce(float), vol.Range(min=0)),
        **_SESSION_FIELDS,
    }
)
UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SESSION_ID): cv.string,
        vol.Optional(ATTR_LOCATION): cv.string,
        vol.Optional(ATTR_ENERGY): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Optional(ATTR_COST): vol.All(vol.Coerce(float), vol.Range(min=0)),
        **_SESSION_FIELDS,
    }
)
DELETE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_SESSION_ID): cv.string, vol.Optional(ATTR_ENTRY_ID): cv.string}
)
LIST_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> EvChargeLogCoordinator:
    entries: list[EvChargeLogConfigEntry] = [
        e for e in hass.config_entries.async_loaded_entries(DOMAIN)
    ]
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_entry"
        )
    return entries[0].runtime_data


def _to_session(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ATTR_DATE in data:
        date: datetime = data[ATTR_DATE]
        if date.tzinfo is None:
            date = date.replace(tzinfo=dt_util.get_default_time_zone())
        out["start"] = date.isoformat()
    for key in (
        ATTR_LOCATION,
        ATTR_ENERGY,
        ATTR_COST,
        ATTR_ODOMETER,
        ATTR_DURATION,
        ATTR_WAITING_TIME,
        ATTR_CHARGE_TYPE,
        ATTR_NOTE,
    ):
        if key in data:
            out[key] = data[key]
    return out


CARD_URL = f"/{DOMAIN}/ev-charge-log-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the form card and load it in every dashboard automatically."""
    integration = await async_get_integration(hass, DOMAIN)
    path = Path(__file__).parent / "frontend" / "ev-charge-log-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and the dashboard card."""
    await _async_register_card(hass)

    async def add_session(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        session = {
            "start": dt_util.now().isoformat(),
            "end": None,
            "odometer": None,
            "duration": None,
            "waiting_time": None,
            "charge_type": None,
            "solar_percentage": None,
            "note": None,
            **_to_session(call.data),
        }
        # only assume the current odometer for sessions logged "now" (not back-dated)
        default_odometer = True
        if ATTR_DATE in call.data:
            date: datetime = call.data[ATTR_DATE]
            if date.tzinfo is None:
                date = date.replace(tzinfo=dt_util.get_default_time_zone())
            default_odometer = abs(dt_util.now() - date) < timedelta(hours=12)
        stored = await coord.async_add_session(session, default_odometer=default_odometer)
        return {"session": stored}

    async def update_session(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        changes = _to_session(call.data)
        stored = await coord.async_update_session(call.data[ATTR_SESSION_ID], changes)
        if stored is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_session",
                translation_placeholders={"id": call.data[ATTR_SESSION_ID]},
            )
        return {"session": stored}

    async def delete_session(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        if not await coord.async_delete_session(call.data[ATTR_SESSION_ID]):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_session",
                translation_placeholders={"id": call.data[ATTR_SESSION_ID]},
            )

    async def list_sessions(call: ServiceCall) -> ServiceResponse:
        coord = _coordinator(hass, call)
        stats = coord.data
        return {
            "sessions": coord.all_sessions(),
            "monthly": stats.monthly if stats else [],
            "odometer": coord.last_odometer,
        }

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_SESSION, add_session, ADD_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SESSION,
        update_session,
        UPDATE_SCHEMA,
        SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_SESSION, delete_session, DELETE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LIST_SESSIONS, list_sessions, LIST_SCHEMA, SupportsResponse.ONLY
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EvChargeLogConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = EvChargeLogCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    price_entity = coordinator.options.get(CONF_FUEL_PRICE_ENTITY)
    if price_entity:

        @callback
        def _price_changed(event: Event[EventStateChangedData]) -> None:
            coordinator.recompute()

        entry.async_on_unload(
            async_track_state_change_event(hass, [price_entity], _price_changed)
        )

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: EvChargeLogConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EvChargeLogConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
