from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    STATE_FINISHING,
    STATE_FOLDING,
    STATE_OFFLINE,
    STATE_PAUSED,
    WS_CONNECT_TIMEOUT,
    WS_PATH,
)

_LOGGER = logging.getLogger(__name__)

# Reusable "unavailable" response returned whenever we cannot determine real
# state from the remote client.
_UNAVAILABLE: dict[str, Any] = {
    "available": False,
    "state": STATE_OFFLINE,
    "groups": [],
    "raw": {},
}


class FahDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a Folding@Home v8 client over WebSocket.

    On each update cycle the coordinator:
    1. Opens a WebSocket to the FAH client.
    2. Reads the initial state-dump message that the client sends immediately.
    3. Parses the JSON payload to extract the folding state and group list.
    4. Closes the WebSocket and returns structured data for entities to consume.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry that holds connection parameters.
        """
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data[CONF_PORT]
        self.fah_name: str = entry.data.get(CONF_NAME, self.host)
        poll_interval: int = entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.host}_{self.port}",
            update_interval=timedelta(seconds=poll_interval),
            config_entry=entry,
        )

    @property
    def ws_url(self) -> str:
        """Return the full WebSocket URL for the FAH client."""
        return f"ws://{self.host}:{self.port}{WS_PATH}"

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current state from the FAH client via WebSocket.

        Returns a dict with the following shape::

            {
                "available": bool,
                "state": "folding" | "paused" | "finishing" | "offline",
                "groups": ["group-name", ...],
                "raw": { ... full parsed JSON ... },
            }

        Connection errors are handled gracefully and never raise
        ``UpdateFailed`` — the coordinator simply reports the client as
        unavailable/offline so that HA does not log noisy warnings for
        machines that are powered off.
        """
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(WS_CONNECT_TIMEOUT):
                ws = await session.ws_connect(self.ws_url)

            try:
                msg = await asyncio.wait_for(
                    ws.receive(), timeout=WS_CONNECT_TIMEOUT
                )

                if msg.type in (
                    aiohttp.WSMsgType.TEXT,
                    aiohttp.WSMsgType.BINARY,
                ):
                    data: dict[str, Any] = json.loads(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    _LOGGER.debug(
                        "FAH client at %s:%s closed WebSocket before sending state",
                        self.host,
                        self.port,
                    )
                    return dict(_UNAVAILABLE)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.warning(
                        "WebSocket error from FAH client at %s:%s: %s",
                        self.host,
                        self.port,
                        ws.exception(),
                    )
                    return dict(_UNAVAILABLE)
                else:
                    _LOGGER.warning(
                        "Unexpected WebSocket message type %s from FAH client at %s:%s",
                        msg.type,
                        self.host,
                        self.port,
                    )
                    return dict(_UNAVAILABLE)
            finally:
                await ws.close()

        except (
            aiohttp.ClientConnectorError,
            ConnectionRefusedError,
            OSError,
            asyncio.TimeoutError,
            TimeoutError,
        ):
            _LOGGER.debug(
                "FAH client at %s:%s is offline",
                self.host,
                self.port,
            )
            return dict(_UNAVAILABLE)

        except (aiohttp.WSServerHandshakeError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "Could not connect to FAH client at %s:%s: %s",
                self.host,
                self.port,
                err,
            )
            return dict(_UNAVAILABLE)

        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.error(
                "Failed to parse FAH state from %s:%s: %s",
                self.host,
                self.port,
                err,
            )
            return dict(_UNAVAILABLE)

        except Exception:
            _LOGGER.error(
                "Unexpected error communicating with FAH client at %s:%s",
                self.host,
                self.port,
                exc_info=True,
            )
            return dict(_UNAVAILABLE)

        try:
            state = self._parse_state(data)
            groups = self._parse_groups(data)
        except Exception:
            _LOGGER.error(
                "Failed to parse FAH state from %s:%s",
                self.host,
                self.port,
                exc_info=True,
            )
            return dict(_UNAVAILABLE)

        units = self._parse_units(data)
        total_ppd = sum(u.get("ppd", 0) for u in units)
        machine_info = self._parse_machine_info(data)
        account = self._parse_account(data)

        return {
            "available": True,
            "state": state,
            "groups": groups,
            "units": units,
            "total_ppd": total_ppd,
            "machine_info": machine_info,
            "account": account,
            "raw": data,
        }

    async def async_send_command(
        self, state: str, group: str | None = None
    ) -> None:
        """Send a state-change command to the FAH client.

        Opens a fresh WebSocket connection, discards the initial state dump,
        sends the command, and closes the connection.  After the command is
        sent successfully the coordinator triggers an immediate data refresh
        so that entities reflect the new state without waiting for the next
        poll cycle.

        Args:
            state: The desired state — one of ``"fold"``, ``"pause"``, or
                ``"finish"``.
            group: Optional resource-group name to target.  When ``None`` the
                command applies to the whole client.

        Raises:
            HomeAssistantError: If the WebSocket connection cannot be
                established or the command cannot be sent.
        """
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(WS_CONNECT_TIMEOUT):
                ws = await session.ws_connect(self.ws_url)
        except (
            aiohttp.ClientConnectorError,
            aiohttp.WSServerHandshakeError,
            aiohttp.ClientError,
            ConnectionRefusedError,
            OSError,
            asyncio.TimeoutError,
            TimeoutError,
        ) as err:
            raise HomeAssistantError(
                f"Could not connect to FAH client at {self.host}:{self.port}"
            ) from err
        except Exception as err:
            raise HomeAssistantError(
                f"Could not connect to FAH client at {self.host}:{self.port}"
            ) from err

        try:
            # Discard the initial state dump that the server sends on connect.
            try:
                await asyncio.wait_for(ws.receive(), timeout=WS_CONNECT_TIMEOUT)
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "Timed out waiting for initial state dump from %s:%s; "
                    "proceeding with command anyway",
                    self.host,
                    self.port,
                )

            # Build the command payload.
            payload: dict[str, str] = {"cmd": "state", "state": state}
            if group is not None:
                payload["group"] = group

            await ws.send_json(payload)
        except Exception as err:
            raise HomeAssistantError(
                f"Could not send command to FAH client at {self.host}:{self.port}"
            ) from err
        finally:
            await ws.close()

        # Trigger an immediate refresh so entities pick up the new state.
        await self.async_request_refresh()

    @staticmethod
    def _parse_state(data: dict[str, Any]) -> str:
        """Derive the overall folding state from a FAH v8 state-dump payload.

        The FAH v8 state dump has **no** top-level ``state`` key.  Instead,
        the folding state is determined from each resource group's config:

        * ``groups[name].config.paused == True``  → group is **paused**
        * ``groups[name].config.finish == True``   → group is **finishing**
        * Both ``False``                           → group is **folding**

        When multiple groups exist the overall state is the "most active":
        folding > finishing > paused.

        As a fallback the method also inspects ``units[].state`` and
        ``units[].paused`` in case the groups structure is absent or empty.

        Args:
            data: The parsed JSON object received from the FAH client.

        Returns:
            One of ``"folding"``, ``"paused"``, or ``"finishing"``.
        """
        # 1. Primary: derive from groups[*].config.paused / .finish
        groups = data.get("groups")
        if isinstance(groups, dict) and groups:
            group_states: list[str] = []
            for group_data in groups.values():
                if not isinstance(group_data, dict):
                    continue
                config = group_data.get("config")
                if not isinstance(config, dict):
                    continue
                paused = config.get("paused", False)
                finish = config.get("finish", False)
                if paused:
                    group_states.append(STATE_PAUSED)
                elif finish:
                    group_states.append(STATE_FINISHING)
                else:
                    group_states.append(STATE_FOLDING)

            if group_states:
                # Most-active wins: folding > finishing > paused
                if STATE_FOLDING in group_states:
                    return STATE_FOLDING
                if STATE_FINISHING in group_states:
                    return STATE_FINISHING
                return STATE_PAUSED

        # 2. Fallback: inspect work-unit entries.
        units = data.get("units")
        if isinstance(units, list) and units:
            has_running = False
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                if unit.get("paused") is True:
                    continue
                if unit.get("state") in ("RUN", "RUNNING", "run", "running"):
                    has_running = True
            if has_running:
                return STATE_FOLDING

        # 3. Cannot determine — safest default.
        return STATE_PAUSED

    @staticmethod
    def _parse_units(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract per-work-unit details from the FAH state dump.

        Each returned dict contains the fields most useful for display:
        ``number``, ``state``, ``progress``, ``eta``, ``ppd``,
        ``run_time``, ``project``, ``credit``, ``cpus``, ``gpus``,
        and ``description`` (a human-readable label like "CPU" or
        "GPU: NVIDIA GeForce RTX 4090").
        """
        raw_units = data.get("units")
        if not isinstance(raw_units, list):
            return []

        # Build a GPU-id → description lookup from info.gpus
        gpu_descriptions: dict[str, str] = {}
        info = data.get("info")
        if isinstance(info, dict):
            info_gpus = info.get("gpus")
            if isinstance(info_gpus, dict):
                for gpu_id, gpu_data in info_gpus.items():
                    if isinstance(gpu_data, dict):
                        gpu_descriptions[gpu_id] = gpu_data.get(
                            "description", gpu_id
                        )

        parsed: list[dict[str, Any]] = []
        for unit in raw_units:
            if not isinstance(unit, dict):
                continue

            # Build a human-friendly description
            unit_gpus = unit.get("gpus", [])
            if isinstance(unit_gpus, list) and unit_gpus:
                gpu_names = [
                    gpu_descriptions.get(g, g)
                    for g in unit_gpus
                    if isinstance(g, str)
                ]
                description = "GPU: " + ", ".join(gpu_names) if gpu_names else "GPU"
            else:
                description = "CPU"

            assignment = unit.get("assignment", {})
            if not isinstance(assignment, dict):
                assignment = {}

            parsed.append(
                {
                    "number": unit.get("number"),
                    "state": unit.get("state"),
                    "paused": unit.get("paused", False),
                    "progress": unit.get("wu_progress", 0.0),
                    "eta": unit.get("eta", ""),
                    "ppd": unit.get("ppd", 0),
                    "run_time": unit.get("run_time", 0),
                    "project": assignment.get("project"),
                    "credit": assignment.get("credit", 0),
                    "cpus": unit.get("cpus", 0),
                    "gpus": unit_gpus if isinstance(unit_gpus, list) else [],
                    "description": description,
                }
            )
        return parsed

    @staticmethod
    def _parse_machine_info(data: dict[str, Any]) -> dict[str, Any]:
        """Extract machine hardware/software info from the state dump."""
        info = data.get("info")
        if not isinstance(info, dict):
            return {}

        # Collect GPU descriptions
        gpu_list: list[str] = []
        info_gpus = info.get("gpus")
        if isinstance(info_gpus, dict):
            for gpu_data in info_gpus.values():
                if isinstance(gpu_data, dict) and gpu_data.get("supported", False):
                    gpu_list.append(gpu_data.get("description", "Unknown GPU"))

        return {
            "version": info.get("version", ""),
            "mach_name": info.get("mach_name", ""),
            "hostname": info.get("hostname", ""),
            "cpu_brand": info.get("cpu_brand", ""),
            "cpus": info.get("cpus", 0),
            "os": info.get("os", ""),
            "os_version": info.get("os_version", ""),
            "gpus": gpu_list,
        }

    @staticmethod
    def _parse_account(data: dict[str, Any]) -> dict[str, Any]:
        """Extract FAH account/team info from the state dump."""
        config = data.get("config")
        if not isinstance(config, dict):
            return {}
        return {
            "user": config.get("user", ""),
            "team": config.get("team", 0),
            "cause": config.get("cause", ""),
        }

    @staticmethod
    def _parse_groups(data: dict[str, Any]) -> list[str]:
        """Extract the list of resource-group names from a FAH state dump.

        The FAH v8 client uses an empty string ``""`` as the name of the
        default resource group.  This method returns all group keys as-is.

        Args:
            data: The parsed JSON object received from the FAH client.

        Returns:
            A list of group-name strings, or an empty list if no groups are
            present.
        """
        groups = data.get("groups")
        if not isinstance(groups, dict):
            return []
        return list(groups.keys())
