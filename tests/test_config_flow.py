"""Tests for the Folding@Home Control config flow.

Covers the user-facing configuration dialog (``async_step_user``) including
successful connections, connection failures, timeouts, duplicate detection,
and the options flow for adjusting the poll interval.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import aiohttp
import pytest

from homeassistant.data_entry_flow import AbortFlow

from custom_components.fah_control.config_flow import (
    FahControlConfigFlow,
    FahOptionsFlowHandler,
)
from custom_components.fah_control.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
)

# Re-use shared constants from conftest
from .conftest import TEST_HOST, TEST_NAME, TEST_PORT, TEST_UNIQUE_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_INPUT = {
    CONF_HOST: TEST_HOST,
    CONF_PORT: TEST_PORT,
    CONF_NAME: TEST_NAME,
}


def _build_flow(hass: MagicMock) -> FahControlConfigFlow:
    """Instantiate a ``FahControlConfigFlow`` bound to a mock hass.

    The mock hass is wired up so that the real ``_abort_if_unique_id_configured``
    and ``async_set_unique_id`` methods work correctly:

    * ``hass.config_entries.async_entry_for_domain_unique_id`` returns ``None``
      (no duplicate) by default.  Tests that need the "already configured"
      behaviour can override this on the returned hass mock.
    """
    flow = FahControlConfigFlow()
    flow.hass = hass

    # async_set_unique_id is a real coroutine on the base FlowHandler.
    # It ultimately sets self.unique_id and (in newer HA) may also check
    # the registry.  We provide a minimal async stub.
    _original_set_unique_id = flow.async_set_unique_id

    # _abort_if_unique_id_configured inspects
    # hass.config_entries.async_entry_for_domain_unique_id(handler, uid)
    # — make it return None (no existing entry) by default.
    hass.config_entries.async_entry_for_domain_unique_id = MagicMock(
        return_value=None
    )

    flow.context = {"source": "user"}
    return flow


def _make_ws_connection(receive_side_effect=None) -> AsyncMock:
    """Create a mock WebSocket connection object.

    Parameters
    ----------
    receive_side_effect:
        An optional side effect for the ``receive()`` coroutine.  When
        ``None``, ``receive()`` returns a simple TEXT message.
    """
    ws = AsyncMock()
    if receive_side_effect is not None:
        ws.receive = AsyncMock(side_effect=receive_side_effect)
    else:
        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.TEXT
        msg.data = '{"state": "RUNNING"}'
        ws.receive = AsyncMock(return_value=msg)
    ws.close = AsyncMock()
    return ws


def _make_session(ws_connect_side_effect=None, ws_connection=None) -> MagicMock:
    """Create a mock ``aiohttp.ClientSession``.

    Parameters
    ----------
    ws_connect_side_effect:
        When set, ``ws_connect`` will raise this instead of returning a
        connection.
    ws_connection:
        The mock WebSocket connection to return.  Defaults to a fresh one
        built by ``_make_ws_connection()``.
    """
    session = MagicMock()
    if ws_connect_side_effect is not None:
        session.ws_connect = AsyncMock(side_effect=ws_connect_side_effect)
    else:
        session.ws_connect = AsyncMock(
            return_value=ws_connection or _make_ws_connection()
        )
    return session


# ---------------------------------------------------------------------------
# Tests — async_step_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_step_success(mock_hass: MagicMock) -> None:
    """A valid host/port that connects successfully creates a config entry."""
    session = _make_session()
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    # The flow should create an entry (not show the form again).
    assert result["type"].value == "create_entry"
    assert result["title"] == TEST_NAME
    assert result["data"][CONF_HOST] == TEST_HOST
    assert result["data"][CONF_PORT] == TEST_PORT
    assert result["data"][CONF_NAME] == TEST_NAME

    # Verify the WebSocket was actually contacted.
    session.ws_connect.assert_awaited_once()
    url_arg = session.ws_connect.call_args[0][0]
    assert TEST_HOST in url_arg
    assert str(TEST_PORT) in url_arg


@pytest.mark.asyncio
async def test_user_step_cannot_connect(mock_hass: MagicMock) -> None:
    """When the WS connection is refused, the form is shown with an error."""
    error = aiohttp.ClientConnectorError(
        connection_key=MagicMock(), os_error=OSError("Connection refused")
    )
    session = _make_session(ws_connect_side_effect=error)
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"].value == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_user_step_connection_refused_os_error(mock_hass: MagicMock) -> None:
    """An ``OSError`` during connection is treated the same as a refused conn."""
    session = _make_session(ws_connect_side_effect=OSError("Network is unreachable"))
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"].value == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_user_step_timeout(mock_hass: MagicMock) -> None:
    """A connection timeout results in a ``cannot_connect`` error."""
    session = _make_session(ws_connect_side_effect=asyncio.TimeoutError())
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"].value == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_user_step_receive_timeout(mock_hass: MagicMock) -> None:
    """Timeout during ``receive()`` (after connect) is also cannot_connect."""
    ws = _make_ws_connection(receive_side_effect=asyncio.TimeoutError())
    session = _make_session(ws_connection=ws)
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    # The _test_connection wraps everything in asyncio.timeout, so this
    # should still surface as cannot_connect.
    assert result["type"].value == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_user_step_shows_form_when_no_input(mock_hass: MagicMock) -> None:
    """When called with no user input, the form is presented."""
    flow = _build_flow(mock_hass)

    result = await flow.async_step_user(user_input=None)

    assert result["type"].value == "form"
    assert result["step_id"] == "user"
    assert result.get("errors") == {}


# ---------------------------------------------------------------------------
# Tests — duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_configured(mock_hass: MagicMock) -> None:
    """Adding a client with the same host:port aborts with already_configured."""
    session = _make_session()
    flow = _build_flow(mock_hass)

    # Simulate an existing entry with the same unique_id.
    # _abort_if_unique_id_configured calls
    #   hass.config_entries.async_entry_for_domain_unique_id(handler, uid)
    # and aborts if it returns a non-None entry.
    existing_entry = MagicMock()
    existing_entry.data = {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    mock_hass.config_entries.async_entry_for_domain_unique_id = MagicMock(
        return_value=existing_entry
    )
    # async_update_entry is also called inside _abort_if_unique_id_configured
    # when updates is not None, but we pass None so just ensure it exists.
    mock_hass.config_entries.async_update_entry = MagicMock(return_value=False)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ), pytest.raises(AbortFlow) as exc_info:
        await flow.async_step_user(user_input=USER_INPUT)

    assert exc_info.value.reason == "already_configured"


# ---------------------------------------------------------------------------
# Tests — options flow
# ---------------------------------------------------------------------------


def _build_options_handler(options: dict | None = None) -> FahOptionsFlowHandler:
    """Build an ``FahOptionsFlowHandler`` that works with newer HA versions.

    In Home Assistant >= 2024.x the ``OptionsFlow.config_entry`` attribute is
    a read-only property managed by the framework.  The property reads from
    ``self.hass.config_entries.async_get_known_entry(self.handler)`` so we
    set up a mock ``hass`` and ``handler`` on the instance to satisfy it.
    """
    mock_entry = MagicMock()
    mock_entry.options = options or {}
    mock_entry.entry_id = "test_entry_id"

    # FahOptionsFlowHandler.__init__ tries ``self.config_entry = config_entry``
    # which fails when the base class defines it as a read-only property.
    # Bypass __init__ entirely and wire up the attributes manually.
    handler = FahOptionsFlowHandler.__new__(FahOptionsFlowHandler)

    # The config_entry property requires:
    #   self.hass  (must not be None)
    #   self.handler  (returned by _config_entry_id)
    #   self.hass.config_entries.async_get_known_entry(handler) → entry
    mock_hass = MagicMock()
    mock_hass.config_entries.async_get_known_entry = MagicMock(
        return_value=mock_entry
    )
    handler.hass = mock_hass
    handler.handler = mock_entry.entry_id

    # FlowHandler methods (async_show_form, async_create_entry) reference
    # flow_id and context, so provide sensible defaults.
    handler.flow_id = "test_options_flow_id"
    handler.context = {}

    return handler


@pytest.mark.asyncio
async def test_options_flow_shows_form() -> None:
    """The options flow shows a form with the current poll_interval."""
    handler = _build_options_handler()

    result = await handler.async_step_init(user_input=None)

    assert result["type"].value == "form"
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_saves_poll_interval() -> None:
    """Submitting the options form persists the new poll interval."""
    handler = _build_options_handler(
        options={CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL}
    )

    new_interval = 120
    result = await handler.async_step_init(
        user_input={CONF_POLL_INTERVAL: new_interval}
    )

    assert result["type"].value == "create_entry"
    assert result["data"][CONF_POLL_INTERVAL] == new_interval


@pytest.mark.asyncio
async def test_options_flow_default_value() -> None:
    """When no options have been set yet, the default poll interval is used."""
    handler = _build_options_handler(options={})

    result = await handler.async_step_init(user_input=None)

    # The schema should contain the default poll interval.
    assert result["type"].value == "form"
    # Inspect the schema to verify the default was applied.
    schema = result["data_schema"]
    for key in schema.schema:
        if hasattr(key, "default") and str(key) == CONF_POLL_INTERVAL:
            assert key.default() == DEFAULT_POLL_INTERVAL


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_step_with_default_port(mock_hass: MagicMock) -> None:
    """When the user omits the port, the default (7396) is used."""
    session = _make_session()
    flow = _build_flow(mock_hass)

    user_input = {
        CONF_HOST: TEST_HOST,
        CONF_PORT: DEFAULT_PORT,
        CONF_NAME: DEFAULT_NAME,
    }

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=user_input)

    assert result["type"].value == "create_entry"
    assert result["data"][CONF_PORT] == DEFAULT_PORT
    assert result["data"][CONF_NAME] == DEFAULT_NAME


@pytest.mark.asyncio
async def test_user_step_ws_close_is_called_on_success(
    mock_hass: MagicMock,
) -> None:
    """Verify the WebSocket is properly closed after a successful test."""
    ws = _make_ws_connection()
    session = _make_session(ws_connection=ws)
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        await flow.async_step_user(user_input=USER_INPUT)

    ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_step_unique_id_is_set(mock_hass: MagicMock) -> None:
    """After a successful connection, the flow's unique_id is ``host:port``."""
    session = _make_session()
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        await flow.async_step_user(user_input=USER_INPUT)

    assert flow.unique_id == TEST_UNIQUE_ID


@pytest.mark.asyncio
async def test_user_step_entry_data_complete(mock_hass: MagicMock) -> None:
    """The created entry contains all three required data keys."""
    session = _make_session()
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    data = result["data"]
    assert set(data.keys()) == {CONF_HOST, CONF_PORT, CONF_NAME}


@pytest.mark.asyncio
async def test_user_step_connection_refused_builtin(mock_hass: MagicMock) -> None:
    """A bare ``ConnectionRefusedError`` also yields cannot_connect."""
    session = _make_session(ws_connect_side_effect=ConnectionRefusedError())
    flow = _build_flow(mock_hass)

    with patch(
        "custom_components.fah_control.config_flow.async_get_clientsession",
        return_value=session,
    ):
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"].value == "form"
    assert result["errors"] == {"base": "cannot_connect"}