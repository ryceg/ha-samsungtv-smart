"""Support for Samsung TV Art Mode dynamic overlay switch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import os
import tempfile
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_OVERLAY_CALENDAR_ENTITIES,
    CONF_OVERLAY_ENABLED,
    CONF_OVERLAY_TODO_ENTITIES,
    CONF_OVERLAY_UPDATE_INTERVAL,
    CONF_OVERLAY_WEATHER_ENTITY,
    DATA_OPTIONS,
    DATA_WS,
    DEFAULT_OVERLAY_UPDATE_INTERVAL,
    DOMAIN,
)
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)


class OverlaySwitch(SamsungTVEntity, SwitchEntity):
    """Switch entity to control dynamic overlay on Frame TV."""

    _attr_has_entity_name = True
    _attr_name = "Art overlay"
    _attr_icon = "mdi:layers-triple-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
        ws_instance: Any,
        overlay_generator: Any,
    ) -> None:
        """Initialize the overlay switch."""
        self._entry_id = entry_id
        self._ws = ws_instance
        self._generator = overlay_generator
        self._hass = hass  # Store hass instance for use in _load_config

        # Initialize SamsungTVEntity
        SamsungTVEntity.__init__(self, config, entry_id)

        self._attr_unique_id = f"{entry_id}_overlay_switch"

        # State tracking
        self._is_on = False
        self._current_overlay_id: str | None = None
        self._last_update: datetime | None = None
        self._update_task = None
        self._cancel_timer = None

        # Configuration
        self._calendar_entities: list[str] = []
        self._weather_entity: str | None = None
        self._todo_entities: list[str] = []
        self._update_interval = DEFAULT_OVERLAY_UPDATE_INTERVAL

        # Load configuration from options
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from entry options."""
        options = self._hass.data[DOMAIN][self._entry_id].get(DATA_OPTIONS, {})

        self._calendar_entities = options.get(CONF_OVERLAY_CALENDAR_ENTITIES, [])
        self._weather_entity = options.get(CONF_OVERLAY_WEATHER_ENTITY)
        self._todo_entities = options.get(CONF_OVERLAY_TODO_ENTITIES, [])
        self._update_interval = options.get(
            CONF_OVERLAY_UPDATE_INTERVAL,
            DEFAULT_OVERLAY_UPDATE_INTERVAL,
        )

        _LOGGER.debug(
            "Loaded overlay config: calendars=%s, weather=%s, todos=%s, interval=%d",
            self._calendar_entities,
            self._weather_entity,
            self._todo_entities,
            self._update_interval,
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Restore previous state if it was on
        # For now, we'll start with it off
        self._is_on = False

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is being removed."""
        await super().async_will_remove_from_hass()

        # Cancel timer
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

        # Clean up current overlay
        if self._current_overlay_id:
            await self._delete_overlay(self._current_overlay_id)

    @property
    def is_on(self) -> bool:
        """Return true if overlay is enabled."""
        return self._is_on

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Check if WebSocket is available and art mode is supported
        if not self._ws:
            return False

        try:
            return self._ws.art_mode_supported()
        except Exception:
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {
            "calendar_entities": self._calendar_entities,
            "weather_entity": self._weather_entity,
            "todo_entities": self._todo_entities,
            "update_interval": self._update_interval,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "current_overlay_id": self._current_overlay_id,
        }

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the overlay."""
        _LOGGER.info("Turning on overlay for %s", self.name)

        self._is_on = True
        self.async_write_ha_state()

        # Generate and display initial overlay
        await self._refresh_overlay()

        # Set up periodic updates
        self._start_update_timer()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the overlay."""
        _LOGGER.info("Turning off overlay for %s", self.name)

        self._is_on = False
        self.async_write_ha_state()

        # Cancel timer
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

        # Clear current overlay
        await self.async_clear_overlay()

    def _start_update_timer(self) -> None:
        """Start the periodic update timer."""
        if self._cancel_timer:
            self._cancel_timer()

        interval = timedelta(seconds=self._update_interval)

        self._cancel_timer = async_track_time_interval(
            self.hass,
            self._periodic_update,
            interval,
        )

        _LOGGER.debug("Started overlay update timer with %d second interval", self._update_interval)

    @callback
    def _periodic_update(self, now: datetime) -> None:
        """Handle periodic overlay update."""
        _LOGGER.debug("Periodic overlay update triggered")

        if self._is_on:
            # Schedule the update as a task
            self.hass.async_create_task(self._refresh_overlay())

    async def _delete_overlay(self, overlay_id: str) -> None:
        """Delete an overlay image from the TV."""
        if not self._ws or not overlay_id:
            return

        try:
            await self.hass.async_add_executor_job(
                self._ws.delete_artwork,
                overlay_id,
            )
            _LOGGER.debug("Deleted overlay image: %s", overlay_id)
        except Exception as exc:
            _LOGGER.warning("Failed to delete overlay %s: %s", overlay_id, exc)

    async def _refresh_overlay(self) -> None:
        """Generate and display a new overlay."""
        if not self._ws:
            _LOGGER.error("WebSocket not available for overlay update")
            return

        if not self._ws.art_mode_supported():
            _LOGGER.error("Art mode not supported, cannot display overlay")
            return

        try:
            _LOGGER.debug("Generating overlay image...")

            # Get current artwork to use as base from the image entity
            base_image_data = None
            try:
                # Find the current artwork image entity using the entity registry
                from homeassistant.helpers import entity_registry as er
                from homeassistant.components.image import async_get_image

                entity_reg = er.async_get(self._hass)

                # Look for the current artwork image entity
                unique_id = f"{self._entry_id}_current_artwork_image"
                _LOGGER.info("Looking for image entity with unique_id: %s", unique_id)

                image_entity = entity_reg.async_get_entity_id("image", DOMAIN, unique_id)

                if image_entity:
                    _LOGGER.info("Found current artwork image entity: %s", image_entity)
                    try:
                        image_data = await async_get_image(self._hass, image_entity)
                        if image_data and image_data.content:
                            base_image_data = bytes(image_data.content)
                            _LOGGER.info("✓ Got base image from entity: %d bytes", len(base_image_data))
                        else:
                            _LOGGER.warning("Image entity returned no content")
                    except Exception as exc:
                        _LOGGER.error("Could not get image from entity %s: %s", image_entity, exc, exc_info=True)
                else:
                    _LOGGER.warning("Current artwork image entity not found with unique_id: %s", unique_id)
                    _LOGGER.info("Available image entities: %s", [
                        f"{e.entity_id} ({e.unique_id})"
                        for e in entity_reg.entities.values()
                        if e.domain == "image" and e.platform == DOMAIN
                    ])
            except Exception as exc:
                _LOGGER.error("Error fetching base image: %s", exc, exc_info=True)

            # Fetch entity data (async)
            calendar_events = []
            if self._calendar_entities:
                calendar_events = await self._generator._get_calendar_events(self._calendar_entities)

            weather_data = None
            if self._weather_entity:
                weather_data = await self._generator._get_weather_data(self._weather_entity)

            todo_items = []
            if self._todo_entities:
                todo_items = await self._generator._get_todo_items(self._todo_entities)

            # Generate overlay image (with or without base)
            # Run in executor since it does blocking I/O (image processing, font loading)
            overlay_data = await self._hass.async_add_executor_job(
                self._generator.generate_overlay_sync,
                calendar_events,
                weather_data,
                todo_items,
                base_image_data,
            )

            # Save to temporary file
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".png",
                prefix="overlay_",
                delete=False,
            ) as temp_file:
                temp_file.write(overlay_data)
                temp_path = temp_file.name

            try:
                _LOGGER.debug("Uploading overlay to TV...")

                # Delete previous overlay if it exists
                if self._current_overlay_id:
                    await self._delete_overlay(self._current_overlay_id)

                # Upload new overlay
                # The upload_artwork method returns the content_id
                content_id = await self.hass.async_add_executor_job(
                    self._ws.upload_artwork,
                    overlay_data,
                    "PNG",
                    "none",  # No matte for overlay
                )

                if content_id:
                    _LOGGER.info("Successfully uploaded overlay: %s", content_id)

                    # Store current overlay ID
                    self._current_overlay_id = content_id
                    self._last_update = dt_util.now()

                    # Display the overlay
                    await self.hass.async_add_executor_job(
                        self._ws.select_artwork,
                        content_id,
                        True,  # show=True
                    )

                    self.async_write_ha_state()
                else:
                    _LOGGER.error("Failed to upload overlay - no content_id returned")

            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except OSError as exc:
                    _LOGGER.debug("Failed to delete temp file %s: %s", temp_path, exc)

        except Exception as exc:
            _LOGGER.error("Error refreshing overlay: %s", exc, exc_info=True)

    async def async_clear_overlay(self) -> None:
        """Clear the current overlay from the TV."""
        if self._current_overlay_id:
            await self._delete_overlay(self._current_overlay_id)
            self._current_overlay_id = None
            self._last_update = None
            self.async_write_ha_state()

    async def async_configure_overlay(
        self,
        calendar_entities: list[str] | None = None,
        weather_entity: str | None = None,
        todo_entities: list[str] | None = None,
        update_interval: int | None = None,
    ) -> None:
        """Configure overlay entity sources."""
        if calendar_entities is not None:
            self._calendar_entities = calendar_entities

        if weather_entity is not None:
            self._weather_entity = weather_entity

        if todo_entities is not None:
            self._todo_entities = todo_entities

        if update_interval is not None:
            self._update_interval = update_interval

            # Restart timer with new interval if overlay is on
            if self._is_on:
                self._start_update_timer()

        # Save to options
        options = self._hass.data[DOMAIN][self._entry_id].get(DATA_OPTIONS, {}).copy()
        options[CONF_OVERLAY_CALENDAR_ENTITIES] = self._calendar_entities
        options[CONF_OVERLAY_WEATHER_ENTITY] = self._weather_entity
        options[CONF_OVERLAY_TODO_ENTITIES] = self._todo_entities
        options[CONF_OVERLAY_UPDATE_INTERVAL] = self._update_interval

        # Update config entry options
        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if entry:
            self._hass.config_entries.async_update_entry(entry, options=options)

        _LOGGER.info("Updated overlay configuration")
        self.async_write_ha_state()

        # Refresh overlay immediately if it's on
        if self._is_on:
            await self._refresh_overlay()

    async def async_service_overlay_configure(
        self,
        calendar_entities: str | None = None,
        weather_entity: str | None = None,
        todo_entities: str | None = None,
        update_interval: int | None = None,
    ) -> None:
        """Service call handler for overlay_configure."""
        # Parse comma-separated entity lists
        cal_list = None
        if calendar_entities:
            cal_list = [e.strip() for e in calendar_entities.split(",") if e.strip()]

        todo_list = None
        if todo_entities:
            todo_list = [e.strip() for e in todo_entities.split(",") if e.strip()]

        await self.async_configure_overlay(
            calendar_entities=cal_list,
            weather_entity=weather_entity,
            todo_entities=todo_list,
            update_interval=update_interval,
        )

    async def async_service_overlay_refresh(self) -> None:
        """Service call handler for overlay_refresh."""
        if not self._is_on:
            _LOGGER.warning("Overlay is off, cannot refresh")
            return

        await self._refresh_overlay()

    async def async_service_overlay_clear(self) -> None:
        """Service call handler for overlay_clear."""
        await self.async_clear_overlay()

