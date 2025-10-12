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

    def set_ws_instance(self, ws_instance: any) -> None:
        """Set the websocket instance."""
        self._ws = ws_instance

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

        # Filter out recently shown artworks (check both content_id and id fields)
        available = [
            art for art in self._available_artworks
            if (art.get("content_id") or art.get("id")) not in self._recently_shown
        ]

        # If all artworks have been shown recently, reset and use full list
        if not available:
            _LOGGER.debug("All artworks shown recently, resetting recently_shown list")
            self._recently_shown.clear()
            available = self._available_artworks

        # Select random artwork
        artwork = random.choice(available)
        artwork_id = artwork.get("content_id") or artwork.get("id")
        self._recently_shown.append(artwork_id)

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
            artwork_id = next_artwork.get("content_id") or next_artwork.get("id")
            _LOGGER.debug("Selected random artwork: %s", artwork_id)
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
                if (art.get("content_id") or art.get("id")) not in self._recently_shown
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







