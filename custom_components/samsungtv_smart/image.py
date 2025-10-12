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

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity
from .slideshow import SlideshowQueueManager

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
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)
        queue_manager = hass.data[DOMAIN][config_entry.entry_id].get("slideshow_queue")
        _LOGGER.debug("Image setup: ws_instance = %s", "present" if ws_instance else "None")

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

        # Create art mode image entity with WebSocket instance
        entities = [ArtModeImageEntity(hass, config, config_entry.entry_id, media_player_entity_id, ws_instance)]

        # Add slideshow preview images if queue manager is available
        if queue_manager:
            entities.extend([
                SlideshowCurrentImage(hass, config, config_entry.entry_id, media_player_entity_id, queue_manager),
                SlideshowUpNextImage(hass, config, config_entry.entry_id, media_player_entity_id, queue_manager),
                SlideshowPreviousImage(hass, config, config_entry.entry_id, media_player_entity_id, queue_manager),
            ])

        async_add_entities(entities)
        _LOGGER.debug(
            "Successfully set up %d image entities for %s",
            len(entities), config.get(CONF_HOST, "unknown")
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
        ws_instance: Any = None,
    ) -> None:
        """Initialize the image entity."""
        # Set entry_id first before calling parent inits
        self._entry_id = entry_id
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance

        # Initialize SamsungTVEntity
        SamsungTVEntity.__init__(self, config, entry_id)
        # Initialize ImageEntity with required hass parameter
        ImageEntity.__init__(self, hass)

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

        # Available if art mode is supported (regardless of current on/off status)
        # We can request artwork info even when art mode is off
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)

        return art_mode_supported

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

        # Get WebSocket API instance
        if not self._ws:
            _LOGGER.debug("WebSocket instance not available")
            return None

        try:
            # Request thumbnail using executor for sync websocket operation
            # This checks cache first, then requests if needed
            thumbnail = await self.hass.async_add_executor_job(
                self._ws.get_artwork_thumbnail, artwork_id
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


class SlideshowImageBase(SamsungTVEntity, ImageEntity):
    """Base class for slideshow preview images."""

    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the slideshow image entity."""
        self._entry_id = entry_id
        self._media_player_entity_id = media_player_entity_id
        self._queue_manager = queue_manager
        self._ws = None

        SamsungTVEntity.__init__(self, config, entry_id)
        ImageEntity.__init__(self, hass)

        self._cached_image: bytes | None = None
        self._last_artwork_id: str | None = None

    async def async_added_to_hass(self) -> None:
        """Set up when entity is added to hass."""
        await super().async_added_to_hass()
        # Get WebSocket instance after entity is added
        self._ws = self.hass.data[DOMAIN][self._entry_id].get(DATA_WS)

    @property
    def entity_picture(self) -> str | None:
        """Return entity picture URL, handling empty access tokens."""
        if not self.access_tokens:
            return None
        return super().entity_picture

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    async def _get_artwork_image(self, artwork: dict | None) -> bytes | None:
        """Get image bytes for an artwork."""
        if not artwork:
            return None

        content_id = artwork.get("content_id")
        if not content_id:
            return None

        # Check if artwork changed
        if content_id != self._last_artwork_id:
            self._cached_image = None
            self._last_artwork_id = content_id

        # Return cached image if available
        if self._cached_image:
            return self._cached_image

        if not self._ws:
            return None

        try:
            thumbnail = await self.hass.async_add_executor_job(
                self._ws.get_artwork_thumbnail, content_id
            )
            if thumbnail:
                self._cached_image = thumbnail
                return thumbnail
        except Exception as exc:
            _LOGGER.debug("Error fetching artwork thumbnail for %s: %s", content_id, exc)

        return None


class SlideshowCurrentImage(SlideshowImageBase):
    """Image entity showing current slideshow artwork."""

    _attr_name = "Slideshow current"
    _attr_icon = "mdi:image"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the current image entity."""
        super().__init__(hass, config, entry_id, media_player_entity_id, queue_manager)
        self._attr_unique_id = f"{entry_id}_slideshow_current_image"

    async def async_image(self) -> bytes | None:
        """Return bytes of current slideshow artwork."""
        current = self._queue_manager.get_current()
        return await self._get_artwork_image(current)


class SlideshowUpNextImage(SlideshowImageBase):
    """Image entity showing next slideshow artwork."""

    _attr_name = "Slideshow up next"
    _attr_icon = "mdi:skip-next-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the up next image entity."""
        super().__init__(hass, config, entry_id, media_player_entity_id, queue_manager)
        self._attr_unique_id = f"{entry_id}_slideshow_up_next_image"

    async def async_image(self) -> bytes | None:
        """Return bytes of next slideshow artwork."""
        next_artwork = self._queue_manager.peek_next()
        return await self._get_artwork_image(next_artwork)


class SlideshowPreviousImage(SlideshowImageBase):
    """Image entity showing previous slideshow artwork."""

    _attr_name = "Slideshow previous"
    _attr_icon = "mdi:skip-previous-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the previous image entity."""
        super().__init__(hass, config, entry_id, media_player_entity_id, queue_manager)
        self._attr_unique_id = f"{entry_id}_slideshow_previous_image"

    async def async_image(self) -> bytes | None:
        """Return bytes of previous slideshow artwork."""
        if len(self._queue_manager._history) < 2:
            return None
        # Get the second-to-last entry from history
        prev_entry = list(self._queue_manager._history)[-2]
        prev_artwork = prev_entry.get("artwork")
        return await self._get_artwork_image(prev_artwork)