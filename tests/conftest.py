"""Shared fixtures for Folding@Home Control integration tests.

Provides reusable mock objects and sample data that mirror a real FAH v8
client's WebSocket responses.  Every fixture is designed to be lightweight
and independent of a full Home Assistant test harness so that the suite can
run quickly in CI.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant


# ---------------------------------------------------------------------------
# Constants used across test modules
# ---------------------------------------------------------------------------

TEST_HOST = "192.168.1.100"
TEST_PORT = 7396
TEST_NAME = "Test FAH"
TEST_UNIQUE_ID = f"{TEST_HOST}:{TEST_PORT}"
TEST_WS_URL = f"ws://{TEST_HOST}:{TEST_PORT}/api/websocket"


# ---------------------------------------------------------------------------
# Mock Home Assistant
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a lightweight mock of the HomeAssistant core object.

    The mock is configured with the minimum attributes that the coordinator
    and entity code touches during unit tests.  For integration tests that
    exercise the full HA machinery you would use the ``hass`` fixture from
    ``pytest-homeassistant-custom-component`` instead.
    """
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.loop = AsyncMock()
    hass.config_entries = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    return hass


# ---------------------------------------------------------------------------
# Mock ConfigEntry
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Return a mock ``ConfigEntry`` with typical FAH connection data.

    The entry mirrors what the config flow would create for a client at
    ``192.168.1.100:7396`` named *Test FAH*.
    """
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.domain = "fah_control"
    entry.title = TEST_NAME
    entry.unique_id = TEST_UNIQUE_ID
    entry.data = {
        "host": TEST_HOST,
        "port": TEST_PORT,
        "name": TEST_NAME,
    }
    entry.options = {}
    entry.runtime_data = None
    # add_update_listener returns a callable that removes the listener.
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    entry.async_on_unload = MagicMock()
    return entry


# ---------------------------------------------------------------------------
# Coordinator data payloads
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_coordinator_data() -> dict[str, Any]:
    """Return a sample *successful* coordinator data dict.

    Represents a FAH client that is actively folding with a single
    default (empty-string) resource group.
    """
    return {
        "available": True,
        "state": "folding",
        "groups": [""],
        "units": [
            {
                "number": 1,
                "state": "RUN",
                "paused": False,
                "progress": 0.5,
                "eta": "30m",
                "ppd": 250000,
                "run_time": 3600,
                "project": 18490,
                "credit": 19948,
                "cpus": 27,
                "gpus": [],
                "description": "CPU",
            },
        ],
        "total_ppd": 250000,
        "machine_info": {
            "version": "8.5.5",
            "cpu_brand": "Test CPU",
            "cpus": 32,
            "os": "linux",
            "os_version": "6.17",
            "mach_name": "test-fah",
            "hostname": "test-fah",
            "gpus": [],
        },
        "account": {"user": "testuser", "team": 0, "cause": "any"},
        "raw": {
            "groups": {
                "": {
                    "config": {
                        "on_idle": False,
                        "paused": False,
                        "finish": False,
                        "cpus": 28,
                        "gpus": {"gpu:01:00:00": {"enabled": True}},
                    },
                },
            },
            "units": [
                {
                    "group": "",
                    "number": 184,
                    "state": "RUN",
                    "paused": False,
                    "cpus": 27,
                    "gpus": [],
                },
            ],
        },
    }


@pytest.fixture
def mock_coordinator_data_paused() -> dict[str, Any]:
    """Return coordinator data for a *paused* FAH client."""
    return {
        "available": True,
        "state": "paused",
        "groups": [""],
        "units": [
            {
                "number": 1,
                "state": "RUN",
                "paused": True,
                "progress": 0.5,
                "eta": "30m",
                "ppd": 0,
                "run_time": 3600,
                "project": 18490,
                "credit": 19948,
                "cpus": 27,
                "gpus": [],
                "description": "CPU",
            },
        ],
        "total_ppd": 0,
        "machine_info": {
            "version": "8.5.5",
            "cpu_brand": "Test CPU",
            "cpus": 32,
            "os": "linux",
            "os_version": "6.17",
            "mach_name": "test-fah",
            "hostname": "test-fah",
            "gpus": [],
        },
        "account": {"user": "testuser", "team": 0, "cause": "any"},
        "raw": {
            "groups": {
                "": {
                    "config": {
                        "on_idle": False,
                        "paused": True,
                        "finish": False,
                        "cpus": 28,
                        "gpus": {"gpu:01:00:00": {"enabled": True}},
                    },
                },
            },
            "units": [],
        },
    }


@pytest.fixture
def mock_coordinator_data_offline() -> dict[str, Any]:
    """Return coordinator data for an *offline / unreachable* FAH client."""
    return {
        "available": False,
        "state": "offline",
        "groups": [],
        "units": [],
        "total_ppd": 0,
        "machine_info": {},
        "account": {},
        "raw": {},
    }


# ---------------------------------------------------------------------------
# FAH v8 WebSocket message helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_fah_state_dump() -> str:
    """Return a sample FAH v8 state-dump JSON string.

    This is the raw text payload that the FAH client sends over WebSocket
    immediately after a connection is established.  Matches the real FAH v8
    API structure (no top-level ``state`` key).
    """
    return json.dumps(
        {
            "info": {"version": "8.5.5", "mach_name": "test-host", "hostname": "test-host"},
            "config": {"user": "testuser", "team": 0},
            "groups": {
                "": {
                    "config": {
                        "on_idle": False,
                        "paused": False,
                        "finish": False,
                        "cpus": 28,
                        "gpus": {"gpu:01:00:00": {"enabled": True}},
                    },
                },
            },
            "units": [
                {
                    "group": "",
                    "number": 184,
                    "state": "RUN",
                    "paused": False,
                    "cpus": 27,
                    "gpus": [],
                },
            ],
        }
    )


@pytest.fixture
def mock_fah_state_dump_paused() -> str:
    """Return a FAH v8 state-dump JSON string for a paused client."""
    return json.dumps(
        {
            "info": {"version": "8.5.5", "mach_name": "test-host", "hostname": "test-host"},
            "config": {"user": "testuser", "team": 0},
            "groups": {
                "": {
                    "config": {
                        "on_idle": False,
                        "paused": True,
                        "finish": False,
                        "cpus": 28,
                        "gpus": {"gpu:01:00:00": {"enabled": True}},
                    },
                },
            },
            "units": [],
        }
    )


@pytest.fixture
def mock_ws_message():
    """Return a factory that creates mock ``aiohttp.WSMessage`` objects.

    Usage::

        msg = mock_ws_message('{"state": "RUNNING"}')
        msg = mock_ws_message('bad json', msg_type=aiohttp.WSMsgType.TEXT)
        msg = mock_ws_message(None, msg_type=aiohttp.WSMsgType.CLOSED)

    The returned object quacks like ``aiohttp.WSMessage`` with ``.type``
    and ``.data`` attributes.
    """
    import aiohttp

    def _factory(
        data: str | None = None,
        msg_type: aiohttp.WSMsgType = aiohttp.WSMsgType.TEXT,
    ) -> MagicMock:
        msg = MagicMock()
        msg.type = msg_type
        msg.data = data
        return msg

    return _factory


# ---------------------------------------------------------------------------
# Mock aiohttp WebSocket connection
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ws_connection(mock_fah_state_dump: str, mock_ws_message):
    """Return a mock WebSocket connection that behaves like a FAH client.

    By default the connection:
    * Returns a TEXT message containing the running state dump on ``receive()``.
    * Accepts ``send_json()`` without error.
    * Has a no-op ``close()`` coroutine.

    Tests can customise ``receive`` side effects to simulate errors.
    """
    ws = AsyncMock()

    # First call to receive() returns the state dump, subsequent calls
    # return a CLOSED message.
    import aiohttp

    state_msg = mock_ws_message(mock_fah_state_dump)
    closed_msg = mock_ws_message(None, aiohttp.WSMsgType.CLOSED)
    ws.receive = AsyncMock(side_effect=[state_msg, closed_msg])
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.exception = MagicMock(return_value=None)

    return ws


@pytest.fixture
def mock_session(mock_ws_connection):
    """Return a mock ``aiohttp.ClientSession`` that yields *mock_ws_connection*.

    The session's ``ws_connect`` is an async function that returns the mock
    WebSocket connection directly (matching ``aiohttp``'s real API where
    ``ws_connect`` is an awaitable that resolves to a ``ClientWebSocketResponse``).
    """
    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=mock_ws_connection)
    return session


# ---------------------------------------------------------------------------
# Convenience: patch ``async_get_clientsession`` globally
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_clientsession(mock_session):
    """Patch ``homeassistant.helpers.aiohttp_client.async_get_clientsession``.

    Returns the mock session so tests can inspect call history.
    """
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        return_value=mock_session,
    ):
        yield mock_session