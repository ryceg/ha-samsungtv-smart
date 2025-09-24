"""Power-related sensors for Samsung TV Smart integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant

from ..api.smartthings import STStatus
from .base import SamsungTVSensorBase


class SamsungTVPowerConsumptionSensor(SamsungTVSensorBase):
    """Representation of a Samsung TV power consumption sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:flash"
    _attr_suggested_display_precision = 1

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Power Consumption"
        self._attr_unique_id = f"{self.unique_id}_power_consumption"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self._st:
            return None
        
        return self._st.power_consumption

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._st is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self._st:
            return {}
        
        attributes = {
            "tv_state": self._st.state,
            "smartthings_device_id": self._st._device_id,
        }
        
        # Add raw power data for debugging
        if hasattr(self._st, '_power_consumption'):
            attributes["raw_power_value"] = self._st._power_consumption
            
        return attributes


class SamsungTVEnergyConsumptionSensor(SamsungTVSensorBase):
    """Representation of a Samsung TV energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"
    _attr_suggested_display_precision = 2

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Energy Consumption"
        self._attr_unique_id = f"{self.unique_id}_energy_consumption"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self._st:
            return None
        
        return self._st.energy

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._st is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self._st:
            return {}
        
        attributes = {
            "tv_state": self._st.state,
            "smartthings_device_id": self._st._device_id,
        }
        
        # Add raw energy data for debugging
        if hasattr(self._st, '_energy'):
            attributes["raw_energy_value"] = self._st._energy
            
        return attributes