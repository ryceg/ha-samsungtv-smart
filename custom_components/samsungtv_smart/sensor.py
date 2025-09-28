"""Support for Samsung TV Art Mode sensors."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api.samsungws import ArtModeStatus, SamsungTVWS
from .const import DATA_CFG, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)

# Update interval for art mode sensors (less frequent than media player)
ART_MODE_UPDATE_INTERVAL = 30  # seconds


class ArtModeDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching art mode data."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Samsung TV Art Mode ({config['host']})",
            update_interval=timedelta(seconds=ART_MODE_UPDATE_INTERVAL),
        )
        self.config = config
        self._samsung_tv: SamsungTVWS | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch art mode data from the TV."""
        if self._samsung_tv is None:
            self._samsung_tv = SamsungTVWS(**self.config)

        try:
            data = {}

            # Get art mode status from existing integration
            art_mode_status = self._samsung_tv.artmode_status

            if art_mode_status == ArtModeStatus.Unsupported:
                _LOGGER.debug("Art mode not supported on %s", self.config['host'])
                return data

            # Convert enum to string for sensor
            if art_mode_status == ArtModeStatus.On:
                data["art_mode_status"] = "on"
            elif art_mode_status == ArtModeStatus.Off:
                data["art_mode_status"] = "off"
            elif art_mode_status == ArtModeStatus.Unavailable:
                data["art_mode_status"] = "unavailable"

            # For now, return basic status. Additional details would require
            # extending the existing WebSocket art mode connection
            return data

        except Exception as exc:
            _LOGGER.debug("Unexpected error fetching art mode data: %s", exc)
            raise UpdateFailed(f"Unexpected error: {exc}")
        finally:
            # Don't close the connection as it's managed by the main integration
            pass


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV art mode sensors."""
    config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]

    # Create coordinator
    coordinator = ArtModeDataUpdateCoordinator(hass, config)

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Only add sensors if art mode is supported
    if coordinator.data:
        entities = [
            ArtModeStatusSensor(coordinator, config_entry),
        ]
        async_add_entities(entities, True)


class SamsungTVArtSensor(CoordinatorEntity, SamsungTVEntity):
    """Base class for Samsung TV art mode sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ArtModeDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        SamsungTVEntity.__init__(self, config_entry)
        self._attr_unique_id = f"{self._uuid}_{self._attr_key}"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._attr_key in self.coordinator.data


class ArtModeStatusSensor(SamsungTVArtSensor):
    """Sensor for art mode on/off status."""

    _attr_key = "art_mode_status"
    _attr_name = "Art mode status"
    _attr_icon = "mdi:television-ambient-light"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._attr_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        return {
            "is_art_mode": self.coordinator.data.get(self._attr_key) == "on"
        }


