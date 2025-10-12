"""Diagnostics support for Samsung TV Smart."""

from __future__ import annotations

import json

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_ID, CONF_MAC, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

TO_REDACT = {CONF_API_KEY, CONF_MAC, CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics for a config entry."""
    diag_data = {"entry": async_redact_data(entry.as_dict(), TO_REDACT)}

    yaml_data = hass.data[DOMAIN].get(entry.unique_id, {})
    if yaml_data:
        diag_data["config_data"] = async_redact_data(yaml_data, TO_REDACT)

    device_id = entry.data.get(CONF_ID, entry.entry_id)
    hass_data = _async_device_ha_info(hass, device_id)
    if hass_data:
        diag_data["device"] = hass_data

    # Include Samsung TV API v2 device information
    api_info = await _async_get_tv_api_info(hass, entry)
    if api_info:
        diag_data["tv_api_info"] = api_info

    return diag_data


async def _async_get_tv_api_info(hass: HomeAssistant, entry: ConfigEntry) -> dict | None:
    """Get Samsung TV API v2 device information."""
    try:
        # Try to get the media player coordinator
        if entry.entry_id not in hass.data[DOMAIN]:
            return None

        coordinator = hass.data[DOMAIN][entry.entry_id]
        if not hasattr(coordinator, "_device_info"):
            return None

        device_info = coordinator._device_info
        if not device_info:
            return None

        # Extract useful diagnostic information from API v2 response
        api_data = {}

        # Device information
        if "device" in device_info:
            device = device_info["device"]
            api_data["device"] = {
                "os": device.get("OS"),
                "model": device.get("model"),
                "model_name": device.get("modelName"),
                "firmware_version": device.get("firmwareVersion"),
                "resolution": device.get("resolution"),
                "network_type": device.get("networkType"),
                "frame_tv_support": device.get("FrameTVSupport"),
                "token_auth_support": device.get("TokenAuthSupport"),
                "voice_support": device.get("VoiceSupport"),
                "gamepad_support": device.get("GamePadSupport"),
                "ime_synced_support": device.get("ImeSyncedSupport"),
                "developer_mode": device.get("developerMode"),
                "power_state": device.get("PowerState"),
                "language": device.get("Language"),
                "country_code": device.get("countryCode"),
                "wall_service": device.get("WallService"),
                "edge_blending_support": device.get("EdgeBlendingSupport"),
            }

        # API version and support information
        if "version" in device_info:
            api_data["api_version"] = device_info["version"]

        if "isSupport" in device_info:
            try:
                support_info = json.loads(device_info["isSupport"])
                api_data["supported_features"] = support_info
            except (json.JSONDecodeError, TypeError):
                api_data["supported_features"] = device_info["isSupport"]

        return api_data

    except Exception:  # pylint: disable=broad-except
        return None


@callback
def _async_device_ha_info(hass: HomeAssistant, device_id: str) -> dict | None:
    """Gather information how this TV device is represented in Home Assistant."""

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    hass_device = device_registry.async_get_device(identifiers={(DOMAIN, device_id)})
    if not hass_device:
        return None

    data = {
        "name": hass_device.name,
        "name_by_user": hass_device.name_by_user,
        "model": hass_device.model,
        "manufacturer": hass_device.manufacturer,
        "sw_version": hass_device.sw_version,
        "disabled": hass_device.disabled,
        "disabled_by": hass_device.disabled_by,
        "entities": {},
    }

    hass_entities = er.async_entries_for_device(
        entity_registry,
        device_id=hass_device.id,
        include_disabled_entities=True,
    )

    for entity_entry in hass_entities:
        if entity_entry.platform != DOMAIN:
            continue
        state = hass.states.get(entity_entry.entity_id)
        state_dict = None
        if state:
            state_dict = dict(state.as_dict())
            # The entity_id is already provided at root level.
            state_dict.pop("entity_id", None)
            # The context doesn't provide useful information in this case.
            state_dict.pop("context", None)
            # Redact the `entity_picture` attribute as it contains a token.
            if "entity_picture" in state_dict["attributes"]:
                state_dict["attributes"] = {
                    **state_dict["attributes"],
                    "entity_picture": REDACTED,
                }

        data["entities"][entity_entry.entity_id] = {
            "name": entity_entry.name,
            "original_name": entity_entry.original_name,
            "disabled": entity_entry.disabled,
            "disabled_by": entity_entry.disabled_by,
            "entity_category": entity_entry.entity_category,
            "device_class": entity_entry.device_class,
            "original_device_class": entity_entry.original_device_class,
            "icon": entity_entry.icon,
            "original_icon": entity_entry.original_icon,
            "unit_of_measurement": entity_entry.unit_of_measurement,
            "state": state_dict,
        }

    return data
