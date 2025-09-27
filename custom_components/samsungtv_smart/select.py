"""Select entities for Samsung TV Smart integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_CFG, DOMAIN
from .sensors.base import SamsungTVArtSensorBase

_LOGGING = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung TV Select entities based on a config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]

    entities = []

    # Only add art-related select entities if Frame TV is supported
    # Check if we have WebSocket configuration
    host = config.get("host")
    if host:
        # Check if art mode is supported before adding entities
        try:
            from .api.samsungws import SamsungTVWS
            temp_ws = SamsungTVWS(
                host=host,
                port=config.get("port", 8002),
                token=config.get("token"),
                name=config.get("ws_name", "SamsungTvRemote"),
            )
            if temp_ws.art().supported():
                entities.extend([
                    SamsungTVCurrentArtworkSelect(config, entry.entry_id, hass),
                    SamsungTVSlideshowTypeSelect(config, entry.entry_id, hass),
                    SamsungTVSlideshowCategorySelect(config, entry.entry_id, hass),
                    SamsungTVArtworkFilterSelect(config, entry.entry_id, hass),
                    SamsungTVArtworkMatteSelect(config, entry.entry_id, hass),
                ])
            temp_ws.close()
        except Exception as e:
            _LOGGING.debug("Failed to check art mode support: %s", e)

    if entities:
        async_add_entities(entities, True)


class SamsungTVArtSelectBase(SamsungTVArtSensorBase, SelectEntity):
    """Base class for Samsung TV art mode select entities."""

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the select entity."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.art_mode_supported


class SamsungTVCurrentArtworkSelect(SamsungTVArtSelectBase):
    """Select entity for choosing current artwork."""

    _attr_icon = "mdi:image-frame"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the current artwork select entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Current Artwork"
        self._attr_unique_id = f"{self.unique_id}_current_artwork_select"
        self._attr_options = []

    @property
    def current_option(self) -> str | None:
        """Return the current artwork."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            current = self._ws.get_current_artwork()
            if current:
                return current.get("content_id") or current.get("title", "Unknown")
            return None
        except Exception as e:
            _LOGGING.debug("Failed to get current artwork: %s", e)
            return None

    @property
    def options(self) -> list[str]:
        """Return available artwork options."""
        if not self._ws or not self.art_mode_supported:
            return []

        try:
            artworks = self._ws.get_available_artworks()
            if artworks:
                options = []
                for artwork in artworks:
                    title = artwork.get("title", "Unknown")
                    content_id = artwork.get("content_id", "")
                    # Use title for display, but we'll need to map back to content_id
                    if title and title not in options:
                        options.append(title)
                return sorted(options)
            return []
        except Exception as e:
            _LOGGING.debug("Failed to get available artworks: %s", e)
            return []

    async def async_select_option(self, option: str) -> None:
        """Select artwork option."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Find the artwork with matching title
            artworks = await self.hass.async_add_executor_job(self._ws.get_available_artworks)
            if artworks:
                for artwork in artworks:
                    if artwork.get("title") == option:
                        content_id = artwork.get("content_id")
                        if content_id:
                            success = await self.hass.async_add_executor_job(
                                self._ws.select_artwork, content_id
                            )
                            if success:
                                self.async_write_ha_state()
                            break
        except Exception as e:
            _LOGGING.error("Failed to select artwork: %s", e)


class SamsungTVSlideshowTypeSelect(SamsungTVArtSelectBase):
    """Select entity for slideshow type."""

    _attr_icon = "mdi:slideshow"
    _attr_options = ["slideshow", "shuffleslideshow"]

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the slideshow type select entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Slideshow Type"
        self._attr_unique_id = f"{self.unique_id}_slideshow_type_select"

    @property
    def current_option(self) -> str | None:
        """Return the current slideshow type."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow and slideshow.get("value") != "off":
                # Map type boolean to string
                slideshow_type = slideshow.get("type", "slideshow")
                return "shuffleslideshow" if slideshow_type else "slideshow"
            return "slideshow"
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow type: %s", e)
            return None

    async def async_select_option(self, option: str) -> None:
        """Select slideshow type option."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Get current settings
            slideshow = await self.hass.async_add_executor_job(self._ws.get_slideshow_status)
            current_duration = 10  # Default duration
            current_category = 2   # Default to My Pictures

            if slideshow and slideshow.get("value") != "off":
                duration_str = slideshow.get("value", "10")
                if isinstance(duration_str, str) and duration_str.isdigit():
                    current_duration = int(duration_str)
                current_category = slideshow.get("category_id", 2)

            # Set slideshow with new type
            shuffle = option == "shuffleslideshow"
            success = await self.hass.async_add_executor_job(
                self._ws.set_slideshow,
                True,  # enabled
                current_duration,
                shuffle,
                current_category
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set slideshow type: %s", e)


class SamsungTVSlideshowCategorySelect(SamsungTVArtSelectBase):
    """Select entity for slideshow category."""

    _attr_icon = "mdi:folder-image"
    _attr_options = ["My Pictures", "Favorites", "Store"]

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the slideshow category select entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Slideshow Category"
        self._attr_unique_id = f"{self.unique_id}_slideshow_category_select"

    @property
    def current_option(self) -> str | None:
        """Return the current slideshow category."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow and slideshow.get("value") != "off":
                category_id = slideshow.get("category_id", 2)
                # Map category ID to friendly name
                category_map = {2: "My Pictures", 4: "Favorites", 8: "Store"}
                return category_map.get(category_id, "My Pictures")
            return "My Pictures"
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow category: %s", e)
            return None

    async def async_select_option(self, option: str) -> None:
        """Select slideshow category option."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Map friendly name to category ID
            category_map = {"My Pictures": 2, "Favorites": 4, "Store": 8}
            category_id = category_map.get(option, 2)

            # Get current settings
            slideshow = await self.hass.async_add_executor_job(self._ws.get_slideshow_status)
            current_duration = 10  # Default duration
            current_shuffle = True  # Default shuffle

            if slideshow and slideshow.get("value") != "off":
                duration_str = slideshow.get("value", "10")
                if isinstance(duration_str, str) and duration_str.isdigit():
                    current_duration = int(duration_str)
                current_shuffle = slideshow.get("type", True)

            # Set slideshow with new category
            success = await self.hass.async_add_executor_job(
                self._ws.set_slideshow,
                True,  # enabled
                current_duration,
                current_shuffle,
                category_id
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set slideshow category: %s", e)


class SamsungTVArtworkFilterSelect(SamsungTVArtSelectBase):
    """Select entity for artwork photo filters."""

    _attr_icon = "mdi:filter"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the artwork filter select entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Artwork Filter"
        self._attr_unique_id = f"{self.unique_id}_artwork_filter_select"
        self._attr_options = []

    @property
    def current_option(self) -> str | None:
        """Return the current filter."""
        # There's no direct API to get current filter, so return None
        return None

    @property
    def options(self) -> list[str]:
        """Return available filter options."""
        if not self._ws or not self.art_mode_supported:
            return []

        try:
            filters = self._ws.get_photo_filter_list()
            if filters:
                options = []
                for filter_item in filters:
                    filter_name = filter_item.get("filter_name", "Unknown")
                    if filter_name and filter_name not in options:
                        options.append(filter_name)
                return sorted(options)
            return []
        except Exception as e:
            _LOGGING.debug("Failed to get photo filters: %s", e)
            return []

    async def async_select_option(self, option: str) -> None:
        """Apply photo filter to current artwork."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Get current artwork
            current = await self.hass.async_add_executor_job(self._ws.get_current_artwork)
            if not current:
                _LOGGING.warning("No current artwork to apply filter to")
                return

            content_id = current.get("content_id")
            if not content_id:
                _LOGGING.warning("Current artwork has no content ID")
                return

            # Find the filter with matching name
            filters = await self.hass.async_add_executor_job(self._ws.get_photo_filter_list)
            if filters:
                for filter_item in filters:
                    if filter_item.get("filter_name") == option:
                        filter_id = filter_item.get("filter_id")
                        if filter_id:
                            success = await self.hass.async_add_executor_job(
                                self._ws.set_photo_filter, content_id, filter_id
                            )
                            if success:
                                self.async_write_ha_state()
                            break
        except Exception as e:
            _LOGGING.error("Failed to apply photo filter: %s", e)


class SamsungTVArtworkMatteSelect(SamsungTVArtSelectBase):
    """Select entity for artwork matte/frame."""

    _attr_icon = "mdi:border-outside"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the artwork matte select entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Artwork Matte"
        self._attr_unique_id = f"{self.unique_id}_artwork_matte_select"
        self._attr_options = []

    @property
    def current_option(self) -> str | None:
        """Return the current matte."""
        # There's no direct API to get current matte, so return None
        return None

    @property
    def options(self) -> list[str]:
        """Return available matte options."""
        if not self._ws or not self.art_mode_supported:
            return []

        try:
            mattes = self._ws.get_matte_list(include_colour=False)
            if mattes:
                options = ["none"]  # Always include "none" option
                for matte_item in mattes:
                    matte_type = matte_item.get("matte_type", "Unknown")
                    if matte_type and matte_type not in options:
                        options.append(matte_type)
                return sorted(options)
            return ["none"]
        except Exception as e:
            _LOGGING.debug("Failed to get matte list: %s", e)
            return ["none"]

    async def async_select_option(self, option: str) -> None:
        """Change matte for current artwork."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Get current artwork
            current = await self.hass.async_add_executor_job(self._ws.get_current_artwork)
            if not current:
                _LOGGING.warning("No current artwork to change matte for")
                return

            content_id = current.get("content_id")
            if not content_id:
                _LOGGING.warning("Current artwork has no content ID")
                return

            # Change matte
            matte_id = option if option != "none" else None
            success = await self.hass.async_add_executor_job(
                self._ws.change_matte, content_id, matte_id
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to change artwork matte: %s", e)