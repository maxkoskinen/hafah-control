from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SELECT_OPTIONS, STATE_TO_SELECT
from .coordinator import FahDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Folding@Home select from a config entry."""
    coordinator: FahDataUpdateCoordinator = entry.runtime_data
    async_add_entities([FahControlSelect(coordinator)])


class FahControlSelect(SelectEntity):
    """Select entity to control Folding@Home state (fold / pause / finish)."""

    _attr_has_entity_name = True
    _attr_name = "Control"
    _attr_icon = "mdi:protein"
    _attr_options = SELECT_OPTIONS

    def __init__(self, coordinator: FahDataUpdateCoordinator) -> None:
        """Initialize the Folding@Home control select."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.host}_{coordinator.port}_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.host}:{coordinator.port}")},
            name=coordinator.fah_name,
            manufacturer="Folding@Home Consortium",
            model="FAH v8 Client",
            configuration_url=f"https://{coordinator.host}:{coordinator.port}",
        )
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
            self._attr_current_option = None
        else:
            self._attr_available = True
            state: str | None = data.get("state")
            self._attr_current_option = (
                STATE_TO_SELECT.get(state) if state is not None else None
            )

    async def async_select_option(self, option: str) -> None:
        """Send the selected command to the FAH client."""
        await self.coordinator.async_send_command(option)
