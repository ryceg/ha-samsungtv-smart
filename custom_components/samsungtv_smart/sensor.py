"""Support for Samsung TV sensors."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_CFG, DOMAIN
from .sensors.art_mode import (
    SamsungTVArtModeStatusSensor,
    SamsungTVAvailableArtworksSensor,
    SamsungTVCurrentArtworkSensor,
    SamsungTVStatusSensor,
    SamsungTVApiVersionSensor,
    SamsungTVDeviceInfoSensor,
)
from .sensors.channel import SamsungTVChannelNameSensor
from .sensors.media_playback import SamsungTVPlaybackStatusSensor
from .sensors.power import SamsungTVEnergyConsumptionSensor, SamsungTVPowerConsumptionSensor


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

    # Add available sensors
    sensors.extend([
        # Core status sensors
        SamsungTVStatusSensor(config, entry.entry_id, hass),
        SamsungTVPlaybackStatusSensor(config, entry.entry_id, hass),
        # Channel sensors
        SamsungTVChannelNameSensor(config, entry.entry_id, hass),
        # Power sensors
        SamsungTVPowerConsumptionSensor(config, entry.entry_id, hass),
        SamsungTVEnergyConsumptionSensor(config, entry.entry_id, hass),
        # Art mode sensors
        SamsungTVArtModeStatusSensor(config, entry.entry_id, hass),
        SamsungTVCurrentArtworkSensor(config, entry.entry_id, hass),
        SamsungTVAvailableArtworksSensor(config, entry.entry_id, hass),
        # Device info sensors
        SamsungTVApiVersionSensor(config, entry.entry_id, hass),
        SamsungTVDeviceInfoSensor(config, entry.entry_id, hass),
    ])

    async_add_entities(sensors, True)