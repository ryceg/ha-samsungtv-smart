"""
Async Samsung TV WebSocket API wrapper using NickWaterton's samsung-tv-ws-api library.
This module provides proper async integration for Home Assistant without blocking calls.

Copyright (C) 2025
SPDX-License-Identifier: LGPL-3.0
"""

from __future__ import annotations

import sys
from pathlib import Path
import logging
from typing import Any, Dict, List, Optional, Union
import asyncio
import aiohttp

# Add vendor library to path
_VENDOR_PATH = Path(__file__).parent.parent.parent.parent / 'vendor/samsung-tv-ws-api'
if str(_VENDOR_PATH) not in sys.path:
    sys.path.insert(0, str(_VENDOR_PATH))

# Import the NickWaterton async library
from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.async_connection import SamsungTVWSAsyncConnection

_LOGGING = logging.getLogger(__name__)


class SamsungTVWSAsync:
    """Async Samsung TV WebSocket API wrapper using NickWaterton's library."""

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
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """Initialize async Samsung TV WebSocket wrapper."""
        self.host = host
        self.token = token
        self.token_file = token_file
        self.port = port or 8001
        self.timeout = None if timeout == 0 else timeout
        self.key_press_delay = 1.0 if key_press_delay is None else key_press_delay
        self.name = name or "SamsungTvRemote"
        self.session = session

        # Async API instances
        self._art_api: Optional[SamsungTVAsyncArt] = None
        self._rest_api: Optional[SamsungTVAsyncRest] = None
        self._remote_api: Optional[SamsungTVWSAsyncConnection] = None

        # Cached data
        self._device_info: Optional[Dict[str, Any]] = None
        self._art_mode_supported: Optional[bool] = None

    async def get_art_api(self) -> SamsungTVAsyncArt:
        """Get or create async art API instance."""
        if self._art_api is None:
            self._art_api = SamsungTVAsyncArt(
                host=self.host,
                token=self.token,
                token_file=self.token_file,
                port=self.port,
                timeout=self.timeout,
                name=self.name
            )
        return self._art_api

    async def get_rest_api(self) -> SamsungTVAsyncRest:
        """Get or create async REST API instance."""
        if self._rest_api is None:
            if self.session is None:
                raise ValueError("Session required for REST API")
            self._rest_api = SamsungTVAsyncRest(
                host=self.host,
                port=self.port,
                session=self.session
            )
        return self._rest_api

    async def get_device_info(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Get device information via REST API."""
        if self._device_info is None or force_refresh:
            try:
                rest_api = await self.get_rest_api()
                self._device_info = await rest_api.rest_device_info()
            except Exception as e:
                _LOGGING.debug("Failed to get device info: %s", e)
                return None
        return self._device_info

    async def is_art_mode_supported(self) -> bool:
        """Check if TV supports art mode (Frame TV)."""
        if self._art_mode_supported is None:
            try:
                art_api = await self.get_art_api()
                self._art_mode_supported = await art_api.supported()
            except Exception as e:
                _LOGGING.debug("Failed to check art mode support: %s", e)
                self._art_mode_supported = False
        return self._art_mode_supported

    async def is_tv_on(self) -> bool:
        """Check if TV is powered on."""
        try:
            device_info = await self.get_device_info()
            if device_info:
                return device_info.get("device", {}).get("PowerState", "off") == "on"
            return False
        except Exception as e:
            _LOGGING.debug("Failed to check TV power state: %s", e)
            return False

    # Art Mode Status and Control
    async def get_art_mode_status(self) -> str:
        """Get current art mode status."""
        if not await self.is_art_mode_supported():
            return "unsupported"

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                status = await art_api.get_artmode()
                return status
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get art mode status: %s", e)
            return "unavailable"

    async def set_art_mode(self, enabled: bool) -> bool:
        """Enable or disable art mode."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.set_artmode("on" if enabled else "off")
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set art mode: %s", e)
            return False

    # Artwork Management
    async def get_current_artwork(self) -> Optional[Dict[str, Any]]:
        """Get currently displayed artwork."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_current()
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get current artwork: %s", e)
            return None

    async def get_available_artworks(self, category: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Get list of available artworks, optionally filtered by category."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.available(category)
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get available artworks: %s", e)
            return None

    async def select_artwork(self, content_id: str, category: Optional[str] = None, show: bool = True) -> bool:
        """Select and display specific artwork."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.select_image(content_id, category, show)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to select artwork: %s", e)
            return False

    # Art Settings
    async def get_art_brightness(self) -> Optional[int]:
        """Get current art mode brightness."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                result = await art_api.get_brightness()
                if isinstance(result, dict):
                    return result.get('value')
                return result
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get art brightness: %s", e)
            return None

    async def set_art_brightness(self, brightness: int) -> bool:
        """Set art mode brightness (0-100)."""
        if not await self.is_art_mode_supported():
            return False

        if not (0 <= brightness <= 100):
            _LOGGING.error("Brightness must be between 0 and 100")
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.set_brightness(brightness)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set art brightness: %s", e)
            return False

    async def get_art_color_temperature(self) -> Optional[int]:
        """Get current art mode color temperature."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                result = await art_api.get_color_temperature()
                if isinstance(result, dict):
                    return result.get('value')
                return result
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get art color temperature: %s", e)
            return None

    async def set_art_color_temperature(self, temperature: int) -> bool:
        """Set art mode color temperature."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.set_color_temperature(temperature)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set art color temperature: %s", e)
            return False

    # Slideshow and Auto Rotation
    async def get_slideshow_status(self) -> Optional[Dict[str, Any]]:
        """Get current slideshow status."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_slideshow_status()
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow status: %s", e)
            return None

    async def set_slideshow(self, enabled: bool, duration_minutes: Optional[int] = None,
                           shuffle: bool = True, category: int = 2) -> bool:
        """Configure slideshow settings."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                duration = duration_minutes or 0 if enabled else 0
                await art_api.set_slideshow_status(duration, shuffle, category)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set slideshow: %s", e)
            return False

    async def get_auto_rotation_status(self) -> Optional[Dict[str, Any]]:
        """Get auto rotation status."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_auto_rotation_status()
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get auto rotation status: %s", e)
            return None

    async def set_auto_rotation(self, enabled: bool, duration_minutes: Optional[int] = None,
                               shuffle: bool = True, category: int = 2) -> bool:
        """Configure auto rotation settings."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                duration = duration_minutes or 0 if enabled else 0
                await art_api.set_auto_rotation_status(duration, shuffle, category)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set auto rotation: %s", e)
            return False

    # Advanced Art Features
    async def upload_artwork(self, file_data: bytes, file_type: str = "png",
                            matte: str = "shadowbox_polar", portrait_matte: str = "shadowbox_polar") -> Optional[str]:
        """Upload artwork to Frame TV."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                result = await art_api.upload(file_data, matte, portrait_matte, file_type)
                return result
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to upload artwork: %s", e)
            return None

    async def delete_artwork(self, content_id: str) -> bool:
        """Delete artwork from Frame TV."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.delete(content_id)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to delete artwork: %s", e)
            return False

    async def set_artwork_favorite(self, content_id: str, favorite: bool = True) -> bool:
        """Set artwork as favorite or unfavorite."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.set_favourite(content_id, 'on' if favorite else 'off')
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set artwork favorite: %s", e)
            return False

    async def get_artwork_thumbnail(self, content_id: Union[str, List[str]]) -> Optional[Union[bytes, Dict[str, bytes]]]:
        """Download artwork thumbnail(s) using binary protocol."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_thumbnail(content_id, as_dict=isinstance(content_id, list))
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get artwork thumbnail: %s", e)
            return None

    # Visual Enhancement Features
    async def get_photo_filter_list(self) -> Optional[List[Dict[str, Any]]]:
        """Get list of available photo filters."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_photo_filter_list()
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get photo filter list: %s", e)
            return None

    async def set_photo_filter(self, content_id: str, filter_id: str) -> bool:
        """Apply photo filter to artwork."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.set_photo_filter(content_id, filter_id)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to set photo filter: %s", e)
            return False

    async def get_matte_list(self, include_colour: bool = False) -> Optional[Union[List[Dict[str, Any]], tuple]]:
        """Get list of available mattes."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_matte_list(include_colour)
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get matte list: %s", e)
            return None

    async def change_artwork_matte(self, content_id: str, matte_id: Optional[str] = None,
                                  portrait_matte: Optional[str] = None) -> bool:
        """Change artwork matte/frame."""
        if not await self.is_art_mode_supported():
            return False

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                await art_api.change_matte(content_id, matte_id, portrait_matte)
                return True
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to change artwork matte: %s", e)
            return False

    # Comprehensive Art Settings
    async def get_artmode_settings(self, setting: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get comprehensive art mode settings."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_artmode_settings(setting or '')
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get art mode settings: %s", e)
            return None

    async def get_art_api_version(self) -> Optional[str]:
        """Get art mode API version."""
        if not await self.is_art_mode_supported():
            return None

        try:
            art_api = await self.get_art_api()
            await art_api.start_listening()
            try:
                return await art_api.get_api_version()
            finally:
                await art_api.close()
        except Exception as e:
            _LOGGING.debug("Failed to get art API version: %s", e)
            return None

    # Cleanup
    async def close(self):
        """Close all connections."""
        if self._art_api:
            await self._art_api.close()
        if self._remote_api:
            await self._remote_api.close()
        # REST API cleanup is handled by the session