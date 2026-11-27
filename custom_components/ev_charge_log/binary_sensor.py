"""Binary sensor: a public charging session timer is running."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvChargeLogConfigEntry
from .const import DOMAIN
from .coordinator import EvChargeLogCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeLogConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChargingTimerSensor(entry.runtime_data)])


class ChargingTimerSensor(BinarySensorEntity):
    """On while a public charging session is being timed."""

    _attr_has_entity_name = True
    _attr_translation_key = "timer_running"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_should_poll = False

    def __init__(self, coordinator: EvChargeLogCoordinator) -> None:
        self._coord = coordinator
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_timer_running"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coord.async_add_active_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._coord.active is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        active = self._coord.active or {}
        return {
            "start": active.get("start"),
            "location": active.get("location"),
            "config_entry_id": self._coord.config_entry.entry_id,
        }
