"""
Samsung TV Art Mode API for Home Assistant Integration

Adapted from Samsung TV WS API by Nick Waterton
Original Copyright (C) 2019 DSR! <xchwarze@gmail.com>
Original Copyright (C) 2021 Matthew Garrett <mjg59@srcf.ucam.org>
Original Copyright (C) 2024 Nick Waterton <n.waterton@outlook.com>

SPDX-License-Identifier: LGPL-3.0
"""

from datetime import datetime
import json
import logging
import random
import socket
import ssl
from typing import Any, Dict, List, Optional, Union
import uuid

import websocket

_LOGGING = logging.getLogger(__name__)

ART_ENDPOINT = "com.samsung.art-app"


class ArtModeError(Exception):
    """Exception for art mode operations."""
    pass


class ArtModeTimeoutError(ArtModeError):
    """Timeout error for art mode operations."""
    pass


class ArtModeResponseError(ArtModeError):
    """Response error for art mode operations."""
    pass


class SamsungTVArt:
    """Samsung TV Art Mode interface."""

    def __init__(self, host: str, port: int = 8001, timeout: int = 5):
        """Initialize art mode interface."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.art_uuid = str(uuid.uuid4())
        self._websocket: Optional[websocket.WebSocket] = None

    def _get_ssl_context(self):
        """Get SSL context for secure connections."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def _process_api_response(self, response: str) -> Dict[str, Any]:
        """Process API response from TV."""
        try:
            return json.loads(response)
        except json.JSONDecodeError as exc:
            _LOGGING.debug("Failed to parse response from TV: %s", response)
            raise ArtModeResponseError(f"Failed to parse response: {exc}")

    def _connect(self) -> bool:
        """Connect to TV art mode endpoint."""
        try:
            ws_url = f"wss://{self.host}:{self.port}/api/v2/channels/{ART_ENDPOINT}"
            self._websocket = websocket.create_connection(
                ws_url,
                timeout=self.timeout,
                sslopt={"cert_reqs": ssl.CERT_NONE}
            )

            # Wait for channel ready event
            data = self._websocket.recv()
            response = self._process_api_response(data)
            event = response.get("event", "*")

            if event != "ms.channel.ready":
                self._websocket.close()
                raise ArtModeError(f"Unexpected event: {event}")

            return True
        except Exception as exc:
            _LOGGING.error("Failed to connect to art mode: %s", exc)
            return False

    def _disconnect(self):
        """Disconnect from TV."""
        if self._websocket:
            try:
                self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    def _send_command(self, command: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send command to TV and get response."""
        if not self._websocket:
            if not self._connect():
                return None

        try:
            message = {
                "method": "ms.channel.emit",
                "params": {
                    "event": "art_app_request",
                    "to": "host",
                    "data": json.dumps(command)
                }
            }

            self._websocket.send(json.dumps(message))

            # Wait for response
            response_data = self._websocket.recv()
            response = self._process_api_response(response_data)

            if response.get("event") == "d2d_service_message":
                return json.loads(response.get("data", "{}"))

            return response

        except websocket.WebSocketTimeoutException:
            raise ArtModeTimeoutError("Timeout waiting for response")
        except Exception as exc:
            _LOGGING.error("Error sending art mode command: %s", exc)
            return None

    def get_uuid(self) -> str:
        """Generate new UUID."""
        self.art_uuid = str(uuid.uuid4())
        return self.art_uuid

    def supported(self) -> bool:
        """Check if TV supports art mode."""
        try:
            import requests
            response = requests.get(
                f"http://{self.host}:8001/api/v2/",
                timeout=self.timeout
            )
            data = response.json()
            return data.get("device", {}).get("FrameTVSupport") == "true"
        except Exception:
            return False

    def get_api_version(self) -> Optional[str]:
        """Get art mode API version."""
        try:
            response = self._send_command({"request": "api_version", "id": self.get_uuid()})
            if response:
                return response.get("version")
        except Exception:
            # Try old API
            try:
                response = self._send_command({"request": "get_api_version", "id": self.get_uuid()})
                if response:
                    return response.get("version")
            except Exception:
                pass
        return None

    def get_artmode_status(self) -> Optional[str]:
        """Get current art mode status."""
        try:
            response = self._send_command({
                "request": "get_artmode_status",
                "id": self.get_uuid()
            })
            if response:
                return response.get("value")
        except Exception as exc:
            _LOGGING.error("Error getting art mode status: %s", exc)
        return None

    def get_current_artwork(self) -> Optional[Dict[str, Any]]:
        """Get currently displayed artwork info."""
        try:
            response = self._send_command({
                "request": "get_current_artwork",
                "id": self.get_uuid()
            })
            return response
        except Exception as exc:
            _LOGGING.error("Error getting current artwork: %s", exc)
        return None

    def get_brightness(self) -> Optional[int]:
        """Get art mode brightness (0-100)."""
        try:
            response = self._send_command({
                "request": "get_artmode_settings",
                "id": self.get_uuid()
            })
            if response and "data" in response:
                settings = json.loads(response["data"])
                for setting in settings:
                    if setting.get("item") == "brightness":
                        return int(setting.get("value", 0))
        except Exception:
            # Try old API
            try:
                response = self._send_command({
                    "request": "get_brightness",
                    "id": self.get_uuid()
                })
                if response:
                    return int(response.get("value", 0))
            except Exception as exc:
                _LOGGING.error("Error getting brightness: %s", exc)
        return None

    def get_color_temperature(self) -> Optional[int]:
        """Get art mode color temperature."""
        try:
            response = self._send_command({
                "request": "get_artmode_settings",
                "id": self.get_uuid()
            })
            if response and "data" in response:
                settings = json.loads(response["data"])
                for setting in settings:
                    if setting.get("item") == "color_temperature":
                        return int(setting.get("value", 0))
        except Exception:
            # Try old API
            try:
                response = self._send_command({
                    "request": "get_color_temperature",
                    "id": self.get_uuid()
                })
                if response:
                    return int(response.get("value", 0))
            except Exception as exc:
                _LOGGING.error("Error getting color temperature: %s", exc)
        return None

    def get_available_artworks(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of available artworks."""
        try:
            response = self._send_command({
                "request": "get_content_list",
                "category": category,
                "id": self.get_uuid()
            })
            if response and "content_list" in response:
                content_list = json.loads(response["content_list"])
                if category:
                    return [v for v in content_list if v.get("category_id") == category]
                return content_list
        except Exception as exc:
            _LOGGING.error("Error getting available artworks: %s", exc)
        return []

    def get_slideshow_status(self) -> Optional[Dict[str, Any]]:
        """Get slideshow status."""
        try:
            response = self._send_command({
                "request": "get_slideshow_status",
                "id": self.get_uuid()
            })
            return response
        except Exception as exc:
            _LOGGING.error("Error getting slideshow status: %s", exc)
        return None

    def set_artmode(self, mode: str) -> bool:
        """Set art mode on/off."""
        try:
            response = self._send_command({
                "request": "set_artmode_status",
                "value": mode,
                "id": self.get_uuid()
            })
            return response is not None
        except Exception as exc:
            _LOGGING.error("Error setting art mode: %s", exc)
        return False

    def close(self):
        """Close connection."""
        self._disconnect()