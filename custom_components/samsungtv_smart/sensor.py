"""Support for Samsung TV sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_smartthings_api_key
from .api.smartthings import SmartThingsTV, STStatus
from .const import (
    CONF_ST_ENTRY_UNIQUE_ID,
    DATA_CFG,
    DOMAIN,
)
from .entity import SamsungTVEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung TV sensor based on a config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]
    
    # Only add sensors if SmartThings is configured
    st_api_key = config.get(CONF_API_KEY)
    device_id = config.get(CONF_DEVICE_ID)
    
    if not st_api_key or not device_id:
        return

    sensors = []
    
    # Add playback status sensor
    sensors.append(SamsungTVPlaybackStatusSensor(config, entry.entry_id, hass))

    async_add_entities(sensors, True)


class SamsungTVPlaybackStatusSensor(SamsungTVEntity, SensorEntity):
    """Representation of a Samsung TV playback status sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:play-pause"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id)
        
        self._attr_name = "Playback Status"
        self._attr_unique_id = f"{self.unique_id}_playback_status"
        
        # Initialize SmartThings connection if available
        self._st = None
        st_entry_uniqueid: str | None = config.get(CONF_ST_ENTRY_UNIQUE_ID)
        
        def api_key_callback() -> str | None:
            """Get new api key and update config entry with the new token."""
            if st_entry_uniqueid:
                return get_smartthings_api_key(hass, st_entry_uniqueid)
            return None

        st_api_key = config.get(CONF_API_KEY)
        device_id = config.get(CONF_DEVICE_ID)
        
        if st_api_key and device_id:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(hass)
            
            use_callback: bool = st_entry_uniqueid is not None
            self._st = SmartThingsTV(
                api_key=st_api_key,
                device_id=device_id,
                use_channel_info=False,  # We don't need channel info for playback status
                session=session,
                api_key_callback=api_key_callback if use_callback else None,
            )

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

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._st is not None and self._st.state != STStatus.STATE_UNKNOWN

    async def async_update(self) -> None:
        """Update the sensor state."""
        if self._st:
            try:
                await self._st.async_device_update()
            except Exception:
                # If update fails, sensor will show as unavailable
                pass