from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import FahDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("group"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Folding@Home Control from a config entry."""
    coordinator = FahDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Folding@Home Control config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register Folding@Home Control services (only once)."""
    if hass.services.has_service(DOMAIN, "fold"):
        return

    async def _async_handle_command(call: ServiceCall, state: str) -> None:
        """Resolve the entity's coordinator and send a command."""
        entity_id: str = call.data["entity_id"]
        group: str | None = call.data.get("group")

        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)

        if entry is None or entry.config_entry_id is None:
            _LOGGER.error(
                "Could not find a config entry for entity %s", entity_id
            )
            return

        config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)

        if config_entry is None:
            _LOGGER.error(
                "Config entry %s not found for entity %s",
                entry.config_entry_id,
                entity_id,
            )
            return

        coordinator: FahDataUpdateCoordinator = config_entry.runtime_data

        await coordinator.async_send_command(state=state, group=group)

    async def async_handle_fold(call: ServiceCall) -> None:
        """Handle the fold service call."""
        await _async_handle_command(call, state="fold")

    async def async_handle_pause(call: ServiceCall) -> None:
        """Handle the pause service call."""
        await _async_handle_command(call, state="pause")

    async def async_handle_finish(call: ServiceCall) -> None:
        """Handle the finish service call."""
        await _async_handle_command(call, state="finish")

    hass.services.async_register(
        DOMAIN, "fold", async_handle_fold, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "pause", async_handle_pause, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "finish", async_handle_finish, schema=SERVICE_SCHEMA
    )
