"""Sensors for EV Charge Log."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfMass,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EvChargeLogConfigEntry
from .const import CONF_BATTERY_CAPACITY, CONF_WLTP_CONSUMPTION, CONF_VEHICLES, DOMAIN
from .coordinator import EvChargeLogCoordinator
from .stats import Stats


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True, kw_only=True)
class EvSensorDescription(SensorEntityDescription):
    """Describes an EV Charge Log sensor."""

    value_fn: Callable[[Stats], Any]
    attrs_fn: Callable[[Stats], dict[str, Any]] | None = None
    currency: bool = False
    per_kwh: bool = False
    per_100km: bool = False


ENERGY = dict(
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    device_class=SensorDeviceClass.ENERGY,
    suggested_display_precision=1,
)
MONEY = dict(
    device_class=SensorDeviceClass.MONETARY,
    state_class=SensorStateClass.TOTAL,
    suggested_display_precision=2,
    currency=True,
)
PRICE = dict(
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=3,
    currency=True,
    per_kwh=True,
)
KM = dict(
    native_unit_of_measurement=UnitOfLength.KILOMETERS,
    device_class=SensorDeviceClass.DISTANCE,
    suggested_display_precision=0,
)

CO2 = dict(
    native_unit_of_measurement=UnitOfMass.KILOGRAMS,
    device_class=SensorDeviceClass.WEIGHT,
    state_class=SensorStateClass.TOTAL,
    suggested_display_precision=0,
)

SENSORS: tuple[EvSensorDescription, ...] = (
    # energy
    EvSensorDescription(key="energy_total", translation_key="energy_total",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: _r(s.total.energy, 3), **ENERGY),
    EvSensorDescription(key="energy_home", translation_key="energy_home",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: _r(s.home.energy, 3), **ENERGY),
    EvSensorDescription(key="energy_external", translation_key="energy_external",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: _r(s.external.energy, 3), **ENERGY),
    EvSensorDescription(key="energy_month", translation_key="energy_month",
        state_class=SensorStateClass.TOTAL, value_fn=lambda s: _r(s.month.energy, 3), **ENERGY),
    EvSensorDescription(key="energy_year", translation_key="energy_year",
        state_class=SensorStateClass.TOTAL, value_fn=lambda s: _r(s.year.energy, 3), **ENERGY),
    # cost
    EvSensorDescription(key="cost_total", translation_key="cost_total",
        value_fn=lambda s: _r(s.total_cost), **MONEY),
    EvSensorDescription(key="cost_home", translation_key="cost_home",
        value_fn=lambda s: _r(s.home_cost), **MONEY),
    EvSensorDescription(key="cost_external", translation_key="cost_external",
        value_fn=lambda s: _r(s.external_cost), **MONEY),
    EvSensorDescription(key="cost_month", translation_key="cost_month",
        value_fn=lambda s: _r(s.month_cost), **MONEY),
    EvSensorDescription(key="cost_year", translation_key="cost_year",
        value_fn=lambda s: _r(s.year_cost), **MONEY),
    # average prices
    EvSensorDescription(key="price_avg", translation_key="price_avg",
        value_fn=lambda s: _r(s.total.avg_price, 4), **PRICE),
    EvSensorDescription(key="price_avg_home", translation_key="price_avg_home",
        value_fn=lambda s: _r(s.home.avg_price, 4), **PRICE),
    EvSensorDescription(key="price_avg_external", translation_key="price_avg_external",
        value_fn=lambda s: _r(s.external.avg_price, 4), **PRICE),
    # fuel comparison
    EvSensorDescription(key="fuel_cost", translation_key="fuel_cost",
        value_fn=lambda s: _r(s.fuel_cost), **MONEY),
    EvSensorDescription(key="savings", translation_key="savings",
        value_fn=lambda s: _r(s.savings), **MONEY),
    EvSensorDescription(key="savings_month", translation_key="savings_month",
        value_fn=lambda s: _r(s.month_savings), **MONEY),
    EvSensorDescription(key="savings_year", translation_key="savings_year",
        value_fn=lambda s: _r(s.year_savings), **MONEY),
    EvSensorDescription(key="cost_per_100km", translation_key="cost_per_100km",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        currency=True, per_100km=True, value_fn=lambda s: _r(s.cost_per_100km)),
    EvSensorDescription(key="fuel_cost_per_100km", translation_key="fuel_cost_per_100km",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        currency=True, per_100km=True, value_fn=lambda s: _r(s.fuel_cost_per_100km),
        attrs_fn=lambda s: {"fuel_consumption": s.fuel_consumption, "fuel_price": s.fuel_price}),
    # CO2
    EvSensorDescription(key="co2_ev", translation_key="co2_ev",
        value_fn=lambda s: _r(s.ev_co2_kg, 1), **CO2),
    EvSensorDescription(key="co2_fuel", translation_key="co2_fuel",
        value_fn=lambda s: _r(s.fuel_co2_kg, 1),
        attrs_fn=lambda s: {"kg_co2_per_litre": s.fuel_co2_per_l}, **CO2),
    EvSensorDescription(key="co2_savings", translation_key="co2_savings",
        value_fn=lambda s: _r(s.co2_savings_kg, 1), **CO2),
    # vehicle
    EvSensorDescription(key="wltp_deviation", translation_key="wltp_deviation",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0, value_fn=lambda s: _r(s.wltp_deviation, 1),
        attrs_fn=lambda s: {"wltp_consumption": s.wltp_consumption}),
    EvSensorDescription(key="range_estimate", translation_key="range_estimate",
        state_class=SensorStateClass.MEASUREMENT, value_fn=lambda s: _r(s.range_estimate, 0),
        attrs_fn=lambda s: {"battery_capacity": s.battery_capacity}, **KM),
    # distance & consumption
    EvSensorDescription(key="odometer", translation_key="odometer",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: s.odometer, **KM),
    EvSensorDescription(key="distance", translation_key="distance",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: s.distance, **KM),
    EvSensorDescription(key="distance_month", translation_key="distance_month",
        state_class=SensorStateClass.TOTAL, value_fn=lambda s: s.distance_month, **KM),
    EvSensorDescription(key="consumption", translation_key="consumption",
        native_unit_of_measurement="kWh/100 km", state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, value_fn=lambda s: _r(s.consumption, 2)),
    # sessions & times
    EvSensorDescription(key="sessions_total", translation_key="sessions_total",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: s.total.sessions),
    EvSensorDescription(key="sessions_external", translation_key="sessions_external",
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: s.external.sessions),
    EvSensorDescription(key="waiting_time", translation_key="waiting_time",
        native_unit_of_measurement=UnitOfTime.MINUTES, device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: _r(s.external.waiting, 0)),
    EvSensorDescription(key="charging_time_external", translation_key="charging_time_external",
        native_unit_of_measurement=UnitOfTime.MINUTES, device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING, value_fn=lambda s: _r(s.external.duration, 0)),
    EvSensorDescription(key="solar_share_home", translation_key="solar_share_home",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0, value_fn=lambda s: _r(s.solar_share_home, 1)),
    # lists
    EvSensorDescription(key="last_session", translation_key="last_session",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: dt_util.parse_datetime(s.recent[0]["date"]) if s.recent else None,
        attrs_fn=lambda s: {"sessions": s.recent}),
    EvSensorDescription(key="monthly_overview", translation_key="monthly_overview",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: len(s.monthly), attrs_fn=lambda s: {"months": s.monthly}),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeLogConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    opts = coordinator.options
    skip = set()
    if not opts.get(CONF_WLTP_CONSUMPTION):
        skip.add("wltp_deviation")
    if not opts.get(CONF_BATTERY_CAPACITY):
        skip.add("range_estimate")
    async_add_entities(
        EvChargeLogSensor(coordinator, d) for d in SENSORS if d.key not in skip
    )


class EvChargeLogSensor(CoordinatorEntity[EvChargeLogCoordinator], SensorEntity):
    """A single statistic."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"sessions", "months"})
    entity_description: EvSensorDescription

    def __init__(self, coordinator: EvChargeLogCoordinator, description: EvSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="EV Charge Log",
            model=", ".join(coordinator.options.get(CONF_VEHICLES) or []) or "EV Charge Log",
            entry_type=DeviceEntryType.SERVICE,
        )
        if description.currency:
            currency = coordinator.hass.config.currency
            if description.per_kwh:
                self._attr_native_unit_of_measurement = f"{currency}/kWh"
            elif description.per_100km:
                self._attr_native_unit_of_measurement = f"{currency}/100 km"
            else:
                self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
