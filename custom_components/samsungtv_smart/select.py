"""Support for Samsung TV Art Mode select entities."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV art mode select entities."""

    @callback
    def _add_art_mode_selects(utc_now: datetime) -> None:
        """Create art mode select entities after media player is ready."""
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
            _LOGGER.debug("Media player entity not found for art mode select entities")
            return

        # Check if art mode is supported via media player attributes
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping select entity setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        # Create art mode select entities
        entities = [
            ArtMatteSelect(config, config_entry.entry_id, media_player_entity_id, ws_instance),
            ArtPhotoFilterSelect(config, config_entry.entry_id, media_player_entity_id, ws_instance),
        ]
        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode select entities for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_art_mode_selects)


class ArtModeSelectBase(SamsungTVEntity, SelectEntity):
    """Base class for art mode select entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the base art mode select entity."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._entry_id = entry_id

    def _get_ws_data(self, attr_name: str) -> Any:
        """Get data from WebSocket instance safely."""
        if not self._ws or not hasattr(self._ws, attr_name):
            return None
        return getattr(self._ws, attr_name, None)

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
                # Check if current artwork changed (which might affect matte/filter)
                artwork_data = new_state.attributes.get("current_artwork", {})
                if isinstance(artwork_data, dict):
                    # Update state when media player changes
                    self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False

        # Available if art mode is supported and currently on
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        art_mode_status = media_player_state.attributes.get("art_mode_status")

        return art_mode_supported and art_mode_status == "on" and self._ws is not None


class ArtMatteSelect(ArtModeSelectBase):
    """Select entity for Art Mode matte/frame style."""

    _attr_name = "Art mode matte"
    _attr_icon = "mdi:border-style"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the matte select entity."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{entry_id}_art_matte_select"
        self._current_content_id = None

    async def async_added_to_hass(self) -> None:
        """Trigger cache population when entity is added."""
        await super().async_added_to_hass()

        # Register callback to update state when cache is populated
        if self._ws and hasattr(self._ws, 'register_art_cache_callback'):
            def _on_cache_update():
                # Schedule state update in the event loop from the callback thread
                self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

            self._ws.register_art_cache_callback(_on_cache_update)

        # Trigger the request to populate cache (runs in executor since it's synchronous)
        if self._ws and hasattr(self._ws, 'get_matte_list'):
            await self.hass.async_add_executor_job(self._ws.get_matte_list, False)

    @property
    def options(self) -> list[str]:
        """Return list of available matte options."""
        if not self._ws or not hasattr(self._ws, '_matte_list_cache'):
            return ["none"]

        # Get matte list from WebSocket cache
        matte_cache = getattr(self._ws, '_matte_list_cache', None)
        if not matte_cache or not isinstance(matte_cache, list):
            return ["none"]

        # Extract matte IDs from cache
        matte_ids = []
        for matte_item in matte_cache:
            if isinstance(matte_item, dict):
                matte_id = matte_item.get('matte_type') or matte_item.get('matte_id')
                if matte_id and matte_id.lower() != 'none':
                    matte_ids.append(matte_id)

        if matte_ids:
            # Always include 'none' option at the start
            matte_ids.insert(0, 'none')
            return matte_ids

        return ["none"]

    @property
    def current_option(self) -> str | None:
        """Return the current matte selection."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        # Get current artwork info from media player
        artwork_data = media_player_state.attributes.get("current_artwork")
        if not artwork_data or not isinstance(artwork_data, dict):
            return None

        # Update cached content ID
        self._current_content_id = artwork_data.get("content_id")

        # Try different fields for matte ID
        for field in ["matte_id", "matte", "frame", "border_style"]:
            if field in artwork_data:
                matte_value = artwork_data[field]
                if matte_value:
                    return str(matte_value)

        return "none"

    async def async_select_option(self, option: str) -> None:
        """Change the selected matte."""
        if not self._ws or not hasattr(self._ws, 'change_matte'):
            _LOGGER.error("WebSocket API not available for changing matte")
            return

        if not self._current_content_id:
            # Try to get current content ID
            media_player_state = self.hass.states.get(self._media_player_entity_id)
            if media_player_state:
                artwork_data = media_player_state.attributes.get("current_artwork", {})
                if isinstance(artwork_data, dict):
                    self._current_content_id = artwork_data.get("content_id")

        if not self._current_content_id:
            _LOGGER.error("Cannot change matte: no current artwork content_id")
            return

        try:
            # Run in executor since WebSocket operation is synchronous
            await self.hass.async_add_executor_job(
                self._ws.change_matte,
                self._current_content_id,
                option if option != "none" else None
            )
            _LOGGER.debug("Changed matte to '%s' for artwork %s", option, self._current_content_id)

            # Request state update
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Error changing matte to '%s': %s", option, exc)


class ArtPhotoFilterSelect(ArtModeSelectBase):
    """Select entity for Art Mode photo filter."""

    _attr_name = "Art mode photo filter"
    _attr_icon = "mdi:image-filter"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the photo filter select entity."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{entry_id}_art_photo_filter_select"
        self._current_content_id = None

    async def async_added_to_hass(self) -> None:
        """Trigger cache population when entity is added."""
        await super().async_added_to_hass()

        # Register callback to update state when cache is populated
        if self._ws and hasattr(self._ws, 'register_art_cache_callback'):
            def _on_cache_update():
                # Schedule state update in the event loop from the callback thread
                self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

            self._ws.register_art_cache_callback(_on_cache_update)

        # Trigger the request to populate cache (runs in executor since it's synchronous)
        if self._ws and hasattr(self._ws, 'get_photo_filter_list'):
            await self.hass.async_add_executor_job(self._ws.get_photo_filter_list)

    @property
    def options(self) -> list[str]:
        """Return list of available filter options."""
        if not self._ws or not hasattr(self._ws, '_photo_filter_list_cache'):
            return ["none"]

        # Get filter list from WebSocket cache
        filter_cache = getattr(self._ws, '_photo_filter_list_cache', None)
        if not filter_cache or not isinstance(filter_cache, list):
            return ["none"]

        # Extract filter IDs from cache
        filter_ids = []
        for filter_item in filter_cache:
            if isinstance(filter_item, dict):
                filter_id = filter_item.get('filter_id') or filter_item.get('filter_name')
                if filter_id:
                    filter_ids.append(filter_id)

        if filter_ids:
            # Always include 'none' option if not already present
            if 'none' not in [f.lower() for f in filter_ids]:
                filter_ids.insert(0, 'none')
            return filter_ids

        return ["none"]

    @property
    def current_option(self) -> str | None:
        """Return the current filter selection."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        # Get current artwork info from media player
        artwork_data = media_player_state.attributes.get("current_artwork")
        if not artwork_data or not isinstance(artwork_data, dict):
            return None

        # Update cached content ID
        self._current_content_id = artwork_data.get("content_id")

        # Try different fields for filter ID
        for field in ["filter_id", "filter", "photo_filter"]:
            if field in artwork_data:
                filter_value = artwork_data[field]
                if filter_value:
                    return str(filter_value)

        return "none"

    async def async_select_option(self, option: str) -> None:
        """Change the selected photo filter."""
        if not self._ws or not hasattr(self._ws, 'set_photo_filter'):
            _LOGGER.error("WebSocket API not available for setting photo filter")
            return

        if not self._current_content_id:
            # Try to get current content ID
            media_player_state = self.hass.states.get(self._media_player_entity_id)
            if media_player_state:
                artwork_data = media_player_state.attributes.get("current_artwork", {})
                if isinstance(artwork_data, dict):
                    self._current_content_id = artwork_data.get("content_id")

        if not self._current_content_id:
            _LOGGER.error("Cannot change filter: no current artwork content_id")
            return

        try:
            # Run in executor since WebSocket operation is synchronous
            if option == "none":
                # Remove filter (if API supports it, otherwise skip)
                _LOGGER.debug("Removing filter not implemented, skipping")
                return

            await self.hass.async_add_executor_job(
                self._ws.set_photo_filter,
                self._current_content_id,
                option
            )
            _LOGGER.debug("Changed photo filter to '%s' for artwork %s", option, self._current_content_id)

            # Request state update
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Error changing photo filter to '%s': %s", option, exc)
