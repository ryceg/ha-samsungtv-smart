"""Samsung TV Smart Sensors."""

from .art_mode import (
    SamsungTVArtModeStatusSensor,
    SamsungTVArtSettingsSensor,
    SamsungTVAvailableArtworksSensor,
    SamsungTVCurrentArtworkSensor,
    SamsungTVSlideshowStatusSensor,
    SamsungTVStatusSensor,
)
from .channel import SamsungTVChannelNameSensor
from .media_playback import SamsungTVPlaybackStatusSensor
from .power import SamsungTVEnergyConsumptionSensor, SamsungTVPowerConsumptionSensor

__all__ = [
    "SamsungTVArtModeStatusSensor",
    "SamsungTVArtSettingsSensor",
    "SamsungTVAvailableArtworksSensor",
    "SamsungTVChannelNameSensor",
    "SamsungTVCurrentArtworkSensor",
    "SamsungTVEnergyConsumptionSensor",
    "SamsungTVPlaybackStatusSensor",
    "SamsungTVPowerConsumptionSensor",
    "SamsungTVSlideshowStatusSensor",
    "SamsungTVStatusSensor",
]