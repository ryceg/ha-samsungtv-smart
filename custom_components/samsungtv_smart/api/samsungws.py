"""
Samsung TV WebSocket API wrapper using NickWaterton's samsung-tv-ws-api library.
This module provides a compatibility layer that matches the existing Home Assistant integration
interface while using the improved NickWaterton library under the hood.

Copyright (C) 2025
SPDX-License-Identifier: LGPL-3.0
"""

from __future__ import annotations

import sys
from pathlib import Path
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from enum import Enum
import aiohttp
import asyncio

# Add vendor library to path
_VENDOR_PATH = Path(__file__).parent.parent.parent.parent / 'vendor/samsung-tv-ws-api'
if str(_VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(_VENDOR_PATH))

# Import the NickWaterton library
from samsungtvws import SamsungTVWS as _SamsungTVWS
from samsungtvws.art import SamsungTVArt as _SamsungTVArt
from samsungtvws.rest import SamsungTVRest as _SamsungTVRest

_LOGGING = logging.getLogger(__name__)


class ArtModeStatus(Enum):
    """Define possible ArtMode status."""
    Unsupported = 0
    Unavailable = 1
    Off = 2
    On = 3


class ConnectionFailure(Exception):
    """Error during connection."""


class ResponseError(Exception):
    """Error in response."""


class HttpApiError(Exception):
    """Error using HTTP API."""


class App:
    """Define a TV Application."""

    def __init__(self, app_id: str, app_name: str, app_type: int):
        self.app_id = app_id
        self.app_name = app_name
        self.app_type = app_type


class SamsungTVAsyncRest:
    """Class that implements rest request in async."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        timeout: Optional[float] = None,
    ) -> None:
        """Initialize the class."""
        self._host = host
        self._session = session
        self._timeout = None if timeout == 0 else timeout
        self._rest = _SamsungTVRest(host=host, timeout=timeout)

    async def async_rest_device_info(self) -> Dict[str, Any]:
        """Get device info using rest api call."""
        _LOGGING.debug("Get device info via rest api")
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._rest.rest_device_info)

    async def async_rest_app_status(self, app_id: str) -> Dict[str, Any]:
        """Get app status using rest api call."""
        _LOGGING.debug("Get app %s status via rest api", app_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._rest.rest_app_status, app_id)

    async def async_rest_app_run(self, app_id: str) -> Dict[str, Any]:
        """Run an app using rest api call."""
        _LOGGING.debug("Run app %s via rest api", app_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._rest.rest_app_run, app_id)

    async def async_rest_app_close(self, app_id: str) -> Dict[str, Any]:
        """Close an app using rest api call."""
        _LOGGING.debug("Close app %s via rest api", app_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._rest.rest_app_close, app_id)

    async def async_rest_app_install(self, app_id: str) -> Dict[str, Any]:
        """Install a new app using rest api call."""
        _LOGGING.debug("Install app %s via rest api", app_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._rest.rest_app_install, app_id)


class SamsungTVWS:
    """Compatibility wrapper for NickWaterton's SamsungTVWS library."""

    def __init__(
        self,
        host: str,
        *,
        token: Optional[str] = None,
        token_file: Optional[str] = None,
        port: Optional[int] = 8001,
        timeout: Optional[int] = None,
        key_press_delay: Optional[float] = 1.0,
        name: Optional[str] = "SamsungTvRemote",
        app_list: Optional[dict] = None,
        ping_port: Optional[int] = 0,
    ):
        """Initialize SamsungTVWS wrapper."""
        self.host = host
        self.token = token
        self.token_file = token_file
        self.port = port or 8001
        self.timeout = None if timeout == 0 else timeout
        self.key_press_delay = 1.0 if key_press_delay is None else key_press_delay
        self.name = name or "SamsungTvRemote"
        self._app_list = dict(app_list) if app_list else None
        self._ping_port = ping_port or 0

        # Initialize the underlying library
        self._tv: Optional[_SamsungTVWS] = None
        self._art_api: Optional[_SamsungTVArt] = None
        self._rest_api: Optional[_SamsungTVRest] = None

        # Status tracking
        self._artmode_status = ArtModeStatus.Unsupported
        self._is_connected = False
        self._installed_app: Dict[str, App] = {}
        self._running_app: Optional[str] = None

    def _get_tv(self) -> _SamsungTVWS:
        """Get or create the underlying TV connection."""
        if self._tv is None:
            self._tv = _SamsungTVWS(
                host=self.host,
                token=self.token,
                token_file=self.token_file,
                port=self.port,
                timeout=self.timeout,
                key_press_delay=self.key_press_delay,
                name=self.name,
            )
        return self._tv

    def _get_rest_api(self) -> _SamsungTVRest:
        """Get or create the REST API client."""
        if self._rest_api is None:
            self._rest_api = _SamsungTVRest(
                host=self.host,
                port=self.port,
                timeout=self.timeout
            )
        return self._rest_api

    def _run_async_art_operation(self, operation_func):
        """Helper to run async art operations with proper cleanup."""
        try:
            from .samsungws_async import SamsungTVWSAsync
            import asyncio

            async def _run_operation():
                async_tv = SamsungTVWSAsync(
                    host=self.host,
                    token=self.token,
                    port=self.port,
                    timeout=self.timeout,
                    name=self.name
                )
                try:
                    return await operation_func(async_tv)
                finally:
                    await async_tv.close()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_run_operation())
            finally:
                loop.close()
        except Exception as e:
            _LOGGING.debug("Async art operation failed: %s", e)
            return None

    @staticmethod
    def ping_probe(host: str) -> Optional[int]:
        """Try to ping device and return usable port."""
        # Use the REST API to test connectivity
        try:
            rest = _SamsungTVRest(host=host)
            device_info = rest.rest_device_info()
            if device_info:
                return 8001  # Standard port
        except Exception:
            pass
        return None

    @property
    def is_connected(self) -> bool:
        """Return if WS connection is open."""
        if self._tv:
            return self._tv.is_connected
        return self._is_connected

    @property
    def artmode_status(self) -> ArtModeStatus:
        """Return current art mode status."""
        if self._art_api is None:
            try:
                tv = self._get_tv()
                self._art_api = _SamsungTVArt(tv)

                if self._art_api.supported():
                    if self._art_api.get_artmode():
                        self._artmode_status = ArtModeStatus.On
                    else:
                        self._artmode_status = ArtModeStatus.Off
                else:
                    self._artmode_status = ArtModeStatus.Unsupported
            except Exception as e:
                _LOGGING.debug("Could not determine art mode status: %s", e)
                self._artmode_status = ArtModeStatus.Unavailable

        return self._artmode_status

    @property
    def installed_app(self) -> Dict[str, App]:
        """Return a list of installed apps."""
        if not self._installed_app:
            try:
                tv = self._get_tv()
                apps_data = tv.app_list()
                if apps_data:
                    for app_data in apps_data:
                        app_id = app_data.get("appId", "")
                        if app_id:
                            app = App(
                                app_id=app_id,
                                app_name=app_data.get("name", ""),
                                app_type=app_data.get("app_type", 2)
                            )
                            self._installed_app[app_id] = app
            except Exception as e:
                _LOGGING.debug("Could not get installed apps: %s", e)

        return self._installed_app

    @property
    def running_app(self) -> Optional[str]:
        """Return current running app."""
        return self._running_app

    def open(self):
        """Open a WS client connection with the TV."""
        try:
            tv = self._get_tv()
            tv.open()
            self._is_connected = True

            # Update token if we got a new one
            if tv.token and tv.token != self.token:
                self.token = tv.token

            return tv
        except Exception as e:
            self._is_connected = False
            # Convert library-specific exceptions to our exceptions
            if "ms.channel.unauthorized" in str(e):
                raise ConnectionFailure("Unauthorized - check TV authorization") from e
            raise ConnectionFailure(str(e)) from e

    def close(self):
        """Close WS connection."""
        if self._tv:
            self._tv.close()
        self._is_connected = False

    def send_key(self, key: str, key_press_delay: Optional[float] = None, cmd: str = "Click") -> bool:
        """Send a key to the TV using WebSocket connection."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            tv.send_key(key, times=1, key_press_delay=key_press_delay, cmd=cmd)
            return True
        except Exception as e:
            _LOGGING.warning("Failed to send key %s: %s", key, e)
            return False

    def hold_key(self, key: str, seconds: float) -> bool:
        """Send a key to the TV and keep it pressed for specific number of seconds."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            tv.hold_key(key, seconds)
            return True
        except Exception as e:
            _LOGGING.warning("Failed to hold key %s: %s", key, e)
            return False

    def send_text(self, text: str, send_delay: Optional[float] = None) -> bool:
        """Send a text string to the TV."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            tv.send_text(text)
            return True
        except Exception as e:
            _LOGGING.warning("Failed to send text %s: %s", text, e)
            return False

    def move_cursor(self, x: int, y: int, duration: int = 0):
        """Move the cursor in the TV to specific coordinate."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            tv.move_cursor(x, y, duration)
        except Exception as e:
            _LOGGING.warning("Failed to move cursor: %s", e)

    def run_app(self, app_id: str, action_type: str = "", meta_tag: str = "", *, use_remote: bool = False):
        """Launch an app using WebSocket channel."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            # Map action types
            if not action_type or action_type == "DEEP_LINK":
                app_type = "DEEP_LINK"
            else:
                app_type = "NATIVE_LAUNCH"

            tv.run_app(app_id, app_type, meta_tag)
            return True
        except Exception as e:
            _LOGGING.warning("Failed to run app %s: %s", app_id, e)
            return False

    def open_browser(self, url: str):
        """Launch the browser app on the TV."""
        try:
            tv = self._get_tv()
            if not tv.is_connected:
                tv.open()

            tv.open_browser(url)
            return True
        except Exception as e:
            _LOGGING.warning("Failed to open browser: %s", e)
            return False

    def rest_device_info(self) -> Optional[Dict[str, Any]]:
        """Get device info using rest api call."""
        try:
            rest_api = self._get_rest_api()
            return rest_api.rest_device_info()
        except Exception as e:
            _LOGGING.debug("Failed to get device info: %s", e)
            return None

    def rest_app_status(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Get app status using rest api call."""
        try:
            rest_api = self._get_rest_api()
            return rest_api.rest_app_status(app_id)
        except Exception as e:
            _LOGGING.debug("Failed to get app status: %s", e)
            return None

    def rest_app_run(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Run an app using rest api call."""
        try:
            rest_api = self._get_rest_api()
            return rest_api.rest_app_run(app_id)
        except Exception as e:
            _LOGGING.debug("Failed to run app via REST: %s", e)
            return None

    def rest_app_close(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Close an app using rest api call."""
        try:
            rest_api = self._get_rest_api()
            return rest_api.rest_app_close(app_id)
        except Exception as e:
            _LOGGING.debug("Failed to close app via REST: %s", e)
            return None

    def rest_app_install(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Install a new app using rest api call."""
        try:
            rest_api = self._get_rest_api()
            return rest_api.rest_app_install(app_id)
        except Exception as e:
            _LOGGING.debug("Failed to install app via REST: %s", e)
            return None

    # Art mode functionality using Nick's comprehensive API
    def get_current_artwork(self) -> Optional[Dict[str, Any]]:
        """Get current displayed artwork details."""
        return self._run_async_art_operation(lambda api: api.get_current())

    def get_available_artworks(self, category: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Get list of available artworks, optionally filtered by category."""
        return self._run_async_art_operation(
            lambda api: api.available(category=category)
        )

    def select_artwork(self, content_id: str, category: Optional[str] = None, show: bool = True) -> bool:
        """Select and display specific artwork."""
        return self._run_async_art_operation(
            lambda api: api.select_image(content_id, category=category, show=show)
        ) is not None

    def set_artmode(self, enabled: bool) -> bool:
        """Enable or disable art mode."""
        result = self._run_async_art_operation(
            lambda api: api.set_artmode(enabled)
        )
        if result is not None:
            self._artmode_status = ArtModeStatus.On if enabled else ArtModeStatus.Off
            return True
        return False

    # Advanced art mode features using properly structured async wrapper
    def get_artmode_settings(self, setting: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get art mode settings (brightness, color temperature, etc.)."""
        return self._run_async_art_operation(
            lambda async_tv: async_tv.get_artmode_settings(setting)
        )

    def set_art_brightness(self, brightness: int) -> bool:
        """Set art mode brightness (0-100)."""
        if not (0 <= brightness <= 100):
            _LOGGING.error("Brightness must be between 0 and 100")
            return False

        result = self._run_async_art_operation(
            lambda async_tv: async_tv.set_art_brightness(brightness)
        )
        return result or False

    def get_art_brightness(self) -> Optional[int]:
        """Get current art mode brightness."""
        return self._run_async_art_operation(
            lambda async_tv: async_tv.get_art_brightness()
        )

    def set_art_color_temperature(self, temperature: int) -> bool:
        """Set art mode color temperature."""
        result = self._run_async_art_operation(
            lambda async_tv: async_tv.set_art_color_temperature(temperature)
        )
        return result or False

    def get_art_color_temperature(self) -> Optional[int]:
        """Get current art mode color temperature."""
        return self._run_async_art_operation(
            lambda async_tv: async_tv.get_art_color_temperature()
        )

    def get_slideshow_status(self) -> Optional[Dict[str, Any]]:
        """Get current slideshow/auto-rotation status."""
        return self._run_async_art_operation(
            lambda async_tv: async_tv.get_slideshow_status()
        )

    def set_slideshow(self, enabled: bool, duration_minutes: Optional[int] = None, shuffle: bool = True, category: int = 2) -> bool:
        """Enable/disable slideshow with optional duration and settings."""
        duration = duration_minutes or 0 if enabled else 0
        return self._run_async_art_operation(
            lambda api: api.set_slideshow_status(duration, shuffle, category)
        ) is not None

    def get_auto_rotation_status(self) -> Optional[Dict[str, Any]]:
        """Get auto rotation status."""
        return self._run_async_art_operation(lambda api: api.get_auto_rotation_status())

    def set_auto_rotation(self, enabled: bool, duration_minutes: Optional[int] = None, shuffle: bool = True, category: int = 2) -> bool:
        """Enable/disable auto rotation with optional settings."""
        duration = duration_minutes or 0 if enabled else 0
        return self._run_async_art_operation(
            lambda api: api.set_auto_rotation_status(duration, shuffle, category)
        ) is not None

    def get_artwork_thumbnail(self, content_id: Union[str, List[str]]) -> Optional[Union[bytes, Dict[str, bytes]]]:
        """Download artwork thumbnail(s) using Samsung's binary protocol."""
        return self._run_async_art_operation(
            lambda api: api.get_thumbnail(content_id, as_dict=isinstance(content_id, list))
        )

    def upload_artwork(self, file_data: bytes, file_type: str = "png", matte: str = "shadowbox_polar") -> Optional[str]:
        """Upload artwork to Frame TV."""
        result = self._run_async_art_operation(
            lambda api: api.upload(file_data, matte=matte, file_type=file_type)
        )
        return result.get('content_id') if isinstance(result, dict) else result

    def set_artwork_favorite(self, content_id: str, favorite: bool = True) -> bool:
        """Set artwork as favorite or unfavorite."""
        return self._run_async_art_operation(
            lambda api: api.set_favourite(content_id, 'on' if favorite else 'off')
        ) is not None

    def delete_artwork(self, content_id: str) -> bool:
        """Delete artwork from Frame TV."""
        return self._run_async_art_operation(
            lambda api: api.delete(content_id)
        ) is not None

    def delete_artworks(self, content_ids: List[str]) -> bool:
        """Delete multiple artworks from Frame TV."""
        return self._run_async_art_operation(
            lambda api: api.delete_list(content_ids)
        ) is not None

    def get_api_version(self) -> Optional[str]:
        """Get art API version."""
        return self._run_async_art_operation(lambda api: api.get_api_version())

    def get_device_info(self) -> Optional[Dict[str, Any]]:
        """Get comprehensive device information."""
        return self._run_async_art_operation(lambda api: api.get_device_info())

    def get_matte_list(self, include_colour: bool = False) -> Optional[Union[List[Dict[str, Any]], tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]]:
        """Get available matte types and optionally colors."""
        return self._run_async_art_operation(lambda api: api.get_matte_list(include_colour=include_colour))

    def change_matte(self, content_id: str, matte_id: Optional[str] = None, portrait_matte: Optional[str] = None) -> bool:
        """Change the matte/frame for specific artwork."""
        return self._run_async_art_operation(
            lambda api: api.change_matte(content_id, matte_id=matte_id, portrait_matte=portrait_matte)
        ) is not None

    def get_photo_filter_list(self) -> Optional[List[Dict[str, Any]]]:
        """Get available photo filters."""
        return self._run_async_art_operation(lambda api: api.get_photo_filter_list())

    def set_photo_filter(self, content_id: str, filter_id: str) -> bool:
        """Apply photo filter to specific artwork."""
        return self._run_async_art_operation(
            lambda api: api.set_photo_filter(content_id, filter_id)
        ) is not None

    def art(self):
        """Return art mode interface for Frame TV functionality."""
        if not self._art_api:
            tv = self._get_tv()
            self._art_api = _SamsungTVArt(tv)
        return self._art_api

    # Context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    # Compatibility methods for existing code
    def register_new_token_callback(self, func):
        """Register a callback function for new tokens."""
        # The NickWaterton library handles token management internally
        pass

    def register_status_callback(self, func):
        """Register callback function used on status change."""
        # Not implemented in wrapper - would need event handling
        pass

    def unregister_status_callback(self):
        """Unregister callback function used on status change."""
        # Not implemented in wrapper
        pass

    def start_poll(self):
        """Start polling the TV for status."""
        # Not implemented - NickWaterton library handles this differently
        pass

    def stop_poll(self):
        """Stop polling the TV for status."""
        # Not implemented - NickWaterton library handles this differently
        pass