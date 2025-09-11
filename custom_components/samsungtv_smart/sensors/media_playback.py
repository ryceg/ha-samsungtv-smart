"""Media playback sensors for Samsung TV Smart integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..api.smartthings import STStatus
from .base import SamsungTVSensorBase


class SamsungTVPlaybackStatusSensor(SamsungTVSensorBase):
    """Representation of a Samsung TV playback status sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:play-pause"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Playback Status"
        self._attr_unique_id = f"{self.unique_id}_playback_status"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not self._st or self._st.state != STStatus.STATE_ON:
            return "unknown"
        
        playback_status = self._st.playback_status
        
        # Map SmartThings playback status values to more user-friendly states
        status_map = {
            "playing": "playing",
            "paused": "paused", 
            "stopped": "stopped",
            "buffering": "buffering",
            "fast_forwarding": "fast_forwarding",
            "rewinding": "rewinding",
        }
        
        return status_map.get(playback_status, playback_status or "unknown")