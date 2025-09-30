"""Support for Samsung TV Art Mode image display."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV art mode image entity."""

    @callback
    def _add_art_mode_image(utc_now: datetime) -> None:
        """Create art mode image entity after media player is ready."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]

        # Find the media player entity for this TV using entity registry
        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id:
            _LOGGER.debug("Media player entity not found for art mode image")
            return

        # Check if art mode is supported via media player attributes
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping image setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        # Create art mode image entity
        entity = ArtModeImageEntity(hass, config, config_entry.entry_id, media_player_entity_id)
        async_add_entities([entity])
        _LOGGER.debug(
            "Successfully set up art mode image for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_art_mode_image)


class ArtModeImageEntity(SamsungTVEntity, ImageEntity):
    """Image entity for displaying current art mode artwork."""

    _attr_has_entity_name = True
    _attr_name = "Current Artwork"
    _attr_icon = "mdi:image-frame"
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
    ) -> None:
        """Initialize the image entity."""
        # Initialize SamsungTVEntity
        SamsungTVEntity.__init__(self, config, entry_id)
        # Initialize ImageEntity with required hass parameter
        ImageEntity.__init__(self, hass)

        self._media_player_entity_id = media_player_entity_id
        self._attr_unique_id = f"{self.unique_id}_art_image"
        self._last_artwork_id = None
        self._cached_image: bytes | None = None

    async def async_added_to_hass(self) -> None:
        """Set up state change tracking when entity is added to hass."""
        await super().async_added_to_hass()

        # Track media player state changes to detect artwork updates
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._media_player_entity_id],
                self._handle_media_player_update
            )
        )

    @callback
    def _handle_media_player_update(self, event) -> None:
        """Handle media player state changes."""
        if event.data.get("entity_id") == self._media_player_entity_id:
            # Check if current artwork has changed
            new_state = event.data.get("new_state")
            if new_state:
                artwork_data = new_state.attributes.get("current_artwork", {})
                artwork_id = artwork_data.get("content_id") if isinstance(artwork_data, dict) else None

                if artwork_id and artwork_id != self._last_artwork_id:
                    self._last_artwork_id = artwork_id
                    self._cached_image = None  # Invalidate cache
                    self._attr_image_last_updated = datetime.now()
                    self.async_write_ha_state()

    @property
    def entity_picture(self) -> str | None:
        """Return entity picture URL, handling empty access tokens."""
        # Prevent IndexError when access_tokens is empty during entity initialization
        if not self.access_tokens:
            return None
        return super().entity_picture

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False

        # Available if art mode is supported and currently on
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        art_mode_status = media_player_state.attributes.get("art_mode_status")

        return art_mode_supported and art_mode_status == "on"

    async def async_image(self) -> bytes | None:
        """Return bytes of the current artwork image."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available")
            return None

        # Get current artwork info
        artwork_data = media_player_state.attributes.get("current_artwork")
        if not artwork_data or not isinstance(artwork_data, dict):
            _LOGGER.debug("No current artwork data available")
            return None

        artwork_id = artwork_data.get("content_id")
        if not artwork_id:
            _LOGGER.debug("No artwork ID in current artwork data")
            return None

        # Check if artwork has changed
        if artwork_id != self._last_artwork_id:
            _LOGGER.debug("Artwork changed from %s to %s", self._last_artwork_id, artwork_id)
            self._cached_image = None
            self._last_artwork_id = artwork_id

        # Return cached image if available for this artwork
        if self._cached_image:
            return self._cached_image

        # Get WebSocket API instance from config entry
        try:
            entry_data = self.hass.data[DOMAIN][self._entry_id]
            ws_api = entry_data.get("ws")

            if not ws_api:
                _LOGGER.error("WebSocket API not available")
                return None

            # Request thumbnail using executor for sync websocket operation
            # This checks cache first, then requests if needed
            thumbnail = await self.hass.async_add_executor_job(
                ws_api.get_artwork_thumbnail, artwork_id
            )

            if thumbnail:
                _LOGGER.debug("Received thumbnail for artwork %s (%d bytes)",
                            artwork_id, len(thumbnail))
                self._cached_image = thumbnail
                return thumbnail

            # Thumbnail not available yet (websocket response pending)
            # Request it and return None - the image will update once received
            _LOGGER.debug("Thumbnail not yet available for artwork %s, requested from TV",
                        artwork_id)
            return None

        except Exception as exc:
            _LOGGER.error("Error fetching artwork image: %s", exc)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        artwork_data = media_player_state.attributes.get("current_artwork", {})
        if not isinstance(artwork_data, dict):
            return None

        return {
            "artwork_id": artwork_data.get("content_id"),
            "artwork_category": artwork_data.get("category"),
            "media_player_entity_id": self._media_player_entity_id,
        }