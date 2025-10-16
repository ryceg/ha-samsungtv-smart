"""Support for Samsung TV Art Mode switches."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    CONF_OVERLAY_CALENDAR_ENTITIES,
    CONF_OVERLAY_TODO_ENTITIES,
    CONF_OVERLAY_WEATHER_ENTITY,
    DATA_CFG,
    DATA_WS,
    DOMAIN,
    SERVICE_OVERLAY_CLEAR,
    SERVICE_OVERLAY_CONFIGURE,
    SERVICE_OVERLAY_REFRESH,
)
from .entity import SamsungTVEntity
from .overlay import OverlaySwitch
from .slideshow import SlideshowQueueManager, CATEGORY_MY_PICTURES


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV switch entities."""

    @callback
    def _add_entities(utc_now: datetime) -> None:
        """Create entities."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)

        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id:
            _LOGGER.debug("Media player entity not found for switch entities")
            return

        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping switch entity setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        queue_manager = hass.data[DOMAIN][config_entry.entry_id].get("slideshow_queue")
        if not queue_manager:
            _LOGGER.debug("Slideshow queue manager not found")
            return

        overlay_generator = hass.data[DOMAIN][config_entry.entry_id].get("overlay_generator")
        if not overlay_generator:
            _LOGGER.debug("Overlay generator not found")
            return

        entities = [
            SlideshowSwitch(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            OverlaySwitch(hass, config, config_entry.entry_id, ws_instance, overlay_generator),
        ]
        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode switch entities for %s",
            config.get(CONF_HOST, "unknown")
        )

    async_call_later(hass, 10, _add_entities)

    # Register overlay services
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_OVERLAY_CONFIGURE,
        {
            vol.Optional("calendar_entities"): cv.string,
            vol.Optional("weather_entity"): cv.entity_id,
            vol.Optional("todo_entities"): cv.string,
            vol.Optional("update_interval"): cv.positive_int,
        },
        "async_service_overlay_configure",
    )

    platform.async_register_entity_service(
        SERVICE_OVERLAY_REFRESH,
        {},
        "async_service_overlay_refresh",
    )

    platform.async_register_entity_service(
        SERVICE_OVERLAY_CLEAR,
        {},
        "async_service_overlay_clear",
    )


class SlideshowSwitch(SamsungTVEntity, SwitchEntity):
    """Switch entity to control slideshow on/off."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow"
    _attr_icon = "mdi:play-circle"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the slideshow switch."""
        super().__init__(config, entry_id)
        self._entry_id = entry_id
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_switch"
        self._is_on = False
        self._duration = 10  # Default 10 minutes
        self._category = CATEGORY_MY_PICTURES
        self._cancel_timer = None  # Timer for advancing slides

    async def async_added_to_hass(self) -> None:
        """Set up state change tracking when entity is added to hass."""
        await super().async_added_to_hass()

        # Track media player state changes
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
            new_state = event.data.get("new_state")
            if new_state:
                # Check slideshow status from media player
                slideshow_data = new_state.attributes.get("slideshow_status", {})
                if isinstance(slideshow_data, dict):
                    # Update our state based on TV's slideshow status
                    self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return true if slideshow is on."""
        # Use our internal state for slideshow control
        # The TV's slideshow status may not reflect external provider slideshow
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "interval": self._duration,
            "category": self._category,
            "shuffle": self._queue_manager.shuffle,
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False

        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on slideshow."""
        if not self._ws or not hasattr(self._ws, 'set_auto_rotation_status'):
            _LOGGER.error("WebSocket API not available for slideshow control")
            return

        try:
            # Load artworks if none available
            if not self._queue_manager._available_artworks:
                _LOGGER.info("No artworks available, loading from providers and TV...")
                await self._load_artworks()

            if not self._queue_manager._available_artworks:
                _LOGGER.warning("No artworks available to display in slideshow")
                return

            # Use queue manager's shuffle setting
            shuffle = self._queue_manager.shuffle

            # Try to enable TV's native slideshow for TV artworks
            tv_artworks = [a for a in self._queue_manager._available_artworks if a.get("content_id")]
            if tv_artworks:
                await self.hass.async_add_executor_job(
                    self._ws.set_auto_rotation_status,
                    self._duration,
                    shuffle,
                    self._category
                )
                _LOGGER.debug("Started TV slideshow (duration=%d, shuffle=%s, category=%d)",
                             self._duration, shuffle, self._category)

            self._is_on = True
            self.async_write_ha_state()

            # Start manual slideshow timer for external artworks
            self._start_slideshow_timer()

        except Exception as exc:
            _LOGGER.error("Error starting slideshow: %s", exc)

    def _start_slideshow_timer(self) -> None:
        """Start timer to advance slides."""
        if self._cancel_timer:
            self._cancel_timer()

        # Schedule next slide based on duration (convert minutes to seconds)
        interval = self._duration * 60 if self._duration > 0 else 600  # Default 10 min

        async def _advance_slide(now):
            if self._is_on:
                await self._advance_to_next()
                self._start_slideshow_timer()  # Schedule next

        self._cancel_timer = async_call_later(self.hass, interval, _advance_slide)
        _LOGGER.debug("Scheduled next slide in %d seconds", interval)

    async def _advance_to_next(self) -> None:
        """Advance to next artwork in queue."""
        next_artwork = self._queue_manager.get_next()
        if not next_artwork:
            _LOGGER.debug("No next artwork available")
            return

        # TV artworks use 'content_id', external providers use 'id'
        artwork_id = next_artwork.get("content_id") or next_artwork.get("id")
        if artwork_id:
            try:
                # Call the media player's select_artwork service
                await self.hass.services.async_call(
                    DOMAIN,
                    "select_artwork",
                    {
                        "entity_id": self._media_player_entity_id,
                        "artwork_id": artwork_id,
                        "show": True,
                    },
                    blocking=False,
                )
                _LOGGER.debug("Advanced to artwork: %s", artwork_id)
            except Exception as exc:
                _LOGGER.error("Error advancing to next artwork: %s", exc)
        else:
            _LOGGER.debug("Artwork has no content_id or id: %s", next_artwork)

    async def _load_artworks(self) -> None:
        """Load artworks from TV and external providers."""
        all_artworks = []

        # Load TV artworks
        if self._ws and hasattr(self._ws, 'get_content_list'):
            try:
                # First call triggers the request, returns empty list
                tv_artworks = await self.hass.async_add_executor_job(
                    self._ws.get_content_list, self._category
                )

                # If empty, wait for cache to populate and try again
                if not tv_artworks:
                    _LOGGER.debug("Waiting for TV artwork list to be cached...")
                    await asyncio.sleep(1)  # Wait 1 second for TV response
                    tv_artworks = await self.hass.async_add_executor_job(
                        self._ws.get_content_list, self._category
                    )

                if tv_artworks:
                    all_artworks.extend(tv_artworks)
                    _LOGGER.info("Loaded %d artworks from TV (category %d)", len(tv_artworks), self._category)
                else:
                    _LOGGER.warning("No TV artworks found for category %d", self._category)
            except Exception as exc:
                _LOGGER.warning("Failed to load TV artworks: %s", exc)

        # Load external provider artworks
        provider_registry = self.hass.data[DOMAIN].get(self._entry_id, {}).get("provider_registry")
        if provider_registry:
            try:
                provider_artworks = await provider_registry.async_load_all_artworks()
                for provider_name, artworks in provider_artworks.items():
                    if artworks:
                        # Note: External artworks will be filtered out below since they need upload
                        all_artworks.extend(artworks)
                        _LOGGER.info("Loaded %d artworks from %s", len(artworks), provider_name)
            except Exception as exc:
                _LOGGER.warning("Failed to load provider artworks: %s", exc)

        # Separate TV artworks from external artworks
        tv_artworks = [art for art in all_artworks if art.get("content_id")]
        external_artworks = [art for art in all_artworks if art.get("id") and not art.get("content_id")]

        # Set TV artworks immediately so they're available
        self._queue_manager.set_available_artworks(tv_artworks)
        _LOGGER.info("Set %d TV artworks as available", len(tv_artworks))

        # Upload external artworks to TV
        if external_artworks and self._ws and provider_registry:
            _LOGGER.info("Uploading %d external artworks to TV...", len(external_artworks))
            uploaded_count = 0

            for artwork in external_artworks:
                try:
                    artwork_id = artwork.get("id")
                    source = artwork.get("source")

                    if not artwork_id or not source:
                        _LOGGER.warning("Skipping artwork with missing id or source: %s", artwork)
                        continue

                    # Get provider
                    provider = provider_registry.get_provider_by_name(source)
                    if not provider:
                        _LOGGER.warning("Provider not found for %s: %s", artwork_id, source)
                        continue

                    # Download artwork data
                    _LOGGER.debug("Downloading artwork %s from %s", artwork_id, source)
                    image_data = await provider.async_get_artwork_data(artwork_id)

                    if not image_data:
                        _LOGGER.warning("Failed to download artwork data for %s", artwork_id)
                        continue

                    # Determine file type from URL or default to JPG
                    url = artwork.get("url", "")
                    if url.lower().endswith(".png"):
                        file_type = "PNG"
                    else:
                        file_type = "JPG"

                    # Upload to TV
                    _LOGGER.debug("Uploading %s (%d bytes) to TV", artwork_id, len(image_data))
                    content_id = await self.hass.async_add_executor_job(
                        self._ws.upload_artwork,
                        image_data,
                        file_type,
                        None,  # matte
                        None,  # portrait_matte
                        None,  # image_date
                        30     # timeout
                    )

                    if content_id:
                        # Create new artwork dict with TV content_id
                        uploaded_artwork = artwork.copy()
                        uploaded_artwork["content_id"] = content_id
                        uploaded_artwork["original_id"] = artwork_id
                        tv_artworks.append(uploaded_artwork)

                        # Add to available artworks immediately so it can be used
                        self._queue_manager.set_available_artworks(tv_artworks)

                        uploaded_count += 1
                        _LOGGER.debug("Successfully uploaded %s as %s (total: %d)",
                                     artwork_id, content_id, len(tv_artworks))
                    else:
                        _LOGGER.warning("Upload returned no content_id for %s", artwork_id)

                except Exception as exc:
                    _LOGGER.warning("Failed to upload external artwork %s: %s", artwork.get("id"), exc)

            _LOGGER.info("Successfully uploaded %d/%d external artworks", uploaded_count, len(external_artworks))

        _LOGGER.info("Total available artworks for slideshow: %d", len(tv_artworks))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off slideshow."""
        if not self._ws or not hasattr(self._ws, 'set_auto_rotation_status'):
            _LOGGER.error("WebSocket API not available for slideshow control")
            return

        try:
            # Cancel timer
            if self._cancel_timer:
                self._cancel_timer()
                self._cancel_timer = None

            # Duration 0 turns off slideshow
            await self.hass.async_add_executor_job(
                self._ws.set_auto_rotation_status,
                0,
                self._queue_manager.shuffle,
                self._category
            )
            self._is_on = False
            _LOGGER.debug("Stopped slideshow")
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Error stopping slideshow: %s", exc)