"""Channel-related sensors for Samsung TV Smart integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..api.smartthings import STStatus
from .base import SamsungTVSensorBase


class SamsungTVChannelNameSensor(SamsungTVSensorBase):
    """Representation of a Samsung TV channel name sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:television"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=True)
        
        self._attr_name = "Channel Name"
        self._attr_unique_id = f"{self.unique_id}_channel_name"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not self._st or self._st.state != STStatus.STATE_ON:
            return None
        
        channel_name = self._st.channel_name
        return channel_name if channel_name else None