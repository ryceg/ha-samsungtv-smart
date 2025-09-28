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

            # If art mode is on, try to get current artwork information
            if art_mode_status == ArtModeStatus.On:
                try:
                    # Use the new SamsungTVArt API to get current artwork
                    from .api.art import SamsungTVArt
                    art_api = SamsungTVArt(self.config['host'],
                                         self.config.get('port', 8001),
                                         self.config.get('timeout', 5))

                    # Get current artwork details
                    current_artwork = art_api.get_current_artwork()
                    if current_artwork:
                        data["current_artwork"] = current_artwork

                    art_api.close()

                except Exception as exc:
                    _LOGGER.debug("Error fetching current artwork: %s", exc)
                    # Don't fail the entire update for artwork info
                    # Set a placeholder so the user knows there was an issue
                    data["current_artwork"] = {"error": str(exc)}

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
            CurrentArtworkSensor(coordinator, config_entry),
        ]
        async_add_entities(entities, True)
    else:
        # Check if Frame TV is supported through device info
        try:
            from .api.art import SamsungTVArt
            art_api = SamsungTVArt(config['host'])
            if art_api.supported():
                _LOGGER.info("Frame TV detected for %s but art mode currently unavailable", config['host'])
                # Still add the sensors as they might become available later
                entities = [
                    ArtModeStatusSensor(coordinator, config_entry),
                    CurrentArtworkSensor(coordinator, config_entry),
                ]
                async_add_entities(entities, True)
            art_api.close()
        except Exception as exc:
            _LOGGER.debug("Could not check Frame TV support for %s: %s", config['host'], exc)


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
        return (self.coordinator.last_update_success and
                (self._attr_key in self.coordinator.data or
                 self.coordinator.data.get("art_mode_status") is not None))


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


class CurrentArtworkSensor(SamsungTVArtSensor):
    """Sensor for current artwork in art mode."""

    _attr_key = "current_artwork"
    _attr_name = "Current artwork"
    _attr_icon = "mdi:image-frame"

    @property
    def native_value(self) -> str | None:
        """Return the name/title of current artwork."""
        # Check if art mode is on first
        art_mode_status = self.coordinator.data.get("art_mode_status")
        if art_mode_status != "on":
            if art_mode_status == "off":
                return "Art mode off"
            elif art_mode_status == "unavailable":
                return "Art mode unavailable"
            else:
                return "Unknown"

        artwork_data = self.coordinator.data.get(self._attr_key)
        if artwork_data:
            # Handle error case
            if "error" in artwork_data:
                return "Error loading artwork"

            # Try different possible keys for artwork name
            return (
                artwork_data.get("content_name") or
                artwork_data.get("title") or
                artwork_data.get("name") or
                "Unknown Artwork"
            )
        return "No artwork info"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes for artwork details."""
        artwork_data = self.coordinator.data.get(self._attr_key)
        art_mode_status = self.coordinator.data.get("art_mode_status")

        base_attrs = {
            "art_mode_status": art_mode_status,
            "is_art_mode": art_mode_status == "on"
        }

        if artwork_data:
            # Handle error case
            if "error" in artwork_data:
                base_attrs["error"] = artwork_data["error"]
                return base_attrs

            # Add artwork details
            base_attrs.update({
                "content_id": artwork_data.get("content_id"),
                "category_id": artwork_data.get("category_id"),
                "image_url": artwork_data.get("image_url"),
                "thumbnail_url": artwork_data.get("thumbnail_url"),
                "artist": artwork_data.get("artist"),
                "description": artwork_data.get("description"),
                "artwork_data": artwork_data  # Full data for advanced users
            })

        return base_attrs

    @property
    def entity_picture(self) -> str | None:
        """Return artwork image for entity picture."""
        artwork_data = self.coordinator.data.get(self._attr_key)
        if artwork_data and "error" not in artwork_data:
            # Prefer thumbnail for entity picture to reduce size
            return artwork_data.get("thumbnail_url") or artwork_data.get("image_url")
        return None

