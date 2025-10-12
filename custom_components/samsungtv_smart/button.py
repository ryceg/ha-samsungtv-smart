"""Support for Samsung TV Art Mode buttons."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity
from .slideshow import SlideshowQueueManager


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV button entities."""

    @callback
    def _add_entities(utc_now: datetime) -> None:
        """Create entities."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)
        queue_manager = hass.data[DOMAIN][config_entry.entry_id].get("slideshow_queue")

        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id or not queue_manager:
            _LOGGER.debug("Media player or queue manager not found for button entities")
            return

        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping button entity setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        entities = [
            SlideshowNextButton(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
            SlideshowPreviousButton(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager),
        ]
        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode button entities for %s",
            config.get(CONF_HOST, "unknown")
        )

    async_call_later(hass, 10, _add_entities)


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

        # TV artworks use 'content_id', external providers use 'id'
        artwork_id = next_artwork.get("content_id") or next_artwork.get("id")
        if artwork_id:
            try:
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
            except Exception as exc:
                _LOGGER.error("Error advancing to next artwork: %s", exc)
        else:
            _LOGGER.debug("Artwork has no content_id or id: %s", next_artwork)


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

        # TV artworks use 'content_id', external providers use 'id'
        artwork_id = prev_artwork.get("content_id") or prev_artwork.get("id")
        if artwork_id:
            try:
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
            except Exception as exc:
                _LOGGER.error("Error going to previous artwork: %s", exc)