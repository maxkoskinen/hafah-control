from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATE_OFFLINE
from .coordinator import FahDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Folding@Home sensors from a config entry."""
    coordinator: FahDataUpdateCoordinator = entry.runtime_data
    async_add_entities([FahStateSensor(coordinator), FahPPDSensor(coordinator)])


def _build_device_info(coordinator: FahDataUpdateCoordinator) -> DeviceInfo:
    """Build a DeviceInfo dict shared by all sensors on the same FAH client."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.host}:{coordinator.port}")},
        name=coordinator.fah_name,
        manufacturer="Folding@Home Consortium",
        model="FAH v8 Client",
        configuration_url=f"https://{coordinator.host}:{coordinator.port}",
    )


def _build_state_attributes(
    coordinator: FahDataUpdateCoordinator,
) -> dict[str, Any]:
    """Build extra state attributes for the FAH state sensor."""
    data = coordinator.data
    if data is None or not data.get("available", False):
        return {
            "host": coordinator.host,
            "port": coordinator.port,
            "groups": [],
            "fah_version": None,
            "cpu": None,
            "gpus": [],
            "os": None,
            "user": None,
            "team": None,
            "work_units": [],
        }

    machine_info: dict[str, Any] = data.get("machine_info", {})
    account: dict[str, Any] = data.get("account", {})

    os_name = machine_info.get("os", "")
    os_version = machine_info.get("os_version", "")
    os_display = f"{os_name} {os_version}".strip() or None

    return {
        "host": coordinator.host,
        "port": coordinator.port,
        "groups": data.get("groups", []),
        "fah_version": machine_info.get("version"),
        "cpu": machine_info.get("cpu_brand"),
        "gpus": machine_info.get("gpus", []),
        "os": os_display,
        "user": account.get("user"),
        "team": account.get("team"),
        "work_units": [
            {
                "number": unit.get("number"),
                "state": unit.get("state"),
                "progress": unit.get("progress"),
                "eta": unit.get("eta"),
                "ppd": unit.get("ppd"),
                "run_time": unit.get("run_time"),
                "project": unit.get("project"),
                "credit": unit.get("credit"),
                "cpus": unit.get("cpus"),
                "gpus": unit.get("gpus", []),
                "description": unit.get("description"),
            }
            for unit in data.get("units", [])
        ],
    }


def _build_ppd_attributes(
    coordinator: FahDataUpdateCoordinator,
) -> dict[str, Any]:
    """Build extra state attributes for the FAH PPD sensor."""
    data = coordinator.data
    if data is None or not data.get("available", False):
        return {"unit_details": []}

    return {
        "unit_details": [
            {
                "description": unit.get("description"),
                "ppd": unit.get("ppd"),
                "progress": unit.get("progress"),
                "eta": unit.get("eta"),
                "project": unit.get("project"),
            }
            for unit in data.get("units", [])
        ],
    }


class FahStateSensor(SensorEntity):
    """Sensor representing the current state of a Folding@Home v8 client."""

    _attr_has_entity_name = True
    _attr_name = "State"
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: FahDataUpdateCoordinator) -> None:
        """Initialise the FAH state sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_state"
        self._attr_device_info = _build_device_info(coordinator)
        self._update_attrs()

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates when added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        self.async_write_ha_state()

    def _update_attrs(self) -> None:
        """Recompute all dynamic attributes from coordinator data."""
        data = self.coordinator.data
        if data is None or not data.get("available", False):
            self._attr_available = False
            self._attr_native_value = STATE_OFFLINE
        else:
            self._attr_available = True
            self._attr_native_value = data.get("state", STATE_OFFLINE)
        self._attr_extra_state_attributes = _build_state_attributes(
            self.coordinator
        )


class FahPPDSensor(SensorEntity):
    """Numeric sensor for total Folding@Home points per day (PPD)."""

    _attr_has_entity_name = True
    _attr_name = "Points Per Day"
    _attr_icon = "mdi:star-four-points"
    _attr_native_unit_of_measurement = "PPD"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FahDataUpdateCoordinator) -> None:
        """Initialise the FAH PPD sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_ppd"
        self._attr_device_info = _build_device_info(coordinator)
        self._update_attrs()

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates when added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        self.async_write_ha_state()

    def _update_attrs(self) -> None:
        """Recompute all dynamic attributes from coordinator data."""
        data = self.coordinator.data
        if data is None or not data.get("available", False):
            self._attr_available = False
            self._attr_native_value = None
        else:
            self._attr_available = True
            self._attr_native_value = data.get("total_ppd", 0)
        self._attr_extra_state_attributes = _build_ppd_attributes(
            self.coordinator
        )
