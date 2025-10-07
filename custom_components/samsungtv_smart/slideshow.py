"""Support for Samsung TV Art Mode Slideshow with queue management."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
import random
import re
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.image import ImageEntity
from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.number import NumberEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, UnitOfTime
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er, service
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)

# Default text overlay patterns
DEFAULT_OVERLAY_PATTERNS = [
    r".*_overlay\.(jpg|jpeg|png)$",
    r"^text_.*\.(jpg|jpeg|png)$",
    r"^overlay_.*\.(jpg|jpeg|png)$",
]

# Slideshow categories
CATEGORY_MY_PICTURES = 2
CATEGORY_FAVORITES = 4
CATEGORY_STORE_ART = 8


class SlideshowQueueManager:
    """Manage slideshow queue with history and overlay support."""

    def __init__(
        self,
        shuffle: bool = True,
        overlay_patterns: list[str] | None = None,
        ws_instance=None,
    ):
        """Initialize queue manager."""
        self._queue: deque = deque()
        self._history: deque = deque(maxlen=50)  # Keep last 50 items
        self._shuffle = shuffle
        self._overlay_patterns = overlay_patterns or DEFAULT_OVERLAY_PATTERNS
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self._overlay_patterns]
        self._current_index = -1
        self._pending_overlay: dict | None = None
        self._ws = ws_instance
        self._available_artworks: list[dict] = []
        self._category = CATEGORY_MY_PICTURES  # Default category
        self._auto_random = True  # Auto-select random artwork when queue is empty
        self._recently_shown: deque = deque(maxlen=20)  # Track recently shown to avoid repeats

    def is_overlay_image(self, content_id: str) -> bool:
        """Check if content_id matches overlay patterns."""
        for pattern in self._compiled_patterns:
            if pattern.match(content_id):
                return True
        return False

    def add_to_queue(self, artwork: dict) -> None:
        """Add artwork to the queue."""
        if not artwork or not artwork.get("content_id"):
            return

        # Check if already in queue
        content_id = artwork["content_id"]
        if any(item.get("content_id") == content_id for item in self._queue):
            _LOGGER.debug("Artwork %s already in queue, skipping", content_id)
            return

        self._queue.append(artwork)
        _LOGGER.debug("Added artwork %s to queue (size: %d)", content_id, len(self._queue))

    def remove_from_queue(self, content_id: str) -> bool:
        """Remove artwork from queue by content_id."""
        for i, item in enumerate(self._queue):
            if item.get("content_id") == content_id:
                del self._queue[i]
                _LOGGER.debug("Removed artwork %s from queue", content_id)
                return True
        return False

    def set_queue(self, artworks: list[dict]) -> None:
        """Replace entire queue with new list."""
        self._queue.clear()
        for artwork in artworks:
            if artwork and artwork.get("content_id"):
                self._queue.append(artwork)

        if self._shuffle:
            self._shuffle_queue()

        self._current_index = -1
        _LOGGER.debug("Queue set with %d items", len(self._queue))

    def _shuffle_queue(self) -> None:
        """Shuffle the queue in place."""
        queue_list = list(self._queue)
        random.shuffle(queue_list)
        self._queue = deque(queue_list)

    def _get_random_artwork(self) -> dict | None:
        """Get a random artwork from available artworks, avoiding recently shown."""
        if not self._available_artworks:
            return None

        # Filter out recently shown artworks
        available = [
            art for art in self._available_artworks
            if art.get("content_id") not in self._recently_shown
        ]

        # If all artworks have been shown recently, reset and use full list
        if not available:
            _LOGGER.debug("All artworks shown recently, resetting recently_shown list")
            self._recently_shown.clear()
            available = self._available_artworks

        # Select random artwork
        artwork = random.choice(available)
        self._recently_shown.append(artwork.get("content_id"))

        return artwork

    def get_next(self) -> dict | None:
        """Get next artwork in queue or random if queue is empty."""
        # Check for pending overlay first
        if self._pending_overlay:
            overlay = self._pending_overlay
            self._pending_overlay = None
            _LOGGER.debug("Returning pending overlay: %s", overlay.get("content_id"))
            return overlay

        # If queue has items, use queue
        if self._queue:
            self._current_index = (self._current_index + 1) % len(self._queue)
            next_artwork = self._queue[self._current_index]
        # If auto-random is enabled and queue is empty, select random artwork
        elif self._auto_random:
            next_artwork = self._get_random_artwork()
            if not next_artwork:
                _LOGGER.warning("No available artworks for random selection")
                return None
            _LOGGER.debug("Selected random artwork: %s", next_artwork.get("content_id"))
        else:
            return None

        # Add to history
        self._history.append({
            "artwork": next_artwork,
            "timestamp": datetime.utcnow(),
        })

        return next_artwork

    def get_previous(self) -> dict | None:
        """Get previous artwork from history."""
        if len(self._history) < 2:
            return None

        # Remove current from history
        self._history.pop()

        # Get previous
        if self._history:
            prev_entry = self._history[-1]
            return prev_entry["artwork"]

        return None

    def peek_next(self) -> dict | None:
        """Peek at next artwork without advancing (preview of what will show next)."""
        if self._pending_overlay:
            return self._pending_overlay

        # If queue has items, peek at next in queue
        if self._queue:
            next_index = (self._current_index + 1) % len(self._queue)
            return self._queue[next_index]

        # If auto-random is enabled and queue is empty, preview a random selection
        if self._auto_random:
            # Don't actually consume the random selection, just preview one
            if not self._available_artworks:
                return None
            available = [
                art for art in self._available_artworks
                if art.get("content_id") not in self._recently_shown
            ]
            if not available:
                available = self._available_artworks
            return random.choice(available) if available else None

        return None

    def get_current(self) -> dict | None:
        """Get current artwork."""
        if self._history:
            return self._history[-1]["artwork"]
        return None

    def add_overlay(self, artwork: dict) -> None:
        """Add overlay to be displayed next, skipping normal queue."""
        if not artwork or not artwork.get("content_id"):
            return

        self._pending_overlay = artwork
        _LOGGER.debug("Added overlay %s to skip queue", artwork.get("content_id"))

    def clear(self) -> None:
        """Clear the queue and history."""
        self._queue.clear()
        self._history.clear()
        self._current_index = -1
        self._pending_overlay = None

    @property
    def queue_size(self) -> int:
        """Return current queue size."""
        return len(self._queue)

    @property
    def shuffle(self) -> bool:
        """Return shuffle mode."""
        return self._shuffle

    @shuffle.setter
    def shuffle(self, value: bool) -> None:
        """Set shuffle mode."""
        self._shuffle = value
        if value and self._queue:
            self._shuffle_queue()

    def set_available_artworks(self, artworks: list[dict]) -> None:
        """Set the list of available artworks for random selection."""
        self._available_artworks = artworks
        _LOGGER.debug("Set %d available artworks for random selection", len(artworks))

    def set_category(self, category: int) -> None:
        """Set the category for artwork selection."""
        self._category = category
        _LOGGER.debug("Set artwork category to %d", category)

    def set_auto_random(self, enabled: bool) -> None:
        """Enable or disable auto-random selection when queue is empty."""
        self._auto_random = enabled
        _LOGGER.debug("Auto-random selection %s", "enabled" if enabled else "disabled")

    @property
    def auto_random(self) -> bool:
        """Return if auto-random is enabled."""
        return self._auto_random

    @property
    def category(self) -> int:
        """Return current category."""
        return self._category

    @property
    def available_count(self) -> int:
        """Return count of available artworks."""
        return len(self._available_artworks)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV slideshow entities."""

    @callback
    def _add_slideshow_entities(utc_now: datetime) -> None:
        """Create slideshow entities after media player is ready."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)

        # Find the media player entity for this TV using entity registry
        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id:
            _LOGGER.debug("Media player entity not found for slideshow entities")
            return

        # Check if art mode is supported via media player attributes
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping slideshow entity setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        # Create queue manager with ws_instance for artwork fetching
        queue_manager = SlideshowQueueManager(ws_instance=ws_instance)

        # Create slideshow entities
        entities = [
            SlideshowSwitch(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            SlideshowIntervalNumber(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            SlideshowNextButton(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            SlideshowPreviousButton(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            SlideshowCurrentImage(config, config_entry.entry_id, media_player_entity_id, queue_manager),
        ]
        async_add_entities(entities, True)

        # Store queue manager for service calls
        hass.data[DOMAIN][config_entry.entry_id]["slideshow_queue"] = queue_manager

        _LOGGER.debug(
            "Successfully set up slideshow entities for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_slideshow_entities)


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

        # If it's a TV artwork, select it
        if next_artwork.get("content_id"):
            try:
                # Call the media player's select_artwork service
                await self.hass.services.async_call(
                    MP_DOMAIN,
                    "select_artwork",
                    {
                        "entity_id": self._media_player_entity_id,
                        "content_id": next_artwork["content_id"],
                        "show": True,
                    },
                    blocking=False,
                )
                _LOGGER.debug("Advanced to TV artwork: %s", next_artwork["content_id"])
            except Exception as exc:
                _LOGGER.error("Error advancing to next artwork: %s", exc)
        else:
            # External artwork - would need to be uploaded first
            _LOGGER.debug("External artwork not yet supported for auto-advance: %s", next_artwork.get("id"))

    async def _load_artworks(self) -> None:
        """Load artworks from TV and external providers."""
        all_artworks = []

        # Load TV artworks
        if self._ws and hasattr(self._ws, 'get_content_list'):
            try:
                tv_artworks = await self.hass.async_add_executor_job(
                    self._ws.get_content_list, self._category
                )
                if tv_artworks:
                    all_artworks.extend(tv_artworks)
                    _LOGGER.info("Loaded %d artworks from TV (category %d)", len(tv_artworks), self._category)
            except Exception as exc:
                _LOGGER.warning("Failed to load TV artworks: %s", exc)

        # Load external provider artworks
        provider_registry = self.hass.data[DOMAIN].get(self.entry_id, {}).get("provider_registry")
        if provider_registry:
            try:
                provider_artworks = await provider_registry.async_load_all_artworks()
                for provider_name, artworks in provider_artworks.items():
                    if artworks:
                        all_artworks.extend(artworks)
                        _LOGGER.info("Loaded %d artworks from %s", len(artworks), provider_name)
            except Exception as exc:
                _LOGGER.warning("Failed to load provider artworks: %s", exc)

        self._queue_manager.set_available_artworks(all_artworks)
        _LOGGER.info("Total available artworks: %d", len(all_artworks))

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


class SlideshowIntervalNumber(SamsungTVEntity, NumberEntity):
    """Number entity to control slideshow interval."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow interval"
    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = 60
    _attr_native_step = 1

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the interval number."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_interval"
        self._switch_entity_id = f"switch.{entry_id.replace('-', '_')}_slideshow"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    @property
    def native_value(self) -> float:
        """Return the current interval."""
        # Get from switch entity
        switch_state = self.hass.states.get(self._switch_entity_id)
        if switch_state:
            return switch_state.attributes.get("interval", 10)
        return 10

    async def async_set_native_value(self, value: float) -> None:
        """Set new interval value."""
        # Find and update the switch entity
        entity_reg = er.async_get(self.hass)
        switch_entry = entity_reg.async_get(self._switch_entity_id)

        if switch_entry:
            # Get the switch entity from platform
            switch_entities = self.hass.data.get("switch", {}).get("entities", [])
            for entity in switch_entities:
                if hasattr(entity, "entity_id") and entity.entity_id == self._switch_entity_id:
                    entity._duration = int(value)
                    # Restart timer if slideshow is on
                    if entity._is_on and hasattr(entity, "_start_slideshow_timer"):
                        entity._start_slideshow_timer()
                    entity.async_write_ha_state()
                    _LOGGER.debug("Updated slideshow interval to %d minutes", int(value))
                    break


class SlideshowNextButton(SamsungTVEntity, ButtonEntity):
    """Button to advance to next artwork."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow next"
    _attr_icon = "mdi:skip-next"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the next button."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_next"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    async def async_press(self) -> None:
        """Handle button press."""
        next_artwork = self._queue_manager.get_next()
        if not next_artwork:
            _LOGGER.debug("No next artwork available")
            return

        if next_artwork.get("content_id"):
            try:
                await self.hass.services.async_call(
                    MP_DOMAIN,
                    "select_artwork",
                    {
                        "entity_id": self._media_player_entity_id,
                        "content_id": next_artwork["content_id"],
                        "show": True,
                    },
                    blocking=False,
                )
            except Exception as exc:
                _LOGGER.error("Error advancing to next artwork: %s", exc)


class SlideshowPreviousButton(SamsungTVEntity, ButtonEntity):
    """Button to go to previous artwork."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow previous"
    _attr_icon = "mdi:skip-previous"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the previous button."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_previous"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    async def async_press(self) -> None:
        """Handle button press."""
        prev_artwork = self._queue_manager.get_previous()
        if not prev_artwork:
            _LOGGER.debug("No previous artwork available")
            return

        if prev_artwork.get("content_id"):
            try:
                await self.hass.services.async_call(
                    MP_DOMAIN,
                    "select_artwork",
                    {
                        "entity_id": self._media_player_entity_id,
                        "content_id": prev_artwork["content_id"],
                        "show": True,
                    },
                    blocking=False,
                )
            except Exception as exc:
                _LOGGER.error("Error going to previous artwork: %s", exc)



class SlideshowCurrentImage(SamsungTVEntity, ImageEntity):
    """Image entity showing current artwork."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow current"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the current image."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_current_image"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported

    async def async_image(self) -> bytes | None:
        """Return current artwork image."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        # Get current artwork thumbnail from media player
        entity_picture = media_player_state.attributes.get("entity_picture")
        if entity_picture:
            # Return URL that HA will fetch
            return None  # Image entity will use image_url instead

        return None

    @property
    def image_url(self) -> str | None:
        """Return URL of current artwork."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if media_player_state:
            return media_player_state.attributes.get("entity_picture")
        return None


