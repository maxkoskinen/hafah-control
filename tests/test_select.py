"""Tests for the Folding@Home Control select entity.

Covers the ``FahControlSelect`` entity including:

* ``current_option`` reflects the coordinator's folding state via STATE_TO_SELECT
* ``available`` tracks the coordinator's ``available`` flag
* ``async_select_option`` dispatches the selected command via the coordinator
* ``unique_id``, ``name``, ``icon``, ``options``, and ``device_info`` are correct
* Dynamic state transitions when coordinator data changes
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fah_control.const import (
    DOMAIN,
    SELECT_OPTIONS,
    STATE_FINISHING,
    STATE_FOLDING,
    STATE_OFFLINE,
    STATE_PAUSED,
)
from custom_components.fah_control.select import FahControlSelect

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    data: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock ``FahDataUpdateCoordinator`` with the given data.

    The mock exposes the minimum surface area that ``FahControlSelect``
    depends on:  ``.data``, ``.host``, ``.port``, ``.name``,
    ``.fah_name``, and ``.async_send_command()``.
    """
    coordinator = MagicMock()
    coordinator.host = TEST_HOST
    coordinator.port = TEST_PORT
    coordinator.name = f"fah_control_{TEST_HOST}_{TEST_PORT}"
    coordinator.fah_name = TEST_NAME
    coordinator.data = data
    coordinator.async_send_command = AsyncMock()
    # CoordinatorEntity expects these on the coordinator:
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    return coordinator


def _make_select(
    coordinator_data: dict[str, Any] | None = None,
) -> tuple[FahControlSelect, MagicMock]:
    """Instantiate a ``FahControlSelect`` backed by a mock coordinator.

    Returns both the select entity and the underlying mock coordinator so
    tests can inspect call history.
    """
    coordinator = _make_coordinator(coordinator_data)
    select = FahControlSelect(coordinator)
    return select, coordinator


# ---------------------------------------------------------------------------
# Default coordinator data payloads
# ---------------------------------------------------------------------------

FOLDING_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_FOLDING,
    "groups": [""],
    "units": [
        {
            "number": 1,
            "state": "RUN",
            "ppd": 250000,
            "progress": 0.5,
            "eta": "30m",
            "run_time": 3600,
            "project": 18490,
            "credit": 19948,
            "cpus": 27,
            "gpus": [],
            "description": "CPU",
            "paused": False,
        },
    ],
    "total_ppd": 250000,
    "machine_info": {
        "version": "8.5.5",
        "cpu_brand": "Test CPU",
        "cpus": 32,
        "os": "linux",
        "os_version": "6.17",
        "mach_name": "test",
        "hostname": "test",
        "gpus": [],
    },
    "account": {"user": "testuser", "team": 0, "cause": "any"},
    "raw": {},
}

PAUSED_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_PAUSED,
    "groups": [""],
    "units": [
        {
            "number": 1,
            "state": "RUN",
            "ppd": 0,
            "progress": 0.5,
            "eta": "30m",
            "run_time": 3600,
            "project": 18490,
            "credit": 19948,
            "cpus": 27,
            "gpus": [],
            "description": "CPU",
            "paused": True,
        },
    ],
    "total_ppd": 0,
    "machine_info": {
        "version": "8.5.5",
        "cpu_brand": "Test CPU",
        "cpus": 32,
        "os": "linux",
        "os_version": "6.17",
        "mach_name": "test",
        "hostname": "test",
        "gpus": [],
    },
    "account": {"user": "testuser", "team": 0, "cause": "any"},
    "raw": {},
}

FINISHING_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_FINISHING,
    "groups": [""],
    "units": [
        {
            "number": 1,
            "state": "RUN",
            "ppd": 250000,
            "progress": 0.8,
            "eta": "10m",
            "run_time": 5400,
            "project": 18490,
            "credit": 19948,
            "cpus": 27,
            "gpus": [],
            "description": "CPU",
            "paused": False,
        },
    ],
    "total_ppd": 250000,
    "machine_info": {
        "version": "8.5.5",
        "cpu_brand": "Test CPU",
        "cpus": 32,
        "os": "linux",
        "os_version": "6.17",
        "mach_name": "test",
        "hostname": "test",
        "gpus": [],
    },
    "account": {"user": "testuser", "team": 0, "cause": "any"},
    "raw": {},
}

OFFLINE_DATA: dict[str, Any] = {
    "available": False,
    "state": STATE_OFFLINE,
    "groups": [],
    "units": [],
    "total_ppd": 0,
    "machine_info": {},
    "account": {},
    "raw": {},
}


# ===================================================================
# current_option property
# ===================================================================


class TestCurrentOption:
    """Verify that ``current_option`` correctly reflects the folding state."""

    def test_current_option_when_folding(self) -> None:
        """Select shows ``fold`` when the FAH client is actively folding."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.current_option == "fold"

    def test_current_option_when_paused(self) -> None:
        """Select shows ``pause`` when the FAH client is paused."""
        select, _ = _make_select(PAUSED_DATA)
        assert select.current_option == "pause"

    def test_current_option_when_finishing(self) -> None:
        """Select shows ``finish`` when the FAH client is finishing."""
        select, _ = _make_select(FINISHING_DATA)
        assert select.current_option == "finish"

    def test_current_option_when_offline(self) -> None:
        """Select shows ``None`` when state is ``offline`` (not in STATE_TO_SELECT)."""
        select, _ = _make_select(OFFLINE_DATA)
        assert select.current_option is None

    def test_current_option_when_no_data(self) -> None:
        """Select shows ``None`` when coordinator.data is ``None``."""
        select, _ = _make_select(None)
        assert select.current_option is None


# ===================================================================
# available property
# ===================================================================


class TestAvailable:
    """Verify that ``available`` tracks the coordinator's availability flag."""

    def test_available_when_folding(self) -> None:
        """Entity is available when the FAH client is reachable and folding."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.available is True

    def test_available_when_paused(self) -> None:
        """Entity is available when the FAH client is reachable and paused."""
        select, _ = _make_select(PAUSED_DATA)
        assert select.available is True

    def test_unavailable_when_offline(self) -> None:
        """Entity is unavailable when the FAH client cannot be reached."""
        select, _ = _make_select(OFFLINE_DATA)
        assert select.available is False

    def test_unavailable_when_no_data(self) -> None:
        """Entity is unavailable before the coordinator has any data."""
        select, _ = _make_select(None)
        assert select.available is False

    def test_unavailable_when_available_key_missing(self) -> None:
        """Entity is unavailable when the ``available`` key is absent."""
        select, _ = _make_select({"state": STATE_FOLDING, "groups": []})
        assert select.available is False


# ===================================================================
# async_select_option
# ===================================================================


class TestSelectOption:
    """Verify that selecting an option dispatches the correct coordinator command."""

    @pytest.mark.asyncio
    async def test_select_fold(self) -> None:
        """Selecting ``fold`` sends a ``fold`` command to the coordinator."""
        select, coordinator = _make_select(PAUSED_DATA)

        await select.async_select_option("fold")

        coordinator.async_send_command.assert_awaited_once_with("fold")

    @pytest.mark.asyncio
    async def test_select_pause(self) -> None:
        """Selecting ``pause`` sends a ``pause`` command to the coordinator."""
        select, coordinator = _make_select(FOLDING_DATA)

        await select.async_select_option("pause")

        coordinator.async_send_command.assert_awaited_once_with("pause")

    @pytest.mark.asyncio
    async def test_select_finish(self) -> None:
        """Selecting ``finish`` sends a ``finish`` command to the coordinator."""
        select, coordinator = _make_select(FOLDING_DATA)

        await select.async_select_option("finish")

        coordinator.async_send_command.assert_awaited_once_with("finish")


# ===================================================================
# Entity metadata
# ===================================================================


class TestEntityMetadata:
    """Verify unique_id, name, icon, options, and device_info are set correctly."""

    def test_unique_id(self) -> None:
        """``unique_id`` follows the ``{host}_{port}_control`` pattern."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.unique_id == f"{TEST_HOST}_{TEST_PORT}_control"

    def test_name(self) -> None:
        """The entity name is ``Control``."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.name == "Control"

    def test_has_entity_name(self) -> None:
        """``has_entity_name`` is True so HA prepends the device name."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.has_entity_name is True

    def test_icon(self) -> None:
        """The icon is the protein MDI icon."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.icon == "mdi:protein"

    def test_options(self) -> None:
        """The options list contains fold, pause, and finish."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.options == ["fold", "pause", "finish"]

    def test_options_matches_const(self) -> None:
        """The options list matches ``SELECT_OPTIONS`` from const.py."""
        select, _ = _make_select(FOLDING_DATA)
        assert select.options == SELECT_OPTIONS

    def test_device_info_identifiers(self) -> None:
        """Device identifiers use ``(DOMAIN, host:port)``."""
        select, _ = _make_select(FOLDING_DATA)
        info = select.device_info
        assert info is not None
        assert (DOMAIN, f"{TEST_HOST}:{TEST_PORT}") in info["identifiers"]

    def test_device_info_manufacturer(self) -> None:
        """The manufacturer is the Folding@Home Consortium."""
        select, _ = _make_select(FOLDING_DATA)
        info = select.device_info
        assert info is not None
        assert info["manufacturer"] == "Folding@Home Consortium"

    def test_device_info_model(self) -> None:
        """The model reflects the FAH v8 client."""
        select, _ = _make_select(FOLDING_DATA)
        info = select.device_info
        assert info is not None
        assert "v8" in info["model"]


# ===================================================================
# State transitions (data changes on the coordinator)
# ===================================================================


class TestStateTransitions:
    """Verify that the select reflects coordinator data changes dynamically."""

    def test_transition_folding_to_paused(self) -> None:
        """When coordinator data switches from folding to paused, option changes."""
        select, coordinator = _make_select(FOLDING_DATA)
        assert select.current_option == "fold"

        coordinator.data = PAUSED_DATA
        assert select.current_option == "pause"

    def test_transition_paused_to_folding(self) -> None:
        """When coordinator data switches from paused to folding, option changes."""
        select, coordinator = _make_select(PAUSED_DATA)
        assert select.current_option == "pause"

        coordinator.data = FOLDING_DATA
        assert select.current_option == "fold"

    def test_transition_folding_to_finishing(self) -> None:
        """When coordinator data switches from folding to finishing, option changes."""
        select, coordinator = _make_select(FOLDING_DATA)
        assert select.current_option == "fold"

        coordinator.data = FINISHING_DATA
        assert select.current_option == "finish"

    def test_transition_folding_to_offline(self) -> None:
        """When the client goes offline, the entity becomes unavailable."""
        select, coordinator = _make_select(FOLDING_DATA)
        assert select.available is True
        assert select.current_option == "fold"

        coordinator.data = OFFLINE_DATA
        assert select.available is False
        assert select.current_option is None

    def test_transition_offline_to_folding(self) -> None:
        """When the client comes back online, the entity becomes available."""
        select, coordinator = _make_select(OFFLINE_DATA)
        assert select.available is False

        coordinator.data = FOLDING_DATA
        assert select.available is True
        assert select.current_option == "fold"

    def test_transition_to_none_data(self) -> None:
        """If coordinator data becomes None, entity goes unavailable."""
        select, coordinator = _make_select(FOLDING_DATA)
        assert select.available is True

        coordinator.data = None
        assert select.available is False
        assert select.current_option is None
