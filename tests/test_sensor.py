"""Tests for the Folding@Home Control sensor entities.

Covers the ``FahStateSensor`` entity including:

* ``native_value`` reflects the coordinator's folding state string
* ``available`` tracks the coordinator's ``available`` flag
* ``extra_state_attributes`` exposes groups, host, port, and enriched machine/account info
* ``unique_id``, ``name``, ``icon``, and ``device_info`` are set correctly
* Dynamic state transitions when coordinator data changes

Also covers the ``FahPPDSensor`` entity including:

* ``native_value`` reflects total PPD from coordinator data
* ``available`` tracks the coordinator's ``available`` flag
* ``extra_state_attributes`` exposes per-unit PPD breakdown
* ``unique_id``, ``name``, ``icon``, ``unit_of_measurement`` are set correctly
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fah_control.const import (
    DOMAIN,
    STATE_FINISHING,
    STATE_FOLDING,
    STATE_OFFLINE,
    STATE_PAUSED,
)
from custom_components.fah_control.sensor import FahPPDSensor, FahStateSensor

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    data: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock ``FahDataUpdateCoordinator`` with the given data.

    The mock exposes the minimum surface area that ``FahStateSensor``
    depends on: ``.data``, ``.host``, ``.port``, ``.name``, and
    listener management methods expected by ``CoordinatorEntity``.
    """
    coordinator = MagicMock()
    coordinator.host = TEST_HOST
    coordinator.port = TEST_PORT
    coordinator.name = f"{DOMAIN}_{TEST_HOST}_{TEST_PORT}"
    coordinator.fah_name = TEST_NAME
    coordinator.data = data
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    return coordinator


def _make_sensor(
    coordinator_data: dict[str, Any] | None = None,
) -> tuple[FahStateSensor, MagicMock]:
    """Instantiate a ``FahStateSensor`` backed by a mock coordinator.

    Returns both the sensor entity and the underlying mock coordinator so
    tests can inspect or mutate state.
    """
    coordinator = _make_coordinator(coordinator_data)
    sensor = FahStateSensor(coordinator)
    return sensor, coordinator


def _make_ppd_sensor(
    coordinator_data: dict[str, Any] | None = None,
) -> tuple[FahPPDSensor, MagicMock]:
    """Instantiate a ``FahPPDSensor`` backed by a mock coordinator.

    Returns both the sensor entity and the underlying mock coordinator so
    tests can inspect or mutate state.
    """
    coordinator = _make_coordinator(coordinator_data)
    sensor = FahPPDSensor(coordinator)
    return sensor, coordinator


# ---------------------------------------------------------------------------
# Default coordinator data payloads (enriched with units, machine_info, account)
# ---------------------------------------------------------------------------

FOLDING_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_FOLDING,
    "groups": ["default"],
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
    "raw": {"state": "RUNNING", "groups": {"default": {"state": "RUNNING"}}},
}

PAUSED_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_PAUSED,
    "groups": ["default"],
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
    "raw": {"state": "PAUSED", "groups": {"default": {"state": "PAUSED"}}},
}

FINISHING_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_FINISHING,
    "groups": ["default"],
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
    "raw": {"state": "FINISHING", "groups": {"default": {"state": "FINISHING"}}},
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

MULTI_GROUP_DATA: dict[str, Any] = {
    "available": True,
    "state": STATE_FOLDING,
    "groups": ["cpu", "gpu-0", "gpu-1"],
    "units": [
        {
            "number": 1,
            "state": "RUN",
            "ppd": 100000,
            "progress": 0.3,
            "eta": "1h",
            "run_time": 1800,
            "project": 18490,
            "credit": 19948,
            "cpus": 27,
            "gpus": [],
            "description": "CPU",
            "paused": False,
        },
        {
            "number": 2,
            "state": "RUN",
            "ppd": 500000,
            "progress": 0.7,
            "eta": "20m",
            "run_time": 4200,
            "project": 19000,
            "credit": 50000,
            "cpus": 0,
            "gpus": ["gpu-0"],
            "description": "GPU-0",
            "paused": False,
        },
    ],
    "total_ppd": 600000,
    "machine_info": {
        "version": "8.5.5",
        "cpu_brand": "Test CPU",
        "cpus": 32,
        "os": "linux",
        "os_version": "6.17",
        "mach_name": "test",
        "hostname": "test",
        "gpus": [{"id": "gpu:01:00:00", "description": "Test GPU"}],
    },
    "account": {"user": "testuser", "team": 0, "cause": "any"},
    "raw": {
        "state": "RUNNING",
        "groups": {
            "cpu": {"state": "RUNNING"},
            "gpu-0": {"state": "PAUSED"},
            "gpu-1": {"state": "FINISHING"},
        },
    },
}


# ===================================================================
# native_value property
# ===================================================================


class TestNativeValue:
    """Verify that ``native_value`` correctly reflects the folding state."""

    def test_sensor_state_folding(self) -> None:
        """Sensor reports ``folding`` when the FAH client is actively folding."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.native_value == STATE_FOLDING

    def test_sensor_state_paused(self) -> None:
        """Sensor reports ``paused`` when the FAH client is paused."""
        sensor, _ = _make_sensor(PAUSED_DATA)
        assert sensor.native_value == STATE_PAUSED

    def test_sensor_state_finishing(self) -> None:
        """Sensor reports ``finishing`` when the FAH client is finishing."""
        sensor, _ = _make_sensor(FINISHING_DATA)
        assert sensor.native_value == STATE_FINISHING

    def test_sensor_state_offline(self) -> None:
        """Sensor reports ``offline`` when the FAH client is unreachable."""
        sensor, _ = _make_sensor(OFFLINE_DATA)
        assert sensor.native_value == STATE_OFFLINE

    def test_sensor_state_offline_when_unavailable(self) -> None:
        """When available=False the sensor reports ``offline`` regardless of
        what the ``state`` key says."""
        data = {
            "available": False,
            "state": STATE_FOLDING,  # contradictory, but available wins
            "groups": [],
            "units": [],
            "total_ppd": 0,
            "machine_info": {},
            "account": {},
            "raw": {},
        }
        sensor, _ = _make_sensor(data)
        assert sensor.native_value == STATE_OFFLINE

    def test_sensor_state_offline_when_no_data(self) -> None:
        """Before the coordinator has any data, the sensor reports ``offline``."""
        sensor, _ = _make_sensor(None)
        assert sensor.native_value == STATE_OFFLINE

    def test_sensor_state_offline_when_state_key_missing(self) -> None:
        """If the ``state`` key is absent but available=False, report offline."""
        data: dict[str, Any] = {
            "available": False,
            "groups": [],
            "units": [],
            "total_ppd": 0,
            "machine_info": {},
            "account": {},
            "raw": {},
        }
        sensor, _ = _make_sensor(data)
        assert sensor.native_value == STATE_OFFLINE

    def test_sensor_state_defaults_to_offline_for_available_missing_state(self) -> None:
        """If available=True but the ``state`` key is missing, fall back to offline."""
        data: dict[str, Any] = {
            "available": True,
            "groups": [],
            "units": [],
            "total_ppd": 0,
            "machine_info": {},
            "account": {},
            "raw": {},
        }
        sensor, _ = _make_sensor(data)
        # The implementation uses .get("state", STATE_OFFLINE), so missing -> offline.
        assert sensor.native_value == STATE_OFFLINE


# ===================================================================
# available property
# ===================================================================


class TestAvailable:
    """Verify that ``available`` tracks the coordinator's availability flag."""

    def test_available_when_folding(self) -> None:
        """Entity is available when the FAH client is reachable and folding."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.available is True

    def test_available_when_paused(self) -> None:
        """Entity is available when the FAH client is reachable and paused."""
        sensor, _ = _make_sensor(PAUSED_DATA)
        assert sensor.available is True

    def test_available_when_finishing(self) -> None:
        """Entity is available when the FAH client is reachable and finishing."""
        sensor, _ = _make_sensor(FINISHING_DATA)
        assert sensor.available is True

    def test_unavailable_when_offline(self) -> None:
        """Entity is unavailable when the FAH client cannot be reached."""
        sensor, _ = _make_sensor(OFFLINE_DATA)
        assert sensor.available is False

    def test_unavailable_when_no_data(self) -> None:
        """Entity is unavailable before the coordinator has any data."""
        sensor, _ = _make_sensor(None)
        assert sensor.available is False

    def test_unavailable_when_available_key_missing(self) -> None:
        """Entity is unavailable when the ``available`` key is absent from data."""
        sensor, _ = _make_sensor({"state": STATE_FOLDING, "groups": []})
        assert sensor.available is False


# ===================================================================
# extra_state_attributes property
# ===================================================================


class TestExtraStateAttributes:
    """Verify that ``extra_state_attributes`` exposes the expected keys."""

    def test_attributes_contain_groups(self) -> None:
        """The ``groups`` attribute lists all resource-group names."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "groups" in attrs
        assert attrs["groups"] == ["default"]

    def test_attributes_contain_host(self) -> None:
        """The ``host`` attribute matches the coordinator's host."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "host" in attrs
        assert attrs["host"] == TEST_HOST

    def test_attributes_contain_port(self) -> None:
        """The ``port`` attribute matches the coordinator's port."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "port" in attrs
        assert attrs["port"] == TEST_PORT

    def test_attributes_contain_fah_version(self) -> None:
        """The ``fah_version`` attribute exposes the FAH client version."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "fah_version" in attrs
        assert attrs["fah_version"] == "8.5.5"

    def test_attributes_contain_cpu(self) -> None:
        """The ``cpu`` attribute exposes the CPU brand string."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "cpu" in attrs
        assert attrs["cpu"] == "Test CPU"

    def test_attributes_contain_gpus(self) -> None:
        """The ``gpus`` attribute exposes the GPU list."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "gpus" in attrs
        assert attrs["gpus"] == []

    def test_attributes_contain_os(self) -> None:
        """The ``os`` attribute exposes the OS name and version."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "os" in attrs
        assert attrs["os"] == "linux 6.17"

    def test_attributes_contain_user(self) -> None:
        """The ``user`` attribute exposes the FAH account user."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "user" in attrs
        assert attrs["user"] == "testuser"

    def test_attributes_contain_team(self) -> None:
        """The ``team`` attribute exposes the FAH team number."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "team" in attrs
        assert attrs["team"] == 0

    def test_attributes_contain_work_units(self) -> None:
        """The ``work_units`` attribute exposes the work unit details."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "work_units" in attrs
        assert len(attrs["work_units"]) == 1
        wu = attrs["work_units"][0]
        assert wu["number"] == 1
        assert wu["state"] == "RUN"
        assert wu["progress"] == 0.5
        assert wu["ppd"] == 250000
        assert wu["project"] == 18490

    def test_attributes_multiple_groups(self) -> None:
        """Multiple resource groups are all listed in the ``groups`` attribute."""
        sensor, _ = _make_sensor(MULTI_GROUP_DATA)
        attrs = sensor.extra_state_attributes
        assert set(attrs["groups"]) == {"cpu", "gpu-0", "gpu-1"}

    def test_attributes_empty_groups_when_offline(self) -> None:
        """When the client is offline, ``groups`` is an empty list."""
        sensor, _ = _make_sensor(OFFLINE_DATA)
        attrs = sensor.extra_state_attributes
        assert attrs["groups"] == []

    def test_attributes_empty_groups_when_no_data(self) -> None:
        """When coordinator data is ``None``, ``groups`` defaults to ``[]``."""
        sensor, _ = _make_sensor(None)
        attrs = sensor.extra_state_attributes
        assert attrs["groups"] == []

    def test_attributes_all_keys_present(self) -> None:
        """Exactly the expected keys are returned — no more, no fewer."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert set(attrs.keys()) == {
            "groups",
            "host",
            "port",
            "fah_version",
            "cpu",
            "gpus",
            "os",
            "user",
            "team",
            "work_units",
        }

    def test_attributes_host_and_port_types(self) -> None:
        """``host`` is a string and ``port`` is an integer."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert isinstance(attrs["host"], str)
        assert isinstance(attrs["port"], int)

    def test_attributes_none_values_when_offline(self) -> None:
        """When offline, machine_info and account fields are None/empty."""
        sensor, _ = _make_sensor(OFFLINE_DATA)
        attrs = sensor.extra_state_attributes
        assert attrs["fah_version"] is None
        assert attrs["cpu"] is None
        assert attrs["gpus"] == []
        assert attrs["os"] is None
        assert attrs["user"] is None
        assert attrs["team"] is None
        assert attrs["work_units"] == []

    def test_attributes_none_values_when_no_data(self) -> None:
        """When coordinator data is None, enriched fields are None/empty."""
        sensor, _ = _make_sensor(None)
        attrs = sensor.extra_state_attributes
        assert attrs["fah_version"] is None
        assert attrs["cpu"] is None
        assert attrs["gpus"] == []
        assert attrs["os"] is None
        assert attrs["user"] is None
        assert attrs["team"] is None
        assert attrs["work_units"] == []

    def test_attributes_gpus_with_gpu_present(self) -> None:
        """When GPUs are present in machine_info, they are exposed."""
        sensor, _ = _make_sensor(MULTI_GROUP_DATA)
        attrs = sensor.extra_state_attributes
        assert len(attrs["gpus"]) == 1
        assert attrs["gpus"][0]["description"] == "Test GPU"


# ===================================================================
# Entity metadata
# ===================================================================


class TestEntityMetadata:
    """Verify unique_id, name, icon, and device_info are set correctly."""

    def test_unique_id(self) -> None:
        """``unique_id`` follows the ``{host}_{port}_state`` pattern."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.unique_id == f"{TEST_HOST}_{TEST_PORT}_state"

    def test_name(self) -> None:
        """The entity name is ``State``."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.name == "State"

    def test_has_entity_name(self) -> None:
        """``has_entity_name`` is True so HA prepends the device name."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.has_entity_name is True

    def test_icon(self) -> None:
        """The icon is the state-machine MDI icon."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        assert sensor.icon == "mdi:state-machine"

    def test_device_info_identifiers(self) -> None:
        """Device identifiers use ``(DOMAIN, host:port)``."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        info = sensor.device_info
        assert info is not None
        assert (DOMAIN, f"{TEST_HOST}:{TEST_PORT}") in info["identifiers"]

    def test_device_info_manufacturer(self) -> None:
        """The manufacturer is the Folding@Home Consortium."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        info = sensor.device_info
        assert info is not None
        assert info["manufacturer"] == "Folding@Home Consortium"

    def test_device_info_model(self) -> None:
        """The model reflects the FAH v8 client."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        info = sensor.device_info
        assert info is not None
        assert "v8" in info["model"]

    def test_device_info_configuration_url(self) -> None:
        """The configuration URL points to the FAH client's web UI."""
        sensor, _ = _make_sensor(FOLDING_DATA)
        info = sensor.device_info
        assert info is not None
        assert TEST_HOST in info["configuration_url"]
        assert str(TEST_PORT) in info["configuration_url"]


# ===================================================================
# State transitions (data changes on the coordinator)
# ===================================================================


class TestStateTransitions:
    """Verify that the sensor reflects coordinator data changes dynamically."""

    def test_transition_folding_to_paused(self) -> None:
        """When coordinator data switches from folding to paused, native_value updates."""
        sensor, coordinator = _make_sensor(FOLDING_DATA)
        assert sensor.native_value == STATE_FOLDING

        coordinator.data = PAUSED_DATA
        assert sensor.native_value == STATE_PAUSED

    def test_transition_paused_to_folding(self) -> None:
        """When coordinator data switches from paused to folding, native_value updates."""
        sensor, coordinator = _make_sensor(PAUSED_DATA)
        assert sensor.native_value == STATE_PAUSED

        coordinator.data = FOLDING_DATA
        assert sensor.native_value == STATE_FOLDING

    def test_transition_folding_to_finishing(self) -> None:
        """State transitions from folding to finishing are reflected."""
        sensor, coordinator = _make_sensor(FOLDING_DATA)
        assert sensor.native_value == STATE_FOLDING

        coordinator.data = FINISHING_DATA
        assert sensor.native_value == STATE_FINISHING

    def test_transition_folding_to_offline(self) -> None:
        """When the client goes offline, the sensor shows ``offline``."""
        sensor, coordinator = _make_sensor(FOLDING_DATA)
        assert sensor.native_value == STATE_FOLDING
        assert sensor.available is True

        coordinator.data = OFFLINE_DATA
        assert sensor.native_value == STATE_OFFLINE
        assert sensor.available is False

    def test_transition_offline_to_folding(self) -> None:
        """When the client comes back online, the sensor reflects the new state."""
        sensor, coordinator = _make_sensor(OFFLINE_DATA)
        assert sensor.native_value == STATE_OFFLINE
        assert sensor.available is False

        coordinator.data = FOLDING_DATA
        assert sensor.native_value == STATE_FOLDING
        assert sensor.available is True

    def test_transition_to_none_data(self) -> None:
        """If coordinator data becomes ``None``, the sensor goes offline/unavailable."""
        sensor, coordinator = _make_sensor(FOLDING_DATA)
        assert sensor.available is True

        coordinator.data = None
        assert sensor.available is False
        assert sensor.native_value == STATE_OFFLINE

    def test_groups_update_on_transition(self) -> None:
        """When the coordinator data changes, extra_state_attributes update too."""
        sensor, coordinator = _make_sensor(FOLDING_DATA)
        assert sensor.extra_state_attributes["groups"] == ["default"]

        coordinator.data = MULTI_GROUP_DATA
        assert set(sensor.extra_state_attributes["groups"]) == {
            "cpu",
            "gpu-0",
            "gpu-1",
        }

    def test_groups_empty_on_offline_transition(self) -> None:
        """Groups become empty when the client goes offline."""
        sensor, coordinator = _make_sensor(MULTI_GROUP_DATA)
        assert len(sensor.extra_state_attributes["groups"]) == 3

        coordinator.data = OFFLINE_DATA
        assert sensor.extra_state_attributes["groups"] == []


# ===================================================================
# FahPPDSensor
# ===================================================================


class TestPPDSensor:
    """Tests for the ``FahPPDSensor`` entity."""

    def test_ppd_value_when_folding(self) -> None:
        """``native_value`` equals ``total_ppd`` from coordinator data."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.native_value == 250000

    def test_ppd_value_when_paused(self) -> None:
        """``native_value`` is ``0`` when paused (total_ppd=0)."""
        sensor, _ = _make_ppd_sensor(PAUSED_DATA)
        assert sensor.native_value == 0

    def test_ppd_value_when_offline(self) -> None:
        """``native_value`` is ``None`` when the client is offline."""
        sensor, _ = _make_ppd_sensor(OFFLINE_DATA)
        assert sensor.native_value is None

    def test_ppd_value_when_no_data(self) -> None:
        """``native_value`` is ``None`` when coordinator data is ``None``."""
        sensor, _ = _make_ppd_sensor(None)
        assert sensor.native_value is None

    def test_ppd_available_when_folding(self) -> None:
        """PPD sensor is available when the FAH client is reachable."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.available is True

    def test_ppd_unavailable_when_offline(self) -> None:
        """PPD sensor is unavailable when the FAH client cannot be reached."""
        sensor, _ = _make_ppd_sensor(OFFLINE_DATA)
        assert sensor.available is False

    def test_ppd_unavailable_when_no_data(self) -> None:
        """PPD sensor is unavailable when coordinator data is ``None``."""
        sensor, _ = _make_ppd_sensor(None)
        assert sensor.available is False

    def test_ppd_unit_details_attribute(self) -> None:
        """``extra_state_attributes`` has ``unit_details`` list with per-unit breakdown."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        attrs = sensor.extra_state_attributes
        assert "unit_details" in attrs
        assert len(attrs["unit_details"]) == 1
        detail = attrs["unit_details"][0]
        assert detail["ppd"] == 250000
        assert detail["description"] == "CPU"
        assert detail["progress"] == 0.5
        assert detail["eta"] == "30m"
        assert detail["project"] == 18490

    def test_ppd_unit_details_empty_when_offline(self) -> None:
        """``unit_details`` is empty when the client is offline."""
        sensor, _ = _make_ppd_sensor(OFFLINE_DATA)
        attrs = sensor.extra_state_attributes
        assert attrs["unit_details"] == []

    def test_ppd_unit_details_empty_when_no_data(self) -> None:
        """``unit_details`` is empty when coordinator data is ``None``."""
        sensor, _ = _make_ppd_sensor(None)
        attrs = sensor.extra_state_attributes
        assert attrs["unit_details"] == []

    def test_ppd_unit_details_multiple_units(self) -> None:
        """``unit_details`` lists all work units from MULTI_GROUP_DATA."""
        sensor, _ = _make_ppd_sensor(MULTI_GROUP_DATA)
        attrs = sensor.extra_state_attributes
        assert len(attrs["unit_details"]) == 2
        descriptions = [d["description"] for d in attrs["unit_details"]]
        assert "CPU" in descriptions
        assert "GPU-0" in descriptions

    def test_ppd_metadata_unique_id(self) -> None:
        """``unique_id`` follows the ``{host}_{port}_ppd`` pattern."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.unique_id == f"{TEST_HOST}_{TEST_PORT}_ppd"

    def test_ppd_metadata_name(self) -> None:
        """The entity name is ``Points Per Day``."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.name == "Points Per Day"

    def test_ppd_metadata_icon(self) -> None:
        """The icon is the star-four-points MDI icon."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.icon == "mdi:star-four-points"

    def test_ppd_metadata_unit_of_measurement(self) -> None:
        """The unit of measurement is ``PPD``."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.native_unit_of_measurement == "PPD"

    def test_ppd_metadata_device_info(self) -> None:
        """PPD sensor shares the same device info as the state sensor."""
        sensor, _ = _make_ppd_sensor(FOLDING_DATA)
        info = sensor.device_info
        assert info is not None
        assert (DOMAIN, f"{TEST_HOST}:{TEST_PORT}") in info["identifiers"]

    def test_ppd_transition_folding_to_offline(self) -> None:
        """PPD sensor goes unavailable and returns None when client goes offline."""
        sensor, coordinator = _make_ppd_sensor(FOLDING_DATA)
        assert sensor.native_value == 250000
        assert sensor.available is True

        coordinator.data = OFFLINE_DATA
        assert sensor.native_value is None
        assert sensor.available is False

    def test_ppd_transition_offline_to_folding(self) -> None:
        """PPD sensor recovers when client comes back online."""
        sensor, coordinator = _make_ppd_sensor(OFFLINE_DATA)
        assert sensor.native_value is None

        coordinator.data = FOLDING_DATA
        assert sensor.native_value == 250000
        assert sensor.available is True

    def test_ppd_multi_group_value(self) -> None:
        """PPD sensor shows the total PPD across all work units."""
        sensor, _ = _make_ppd_sensor(MULTI_GROUP_DATA)
        assert sensor.native_value == 600000
