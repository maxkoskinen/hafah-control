"""Tests for the Folding@Home Control service handlers.

Covers the three custom services registered in ``__init__.py``:

* ``fah_control.fold``  — start folding
* ``fah_control.pause`` — pause folding
* ``fah_control.finish`` — finish current work unit then pause

Each service resolves the target coordinator through the entity registry
(entity_id → config_entry_id → config_entry → runtime_data) and delegates
to ``FahDataUpdateCoordinator.async_send_command``.

The tests mock the HA entity-registry and config-entry lookup chain so that
the service handler code can be exercised without a full HA runtime.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from custom_components.fah_control import (
    _async_register_services,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.fah_control.const import DOMAIN

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENTITY_ID = "select.test_fah_control"
CONFIG_ENTRY_ID = "test_config_entry_id_abc123"


def _make_mock_coordinator() -> AsyncMock:
    """Return a mock coordinator with an ``async_send_command`` method."""
    coordinator = AsyncMock()
    coordinator.host = TEST_HOST
    coordinator.port = TEST_PORT
    coordinator.fah_name = TEST_NAME
    coordinator.async_send_command = AsyncMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    return coordinator


def _make_service_call(
    entity_id: str = ENTITY_ID,
    group: str | None = None,
) -> MagicMock:
    """Build a mock ``ServiceCall`` with the given data."""
    call_obj = MagicMock()
    data: dict[str, Any] = {"entity_id": entity_id}
    if group is not None:
        data["group"] = group
    call_obj.data = data
    return call_obj


def _make_registry_entry(
    config_entry_id: str | None = CONFIG_ENTRY_ID,
) -> MagicMock:
    """Build a mock entity-registry entry."""
    entry = MagicMock()
    entry.config_entry_id = config_entry_id
    return entry


def _make_config_entry(
    coordinator: AsyncMock | None = None,
    entry_id: str = CONFIG_ENTRY_ID,
) -> MagicMock:
    """Build a mock ``ConfigEntry`` with ``runtime_data`` set to the coordinator."""
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.runtime_data = coordinator or _make_mock_coordinator()
    return config_entry


def _setup_hass_for_services(
    coordinator: AsyncMock | None = None,
    registry_entry: MagicMock | None = None,
    config_entry: MagicMock | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """Wire up a mock ``hass`` so that the service handler can resolve a coordinator.

    Returns ``(hass, coordinator)`` — the coordinator whose
    ``async_send_command`` should be asserted against.
    """
    coord = coordinator or _make_mock_coordinator()
    reg_entry = registry_entry or _make_registry_entry()
    cfg_entry = config_entry or _make_config_entry(coord)

    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()

    # entity_registry.async_get(hass) → registry mock
    mock_registry = MagicMock()
    mock_registry.async_get = MagicMock(return_value=reg_entry)

    # config_entries.async_get_entry(entry_id) → config entry mock
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=cfg_entry)

    return hass, coord, mock_registry


def _extract_service_handler(
    hass: MagicMock,
    service_name: str,
) -> Any:
    """Find the handler that was registered for ``DOMAIN.service_name``.

    Walks through the ``hass.services.async_register`` calls to locate the
    one matching the requested service name.
    """
    for c in hass.services.async_register.call_args_list:
        args = c[0]  # positional args: (domain, service, handler, ...)
        if args[0] == DOMAIN and args[1] == service_name:
            return args[2]
    raise AssertionError(
        f"Service {DOMAIN}.{service_name} was not registered. "
        f"Registered calls: {hass.services.async_register.call_args_list}"
    )


# ===================================================================
# Service registration
# ===================================================================


class TestServiceRegistration:
    """Verify that services are registered correctly and only once."""

    def test_services_registered(self) -> None:
        """All three services (fold, pause, finish) are registered."""
        hass, _, _ = _setup_hass_for_services()

        _async_register_services(hass)

        registered_names = [
            c[0][1] for c in hass.services.async_register.call_args_list
        ]
        assert "fold" in registered_names
        assert "pause" in registered_names
        assert "finish" in registered_names

    def test_services_registered_with_correct_domain(self) -> None:
        """All services are registered under the ``fah_control`` domain."""
        hass, _, _ = _setup_hass_for_services()

        _async_register_services(hass)

        for c in hass.services.async_register.call_args_list:
            assert c[0][0] == DOMAIN

    def test_services_not_registered_twice(self) -> None:
        """Calling ``_async_register_services`` a second time is a no-op."""
        hass, _, _ = _setup_hass_for_services()
        hass.services.has_service = MagicMock(return_value=False)

        _async_register_services(hass)
        first_call_count = hass.services.async_register.call_count

        # Simulate that services now exist.
        hass.services.has_service = MagicMock(return_value=True)

        _async_register_services(hass)
        assert hass.services.async_register.call_count == first_call_count

    def test_has_service_checked_before_register(self) -> None:
        """``hass.services.has_service`` is called to prevent double-registration."""
        hass, _, _ = _setup_hass_for_services()

        _async_register_services(hass)

        hass.services.has_service.assert_called_with(DOMAIN, "fold")

    def test_services_registered_with_schema(self) -> None:
        """Each service is registered with a non-None schema."""
        hass, _, _ = _setup_hass_for_services()

        _async_register_services(hass)

        for c in hass.services.async_register.call_args_list:
            # schema is either the 4th positional arg or the 'schema' kwarg
            if len(c[0]) > 3:
                assert c[0][3] is not None
            elif "schema" in c[1]:
                assert c[1]["schema"] is not None


# ===================================================================
# Fold service
# ===================================================================


class TestFoldService:
    """Tests for the ``fah_control.fold`` service."""

    @pytest.mark.asyncio
    async def test_fold_service_sends_command(self) -> None:
        """The fold service resolves the coordinator and sends state='fold'."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="fold", group=None
        )

    @pytest.mark.asyncio
    async def test_fold_service_with_group(self) -> None:
        """When a group is specified, it is forwarded to ``async_send_command``."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id=ENTITY_ID, group="gpu")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="fold", group="gpu"
        )

    @pytest.mark.asyncio
    async def test_fold_service_without_group(self) -> None:
        """When no group is given, ``group=None`` is passed to the coordinator."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        _, kwargs = coordinator.async_send_command.call_args
        assert kwargs.get("group") is None


# ===================================================================
# Pause service
# ===================================================================


class TestPauseService:
    """Tests for the ``fah_control.pause`` service."""

    @pytest.mark.asyncio
    async def test_pause_service_sends_command(self) -> None:
        """The pause service resolves the coordinator and sends state='pause'."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "pause")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="pause", group=None
        )

    @pytest.mark.asyncio
    async def test_pause_service_with_group(self) -> None:
        """When a group is specified, it is forwarded for the pause command."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "pause")

        service_call = _make_service_call(entity_id=ENTITY_ID, group="cpu")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="pause", group="cpu"
        )


# ===================================================================
# Finish service
# ===================================================================


class TestFinishService:
    """Tests for the ``fah_control.finish`` service."""

    @pytest.mark.asyncio
    async def test_finish_service_sends_command(self) -> None:
        """The finish service resolves the coordinator and sends state='finish'."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "finish")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="finish", group=None
        )

    @pytest.mark.asyncio
    async def test_finish_service_with_group(self) -> None:
        """When a group is specified, it is forwarded for the finish command."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "finish")

        service_call = _make_service_call(entity_id=ENTITY_ID, group="gpu")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="finish", group="gpu"
        )

    @pytest.mark.asyncio
    async def test_finish_service_with_named_group(self) -> None:
        """Verify a realistic group name like ``gpu-0`` is passed through."""
        hass, coordinator, mock_registry = _setup_hass_for_services()

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "finish")

        service_call = _make_service_call(entity_id=ENTITY_ID, group="gpu-0")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_awaited_once_with(
            state="finish", group="gpu-0"
        )


# ===================================================================
# Error paths — entity not found
# ===================================================================


class TestEntityNotFound:
    """Tests for when the entity registry cannot resolve the entity_id."""

    @pytest.mark.asyncio
    async def test_entity_not_in_registry(self) -> None:
        """When the entity is not in the registry, the handler logs and returns.

        No exception should propagate — the handler fails gracefully.
        """
        hass, coordinator, mock_registry = _setup_hass_for_services()
        mock_registry.async_get = MagicMock(return_value=None)

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id="select.nonexistent")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            # Should not raise.
            await handler(service_call)

        coordinator.async_send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_entity_has_no_config_entry_id(self) -> None:
        """When the registry entry has ``config_entry_id=None``, fail gracefully."""
        hass, coordinator, mock_registry = _setup_hass_for_services()
        reg_entry = _make_registry_entry(config_entry_id=None)
        mock_registry.async_get = MagicMock(return_value=reg_entry)

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_not_awaited()


# ===================================================================
# Error paths — config entry not found
# ===================================================================


class TestConfigEntryNotFound:
    """Tests for when the config entry lookup fails."""

    @pytest.mark.asyncio
    async def test_config_entry_not_found(self) -> None:
        """When ``async_get_entry`` returns None, the handler fails gracefully."""
        hass, coordinator, mock_registry = _setup_hass_for_services()
        hass.config_entries.async_get_entry = MagicMock(return_value=None)

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "pause")

        service_call = _make_service_call(entity_id=ENTITY_ID)

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        coordinator.async_send_command.assert_not_awaited()


# ===================================================================
# Multiple entities / coordinators
# ===================================================================


class TestMultipleCoordinators:
    """Verify correct coordinator resolution when multiple entries exist."""

    @pytest.mark.asyncio
    async def test_correct_coordinator_resolved(self) -> None:
        """The service resolves the coordinator for the specific entity, not another."""
        coord_a = _make_mock_coordinator()
        coord_b = _make_mock_coordinator()

        cfg_entry_a = _make_config_entry(coord_a, entry_id="entry_a")
        cfg_entry_b = _make_config_entry(coord_b, entry_id="entry_b")

        # entity_id maps to entry_b via the registry
        reg_entry = _make_registry_entry(config_entry_id="entry_b")

        hass, _, mock_registry = _setup_hass_for_services()
        mock_registry.async_get = MagicMock(return_value=reg_entry)

        def _get_entry(entry_id: str) -> MagicMock | None:
            return {"entry_a": cfg_entry_a, "entry_b": cfg_entry_b}.get(entry_id)

        hass.config_entries.async_get_entry = MagicMock(side_effect=_get_entry)

        _async_register_services(hass)
        handler = _extract_service_handler(hass, "fold")

        service_call = _make_service_call(entity_id="select.fah_machine_b")

        with patch(
            "custom_components.fah_control.er.async_get",
            return_value=mock_registry,
        ):
            await handler(service_call)

        # Only coordinator B should have been called.
        coord_b.async_send_command.assert_awaited_once_with(
            state="fold", group=None
        )
        coord_a.async_send_command.assert_not_awaited()


# ===================================================================
# Integration: async_setup_entry registers services
# ===================================================================


class TestSetupEntryRegistersServices:
    """Verify that ``async_setup_entry`` triggers service registration."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_registers_services(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``async_setup_entry`` calls ``_async_register_services``."""
        coordinator = _make_mock_coordinator()

        with (
            patch(
                "custom_components.fah_control.FahDataUpdateCoordinator",
                return_value=coordinator,
            ),
            patch(
                "custom_components.fah_control._async_register_services"
            ) as mock_register,
            patch.object(
                mock_hass.config_entries,
                "async_forward_entry_setups",
                new=AsyncMock(),
            ),
        ):
            result = await async_setup_entry(mock_hass, mock_config_entry)

        assert result is True
        mock_register.assert_called_once_with(mock_hass)

    @pytest.mark.asyncio
    async def test_async_setup_entry_stores_coordinator_as_runtime_data(
        self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """``async_setup_entry`` stores the coordinator on ``entry.runtime_data``."""
        coordinator = _make_mock_coordinator()

        with (
            patch(
                "custom_components.fah_control.FahDataUpdateCoordinator",
                return_value=coordinator,
            ),
            patch("custom_components.fah_control._async_register_services"),
            patch.object(
                mock_hass.config_entries,
                "async_forward_entry_setups",
                new=AsyncMock(),
            ),
        ):
            await async_setup_entry(mock_hass, mock_config_entry)

        assert mock_config_entry.runtime_data is coordinator