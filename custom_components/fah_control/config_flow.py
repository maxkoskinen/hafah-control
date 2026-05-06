from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    WS_CONNECT_TIMEOUT,
    WS_PATH,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


class FahControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Folding@Home Control."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = user_input[CONF_PORT]
            name: str = user_input[CONF_NAME]

            if await self._test_connection(host, port):
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                    },
                )

            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, host: str, port: int) -> bool:
        """Test if we can connect to the Folding@Home WebSocket API."""
        session = async_get_clientsession(self.hass)
        url = f"ws://{host}:{port}{WS_PATH}"

        try:
            async with asyncio.timeout(WS_CONNECT_TIMEOUT):
                ws_connection = await session.ws_connect(url)
                try:
                    await ws_connection.receive()
                    return True
                finally:
                    await ws_connection.close()
        except (
            aiohttp.ClientConnectorError,
            ConnectionRefusedError,
            OSError,
            asyncio.TimeoutError,
        ):
            _LOGGER.debug(
                "Failed to connect to Folding@Home at %s:%s", host, port
            )
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> FahOptionsFlowHandler:
        """Get the options flow for this handler."""
        return FahOptionsFlowHandler()


class FahOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Folding@Home Control."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
