"""Data coordinator for EV Charge Log."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
import uuid

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EvccApi, EvccApiError
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_FUEL_TYPE,
    CONF_GRID_CO2,
    CONF_ODOMETER_ENTITY,
    CONF_VEHICLES,
    CONF_WLTP_CONSUMPTION,
    DEFAULT_FUEL_TYPE,
    DEFAULT_GRID_CO2,
    FUEL_CO2_KG_PER_L,
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
    DOMAIN,
    RECENT_SESSIONS,
    SOURCE_MANUAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .stats import Stats, compute, normalize_evcc_session

_LOGGER = logging.getLogger(__name__)


class EvChargeLogCoordinator(DataUpdateCoordinator[Stats]):
    """Fetches evcc sessions, merges manual ones and computes statistics."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        opts = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        url = opts.get(CONF_URL)
        self.api = EvccApi(async_get_clientsession(hass), url) if url else None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self.manual_sessions: list[dict[str, Any]] = []
        self.evcc_sessions: list[dict[str, Any]] = []
        self.last_odometer: float | None = None
        self.active: dict[str, Any] | None = None
        self._active_listeners: list[Callable[[], None]] = []
        self.evcc_available = False

    # ------------------------------------------------------------------ options
    @property
    def options(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def fuel_price(self) -> float:
        entity_id = self.options.get(CONF_FUEL_PRICE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state is not None:
                try:
                    return float(state.state)
                except ValueError:
                    pass
        return float(self.options.get(CONF_FUEL_PRICE, DEFAULT_FUEL_PRICE))

    # ------------------------------------------------------------------ storage
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.manual_sessions = data.get("sessions", [])
        self.last_odometer = data.get("last_odometer")
        self.active = data.get("active")

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "sessions": self.manual_sessions,
                "last_odometer": self.last_odometer,
                "active": self.active,
            }
        )

    # ------------------------------------------------------------------ update
    def _entity_odometer(self) -> float | None:
        entity_id = self.options.get(CONF_ODOMETER_ENTITY)
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _vehicle_matches(self, title: str | None) -> bool:
        title = (title or "").lower()
        selected = [v.lower() for v in self.options.get(CONF_VEHICLES) or []]
        if selected:
            return title in selected
        legacy = [
            v.strip().lower()
            for v in (self.options.get(CONF_VEHICLE_FILTER) or "").split(",")
            if v.strip()
        ]
        return not legacy or any(f in title for f in legacy)

    async def _async_update_data(self) -> Stats:
        raw, odometer = None, None
        if self.api is not None:
            try:
                raw = await self.api.sessions()
                readings = [
                    odo for title, odo in await self.api.odometers()
                    if self._vehicle_matches(title)
                ]
                odometer = max(readings) if readings else None
                self.evcc_available = True
            except EvccApiError as err:
                self.evcc_available = False
                if not self.evcc_sessions and not self.manual_sessions:
                    raise UpdateFailed(f"evcc not reachable: {err}") from err
                _LOGGER.warning("evcc not reachable, using cached data: %s", err)

        if raw is not None:
            sessions = []
            for item in raw:
                norm = normalize_evcc_session(item)
                if norm is not None and self._vehicle_matches(norm.get("vehicle")):
                    sessions.append(norm)
            self.evcc_sessions = sessions

        entity_odo = self._entity_odometer()
        if entity_odo and (odometer is None or entity_odo > odometer):
            odometer = entity_odo

        if odometer and (self.last_odometer is None or odometer > self.last_odometer):
            self.last_odometer = odometer
            await self._async_save()

        return self._compute()

    def _compute(self) -> Stats:
        fuel_type = self.options.get(CONF_FUEL_TYPE, DEFAULT_FUEL_TYPE)
        return compute(
            self.evcc_sessions + self.manual_sessions,
            now=dt_util.now(),
            current_odometer=self.last_odometer,
            start_odometer=float(
                self.options.get(CONF_START_ODOMETER, DEFAULT_START_ODOMETER)
            ),
            fuel_consumption=float(
                self.options.get(CONF_FUEL_CONSUMPTION, DEFAULT_FUEL_CONSUMPTION)
            ),
            fuel_price=self.fuel_price(),
            fuel_co2_per_l=FUEL_CO2_KG_PER_L.get(fuel_type, FUEL_CO2_KG_PER_L["diesel"]),
            grid_co2=float(self.options.get(CONF_GRID_CO2, DEFAULT_GRID_CO2)),
            battery_capacity=self.options.get(CONF_BATTERY_CAPACITY),
            wltp_consumption=self.options.get(CONF_WLTP_CONSUMPTION),
            recent_count=RECENT_SESSIONS,
        )

    def recompute(self) -> None:
        """Recalculate without fetching evcc (e.g. fuel price changed)."""
        self.async_set_updated_data(self._compute())

    # ------------------------------------------------------------------ manual sessions
    async def async_add_session(
        self, session: dict[str, Any], *, default_odometer: bool = True
    ) -> dict[str, Any]:
        if (
            default_odometer
            and session.get("odometer") is None
            and self.last_odometer is not None
        ):
            session["odometer"] = self.last_odometer
        if session.get("odometer") and (
            self.last_odometer is None or session["odometer"] > self.last_odometer
        ):
            self.last_odometer = session["odometer"]
        session["id"] = f"manual_{uuid.uuid4().hex[:8]}"
        session["source"] = SOURCE_MANUAL
        self.manual_sessions.append(session)
        await self._async_save()
        self.recompute()
        return session

    def _find(self, session_id: str) -> dict[str, Any] | None:
        return next((s for s in self.manual_sessions if s["id"] == session_id), None)

    async def async_update_session(self, session_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        session = self._find(session_id)
        if session is None:
            return None
        session.update(changes)
        await self._async_save()
        self.recompute()
        return session

    async def async_delete_session(self, session_id: str) -> bool:
        session = self._find(session_id)
        if session is None:
            return False
        self.manual_sessions.remove(session)
        await self._async_save()
        self.recompute()
        return True

    # ------------------------------------------------------------------ charging timer
    @callback
    def async_add_active_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._active_listeners.append(update)
        return lambda: self._active_listeners.remove(update)

    def _notify_active(self) -> None:
        for update in list(self._active_listeners):
            update()

    async def async_start_timer(self, location: str | None) -> dict[str, Any]:
        """Remember that a public charging session has started (persists restarts)."""
        if self.active is None:
            self.active = {"start": dt_util.now().isoformat(timespec="seconds"), "location": location}
        elif location:
            self.active["location"] = location
        await self._async_save()
        self._notify_active()
        return dict(self.active)

    async def async_stop_timer(self) -> dict[str, Any] | None:
        """End the running timer and return start + duration in minutes."""
        if self.active is None:
            return None
        start = dt_util.parse_datetime(self.active["start"])
        result = {
            **self.active,
            "end": dt_util.now().isoformat(timespec="seconds"),
            "duration": max(round((dt_util.now() - start).total_seconds() / 60), 1)
            if start
            else None,
        }
        self.active = None
        await self._async_save()
        self._notify_active()
        return result

    async def async_cancel_timer(self) -> bool:
        if self.active is None:
            return False
        self.active = None
        await self._async_save()
        self._notify_active()
        return True

    def all_sessions(self) -> list[dict[str, Any]]:
        return sorted(
            self.evcc_sessions + self.manual_sessions, key=lambda s: s.get("start") or ""
        )
