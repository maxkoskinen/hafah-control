"""Tests for the Folding@Home Control data-update coordinator.

Covers the ``FahDataUpdateCoordinator`` class including:

* Successful data fetches via WebSocket
* Graceful handling of connection errors (refused, timeout, handshake)
* Malformed / unexpected JSON payloads
* Command sending (``async_send_command``) for fold, pause, finish
* Command sending failure paths (connection errors → ``HomeAssistantError``)
* State-parsing helpers for various FAH v8 state string formats
* Group-list extraction from state dumps
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.fah_control.const import (
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
)
from custom_components.fah_control.coordinator import FahDataUpdateCoordinator

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT, TEST_WS_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    hass: MagicMock,
    entry: MagicMock,
    *,
    mock_refresh: bool = False,
) -> FahDataUpdateCoordinator:
    """Instantiate a coordinator with mocked HA internals.

    Parameters
    ----------
    mock_refresh:
        When ``True``, replace ``async_request_refresh`` with an
        ``AsyncMock`` so that the real HA debounce machinery is bypassed.
        This is required for ``async_send_command`` tests where the
        coordinator calls ``await self.async_request_refresh()`` at the end.
    """
    coordinator = FahDataUpdateCoordinator(hass, entry)
    if mock_refresh:
        coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _make_ws_msg(
    data: str | None = None,
    msg_type: aiohttp.WSMsgType = aiohttp.WSMsgType.TEXT,
) -> MagicMock:
    """Create a mock ``aiohttp.WSMessage``."""
    msg = MagicMock()
    msg.type = msg_type
    msg.data = data
    return msg


def _make_ws(
    receive_side_effect=None,
    receive_return=None,
) -> AsyncMock:
    """Create a mock WebSocket connection.

    Parameters
    ----------
    receive_side_effect:
        If set, ``receive()`` will use this as its side effect (can be a list
        or an exception).
    receive_return:
        If set *and* ``receive_side_effect`` is ``None``, ``receive()`` returns
        this value.
    """
    ws = AsyncMock()
    if receive_side_effect is not None:
        ws.receive = AsyncMock(side_effect=receive_side_effect)
    elif receive_return is not None:
        ws.receive = AsyncMock(return_value=receive_return)
    else:
        msg = _make_ws_msg(json.dumps({
            "groups": {"": {"config": {"paused": False, "finish": False}}},
            "units": [{"group": "", "state": "RUN", "paused": False}],
        }))
        ws.receive = AsyncMock(return_value=msg)
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.exception = MagicMock(return_value=None)
    return ws


def _make_session(ws=None, ws_connect_side_effect=None) -> MagicMock:
    """Create a mock ``aiohttp.ClientSession``."""
    session = MagicMock()
    if ws_connect_side_effect is not None:
        session.ws_connect = AsyncMock(side_effect=ws_connect_side_effect)
    else:
        session.ws_connect = AsyncMock(return_value=ws or _make_ws())
    return session


def _patch_session(session: MagicMock):
    """Return a context-manager that patches ``async_get_clientsession``."""
    return patch(
        "custom_components.fah_control.coordinator.async_get_clientsession",
        return_value=session,
    )


# ===================================================================
# Data fetching — _async_update_data
# ===================================================================


class TestSuccessfulUpdate:
    """Tests for successful WebSocket data retrieval."""

    @pytest.mark.asyncio
    async def test_successful_update_running(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A valid folding state dump yields available=True, state=folding."""
        state_dump = json.dumps({
            "groups": {"": {"config": {"paused": False, "finish": False}}},
            "units": [{"group": "", "state": "RUN", "paused": False}],
        })
        ws = _make_ws(receive_return=_make_ws_msg(state_dump))
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True
        assert data["state"] == STATE_FOLDING
        assert "" in data["groups"]
        assert data["raw"]["groups"][""]["config"]["paused"] is False

    @pytest.mark.asyncio
    async def test_successful_update_paused(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A paused state dump yields state=paused."""
        state_dump = json.dumps({
            "groups": {"": {"config": {"paused": True, "finish": False}}},
            "units": [],
        })
        ws = _make_ws(receive_return=_make_ws_msg(state_dump))
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True
        assert data["state"] == STATE_PAUSED

    @pytest.mark.asyncio
    async def test_successful_update_finishing(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A finishing state dump yields state=finishing."""
        state_dump = json.dumps({
            "groups": {"gpu": {"config": {"paused": False, "finish": True}}},
            "units": [],
        })
        ws = _make_ws(receive_return=_make_ws_msg(state_dump))
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True
        assert data["state"] == STATE_FINISHING
        assert "gpu" in data["groups"]

    @pytest.mark.asyncio
    async def test_successful_update_multiple_groups(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Multiple groups are all returned in the groups list."""
        state_dump = json.dumps({
            "groups": {
                "cpu": {"config": {"paused": False, "finish": False}},
                "gpu-0": {"config": {"paused": True, "finish": False}},
                "gpu-1": {"config": {"paused": False, "finish": True}},
            },
            "units": [],
        })
        ws = _make_ws(receive_return=_make_ws_msg(state_dump))
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True
        assert set(data["groups"]) == {"cpu", "gpu-0", "gpu-1"}
        # If any group is folding the overall state should be folding.
        assert data["state"] == STATE_FOLDING

    @pytest.mark.asyncio
    async def test_ws_closed_after_successful_read(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """The WebSocket is always closed after reading the state dump."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            await coordinator._async_update_data()

        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_binary_message_also_parsed(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A BINARY WebSocket message is parsed as JSON just like TEXT."""
        state_dump = json.dumps({
            "groups": {"": {"config": {"paused": False, "finish": False}}},
        })
        msg = _make_ws_msg(state_dump, aiohttp.WSMsgType.BINARY)
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True


# ===================================================================
# Data fetching — connection failures
# ===================================================================


class TestConnectionErrors:
    """Tests for graceful handling of connection-level errors.

    The coordinator must **never** raise ``UpdateFailed`` for transient
    network problems — it should return the ``_UNAVAILABLE`` sentinel
    instead.
    """

    @pytest.mark.asyncio
    async def test_connection_refused(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """ClientConnectorError → available=False, state=offline."""
        error = aiohttp.ClientConnectorError(
            connection_key=MagicMock(),
            os_error=OSError("Connection refused"),
        )
        session = _make_session(ws_connect_side_effect=error)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE
        assert data["groups"] == []
        assert data["raw"] == {}

    @pytest.mark.asyncio
    async def test_connection_refused_builtin(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Built-in ``ConnectionRefusedError`` is also handled."""
        session = _make_session(ws_connect_side_effect=ConnectionRefusedError())
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE

    @pytest.mark.asyncio
    async def test_timeout(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``asyncio.TimeoutError`` → available=False, state=offline."""
        session = _make_session(ws_connect_side_effect=asyncio.TimeoutError())
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE

    @pytest.mark.asyncio
    async def test_os_error(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Generic ``OSError`` (e.g. network unreachable) → offline."""
        session = _make_session(
            ws_connect_side_effect=OSError("Network is unreachable")
        )
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE

    @pytest.mark.asyncio
    async def test_ws_handshake_error(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``WSServerHandshakeError`` → offline."""
        error = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(),
            history=(),
            status=403,
            message="Forbidden",
            headers=MagicMock(),
        )
        session = _make_session(ws_connect_side_effect=error)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_receive_timeout(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Timeout during ``receive()`` after a successful connect → offline."""
        ws = _make_ws(receive_side_effect=asyncio.TimeoutError())
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE
        # Even on error the WS should be closed.
        ws.close.assert_awaited_once()


# ===================================================================
# Data fetching — malformed / unexpected messages
# ===================================================================


class TestMalformedData:
    """Tests for non-JSON or structurally unexpected WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_malformed_json(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Invalid JSON in the message body → available=False."""
        msg = _make_ws_msg("this is { not valid JSON !!!")
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False
        assert data["state"] == STATE_OFFLINE

    @pytest.mark.asyncio
    async def test_ws_closed_message(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A CLOSED message type before any data → offline."""
        msg = _make_ws_msg(None, aiohttp.WSMsgType.CLOSED)
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_ws_closing_message(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A CLOSING message type before any data → offline."""
        msg = _make_ws_msg(None, aiohttp.WSMsgType.CLOSING)
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_ws_error_message(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """An ERROR message type → offline."""
        msg = _make_ws_msg(None, aiohttp.WSMsgType.ERROR)
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_empty_json_object(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """An empty JSON object ``{}`` → available but falls back to paused."""
        msg = _make_ws_msg("{}")
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        # An empty object is still parseable — available should be True,
        # but the state falls back to "paused" (safest default).
        assert data["available"] is True
        assert data["state"] == STATE_PAUSED
        assert data["groups"] == []

    @pytest.mark.asyncio
    async def test_missing_groups_key(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """State dump with no ``groups`` key → empty group list, falls back to paused."""
        msg = _make_ws_msg(json.dumps({"info": {"version": "8.5.5"}}))
        ws = _make_ws(receive_return=msg)
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            data = await coordinator._async_update_data()

        assert data["available"] is True
        assert data["state"] == STATE_PAUSED
        assert data["groups"] == []


# ===================================================================
# Command sending — async_send_command
# ===================================================================


class TestSendCommand:
    """Tests for ``async_send_command``."""

    @pytest.mark.asyncio
    async def test_send_command_fold(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Sending a 'fold' command transmits the correct JSON payload."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("fold")

        ws.send_json.assert_awaited_once_with({"cmd": "state", "state": "fold"})
        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_command_pause(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Sending a 'pause' command transmits the correct JSON payload."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("pause")

        ws.send_json.assert_awaited_once_with({"cmd": "state", "state": "pause"})

    @pytest.mark.asyncio
    async def test_send_command_finish(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Sending a 'finish' command transmits the correct JSON payload."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("finish")

        ws.send_json.assert_awaited_once_with({"cmd": "state", "state": "finish"})

    @pytest.mark.asyncio
    async def test_send_command_with_group(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """When a group is specified, it appears in the JSON payload."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("fold", group="gpu")

        ws.send_json.assert_awaited_once_with(
            {"cmd": "state", "state": "fold", "group": "gpu"}
        )

    @pytest.mark.asyncio
    async def test_send_command_without_group(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """When no group is given, the ``group`` key is absent from the payload."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("pause")

        payload = ws.send_json.call_args[0][0]
        assert "group" not in payload

    @pytest.mark.asyncio
    async def test_send_command_triggers_refresh(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """After a successful command, ``async_request_refresh`` is called."""
        ws = _make_ws()
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("fold")

        coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_command_discards_initial_state(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """The initial state dump from the server is read (and discarded)
        before the command is sent."""
        state_msg = _make_ws_msg(json.dumps({
            "groups": {"": {"config": {"paused": False, "finish": False}}},
        }))
        closed_msg = _make_ws_msg(None, aiohttp.WSMsgType.CLOSED)
        ws = _make_ws(receive_side_effect=[state_msg, closed_msg])
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry, mock_refresh=True)

        with _patch_session(session):
            await coordinator.async_send_command("fold")

        # receive() should have been called once (to discard the state dump).
        ws.receive.assert_awaited_once()
        # The command should have been sent after the receive.
        ws.send_json.assert_awaited_once()


# ===================================================================
# Command sending — failure paths
# ===================================================================


class TestSendCommandErrors:
    """Tests for error handling during ``async_send_command``."""

    @pytest.mark.asyncio
    async def test_send_command_connection_refused(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``ClientConnectorError`` during connect raises ``HomeAssistantError``."""
        error = aiohttp.ClientConnectorError(
            connection_key=MagicMock(),
            os_error=OSError("Connection refused"),
        )
        session = _make_session(ws_connect_side_effect=error)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            with pytest.raises(HomeAssistantError, match="Could not connect"):
                await coordinator.async_send_command("fold")

    @pytest.mark.asyncio
    async def test_send_command_timeout(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``TimeoutError`` during connect raises ``HomeAssistantError``."""
        session = _make_session(ws_connect_side_effect=asyncio.TimeoutError())
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            with pytest.raises(HomeAssistantError, match="Could not connect"):
                await coordinator.async_send_command("pause")

    @pytest.mark.asyncio
    async def test_send_command_os_error(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``OSError`` during connect raises ``HomeAssistantError``."""
        session = _make_session(
            ws_connect_side_effect=OSError("No route to host")
        )
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            with pytest.raises(HomeAssistantError):
                await coordinator.async_send_command("finish")

    @pytest.mark.asyncio
    async def test_send_command_send_json_error(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Error during ``send_json`` raises ``HomeAssistantError``."""
        ws = _make_ws()
        ws.send_json = AsyncMock(side_effect=ConnectionResetError("Broken pipe"))
        session = _make_session(ws=ws)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            with pytest.raises(HomeAssistantError, match="Could not send command"):
                await coordinator.async_send_command("fold")

        # Even on error the WS should be closed.
        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_command_ws_handshake_error(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``WSServerHandshakeError`` raises ``HomeAssistantError``."""
        error = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(),
            history=(),
            status=403,
            message="Forbidden",
            headers=MagicMock(),
        )
        session = _make_session(ws_connect_side_effect=error)
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with _patch_session(session):
            with pytest.raises(HomeAssistantError):
                await coordinator.async_send_command("fold")


# ===================================================================
# State parsing — _parse_state
# ===================================================================


class TestParseState:
    """Tests for ``FahDataUpdateCoordinator._parse_state`` (static method).

    The FAH v8 API has **no** top-level ``state`` key.  State is derived from
    ``groups[name].config.paused`` (bool) and ``groups[name].config.finish``
    (bool).  Multiple groups are aggregated: folding > finishing > paused.
    As a fallback, ``units[*].state`` / ``units[*].paused`` are inspected.
    """

    def test_folding_when_not_paused_not_finish(self) -> None:
        """paused=False, finish=False → folding."""
        data: dict[str, Any] = {
            "groups": {"": {"config": {"paused": False, "finish": False}}},
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_FOLDING

    def test_paused_when_paused_true(self) -> None:
        """paused=True → paused."""
        data: dict[str, Any] = {
            "groups": {"": {"config": {"paused": True, "finish": False}}},
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_PAUSED

    def test_finishing_when_finish_true(self) -> None:
        """finish=True (and paused=False) → finishing."""
        data: dict[str, Any] = {
            "groups": {"": {"config": {"paused": False, "finish": True}}},
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_FINISHING

    def test_multiple_groups_folding_wins(self) -> None:
        """If any group is folding, the overall state is folding."""
        data: dict[str, Any] = {
            "groups": {
                "": {"config": {"paused": False, "finish": False}},
                "gpu": {"config": {"paused": True, "finish": False}},
            },
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_FOLDING

    def test_multiple_groups_finishing_over_paused(self) -> None:
        """Finishing takes precedence over paused when no group is folding."""
        data: dict[str, Any] = {
            "groups": {
                "": {"config": {"paused": True, "finish": False}},
                "gpu": {"config": {"paused": False, "finish": True}},
            },
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_FINISHING

    def test_multiple_groups_all_paused(self) -> None:
        """All groups paused → overall state is paused."""
        data: dict[str, Any] = {
            "groups": {
                "": {"config": {"paused": True, "finish": False}},
                "gpu": {"config": {"paused": True, "finish": False}},
            },
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_PAUSED

    def test_fallback_to_units_running(self) -> None:
        """No groups, but units with state=RUN and paused=False → folding."""
        data: dict[str, Any] = {
            "units": [{"state": "RUN", "paused": False}],
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_FOLDING

    def test_fallback_units_all_paused(self) -> None:
        """No groups, all units paused → paused (default)."""
        data: dict[str, Any] = {
            "units": [{"state": "RUN", "paused": True}],
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_PAUSED

    def test_no_groups_no_units(self) -> None:
        """Empty data → paused (default)."""
        assert FahDataUpdateCoordinator._parse_state({}) == STATE_PAUSED

    def test_group_missing_config(self) -> None:
        """Group present but no config key → falls through to default."""
        data: dict[str, Any] = {
            "groups": {"": {"some_other_key": 123}},
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_PAUSED

    def test_group_config_not_dict(self) -> None:
        """Group config is not a dict → falls through to default."""
        data: dict[str, Any] = {
            "groups": {"": {"config": "not a dict"}},
        }
        assert FahDataUpdateCoordinator._parse_state(data) == STATE_PAUSED


# ===================================================================
# Group parsing — _parse_groups
# ===================================================================


class TestParseGroups:
    """Tests for ``FahDataUpdateCoordinator._parse_groups`` (static method)."""

    def test_single_group(self) -> None:
        data: dict[str, Any] = {
            "groups": {"": {"config": {"paused": False, "finish": False}}},
        }
        assert FahDataUpdateCoordinator._parse_groups(data) == [""]

    def test_multiple_groups(self) -> None:
        data: dict[str, Any] = {
            "groups": {
                "": {"config": {"paused": False, "finish": False}},
                "gpu": {"config": {"paused": False, "finish": False}},
            }
        }
        result = FahDataUpdateCoordinator._parse_groups(data)
        assert set(result) == {"", "gpu"}

    def test_no_groups_key(self) -> None:
        assert FahDataUpdateCoordinator._parse_groups({}) == []

    def test_groups_is_none(self) -> None:
        assert FahDataUpdateCoordinator._parse_groups({"groups": None}) == []

    def test_groups_is_not_dict(self) -> None:
        assert FahDataUpdateCoordinator._parse_groups({"groups": [1, 2]}) == []

    def test_empty_groups_dict(self) -> None:
        assert FahDataUpdateCoordinator._parse_groups({"groups": {}}) == []


# ===================================================================
# Coordinator properties
# ===================================================================


class TestCoordinatorProperties:
    """Tests for coordinator attribute initialization."""

    def test_host_port_name(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """The coordinator stores host, port, and fah_name from the entry."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        assert coordinator.host == TEST_HOST
        assert coordinator.port == TEST_PORT
        assert coordinator.fah_name == TEST_NAME

    def test_ws_url(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``ws_url`` builds the correct WebSocket URL."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.ws_url == TEST_WS_URL

    def test_default_poll_interval(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """When options are empty the default poll interval is used."""
        mock_config_entry.options = {}
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)

    def test_custom_poll_interval(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """A custom poll interval from options overrides the default."""
        mock_config_entry.options = {CONF_POLL_INTERVAL: 30}
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.update_interval == timedelta(seconds=30)

    def test_coordinator_name(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """The DataUpdateCoordinator name follows the expected pattern."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.name == f"{DOMAIN}_{TEST_HOST}_{TEST_PORT}"