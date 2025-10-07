# SamsungTV Smart - Home Assistant Custom Component

## Project Overview

**SamsungTV Smart** is a custom Home Assistant integration for controlling Samsung Smart TVs (2016+ models using Tizen OS). This is a fork of SamsungTV Tizen with enhanced features, UI configuration, and Art Mode support for "The Frame" TVs.

**Key Features:**
- WebSocket-based control via Samsung TV WS API
- SmartThings Cloud API integration for enhanced features
- Art Mode support for Frame TVs (artwork management, slideshow control)
- Multi-platform entity support (media_player, remote, sensor, image, number, select)
- Logo display for TV channels and apps
- Key chaining and macro support
- YouTube casting with enqueue support

**Technology Stack:**
- Python 3.13+
- Home Assistant 2025.6.0+
- WebSocket for TV communication
- REST API for SmartThings integration
- HACS for distribution

## Project Structure

```
custom_components/samsungtv_smart/
├── __init__.py              # Integration setup, platform registration
├── const.py                 # Constants, enums, configuration keys
├── manifest.json            # Integration metadata
├── config_flow.py           # UI configuration flow
├── entity.py               # Base entity class (SamsungTVEntity)
├── media_player.py         # Main media player platform
├── remote.py               # Remote control platform
├── sensor.py               # Art mode sensors (status, artwork, brightness, etc.)
├── image.py                # Art mode current artwork image display
├── number.py               # Art mode number controls (brightness, color temp)
├── select.py               # Art mode select controls (matte, photo filter)
├── logo.py                 # Logo retrieval and caching
├── diagnostics.py          # Diagnostic data collection
└── api/
    ├── samsungws.py        # WebSocket API wrapper (core communication)
    ├── smartthings.py      # SmartThings Cloud API
    ├── art.py              # Art Mode API
    ├── samsungcast.py      # Casting functionality
    ├── upnp.py             # UPnP for network discovery
    └── shortcuts.py        # Key shortcuts management
```

## Architecture Patterns

### 1. Platform Registration Pattern

The integration uses Home Assistant's modern platform setup:

```python
# In __init__.py
SAMSMART_PLATFORM = [
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SENSOR,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
]

async def async_setup_entry(hass, entry):
    # Setup entry data
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CFG: config,
        DATA_OPTIONS: entry.options.copy(),
    }

    # Forward to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, SAMSMART_PLATFORM)
```

### 2. Shared WebSocket Instance Pattern

The WebSocket connection (`SamsungTVWS`) is created by the media_player and shared across all platforms:

**Media Player** (creates and stores):
```python
# In media_player.py
self._ws = SamsungTVWS(...)
entry_data[DATA_WS] = self._ws  # Store in hass.data for other platforms
```

**Other Platforms** (retrieve):
```python
# In sensor.py, image.py, number.py, select.py
ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)
```

**Key Point:** The WebSocket instance (`DATA_WS`) is shared across all entities to maintain a single connection to the TV.

### 3. Delayed Entity Setup Pattern (async_call_later)

Art mode entities (sensors, image, number, select) use `async_call_later` to delay creation until:
1. Media player entity is fully initialized
2. Art mode detection is complete

```python
async def async_setup_entry(hass, config_entry, async_add_entities):
    @callback
    def _add_art_mode_entities(utc_now: datetime) -> None:
        # Find media player entity
        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        # Check if art mode is supported
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state.attributes.get("art_mode_supported", False):
            return  # Skip if not supported

        # Get shared WebSocket instance
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)

        # Create entities
        entities = [
            ArtModeSensor(config, entry_id, media_player_entity_id, ws_instance),
            # ... more entities
        ]
        async_add_entities(entities, True)

    # Wait 10 seconds for media player to be ready
    async_call_later(hass, 10, _add_art_mode_entities)
```

**Delay Times:**
- Remote: 5 seconds
- Art mode entities: 10 seconds (allows art mode detection to complete)

### 4. Base Entity Pattern

All entities inherit from `SamsungTVEntity` which handles device info:

```python
class SamsungTVEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, config: dict[str, Any], entry_id: str):
        self._name = config.get(CONF_NAME, config[CONF_HOST])
        self._mac = config.get(CONF_MAC)
        self._attr_unique_id = config.get(CONF_ID, entry_id)

        # Device info with model, manufacturer, connections
        self._attr_device_info = DeviceInfo(...)
```

Platform-specific entities use multiple inheritance:
```python
class SamsungTVDevice(SamsungTVEntity, MediaPlayerEntity): ...
class SamsungTVRemote(SamsungTVEntity, RemoteEntity): ...
class ArtModeImageEntity(SamsungTVEntity, ImageEntity): ...
```

## WebSocket API Architecture (samsungws.py)

### Key Components

1. **Connection Management**
   - Three WebSocket endpoints: remote control, app control, art mode
   - Automatic reconnection with ping/pong monitoring
   - SSL/non-SSL support (port 8001/8002)

2. **Threading Model**
   - Remote control: Main thread with WebSocketApp.run_forever()
   - Control channel: Separate thread for app control
   - Art mode: Separate thread for art operations

3. **Message Handling**
   ```python
   def _on_message_remote(self, _, message):
       response = _process_api_response(message)
       event = response.get("event")

       # Handle different event types
       if event == "ms.channel.connect": ...
       elif event == "ms.channel.ready": ...
       elif event == "ms.remote.touchEnable": ...
   ```

### Art Mode WebSocket Flow

1. **Connection**: Connects to `/api/v2/channels/com.samsung.art-app`
2. **Events Handled**:
   - `d2d_service_message`: Art mode responses (artwork lists, current artwork, etc.)
   - `art_mode`: Status changes
   - `current_artwork`: Current artwork info updates

3. **Caching**: Artwork thumbnails are cached in `_artwork_thumbnails` dict
   ```python
   def get_artwork_thumbnail(self, artwork_id: str) -> bytes | None:
       if artwork_id in self._artwork_thumbnails:
           return self._artwork_thumbnails[artwork_id]
       # ... request from TV and cache
   ```

## Art Mode Architecture

### Data Flow

1. **Detection** (media_player.py)
   - On connection, query TV for art mode support
   - Set `art_mode_supported` attribute
   - Request current artwork info

2. **Shared State** (WebSocket instance)
   - `_current_artwork`: Dict with current artwork metadata
   - `_artwork_thumbnails`: Dict caching artwork images by ID
   - `_art_mode_status`: Current art mode state

3. **Entity Access Pattern**
   ```python
   # Entities retrieve data from WebSocket instance
   class ArtModeSensorBase(SamsungTVEntity, SensorEntity):
       def __init__(self, ..., ws_instance):
           self._ws = ws_instance

       def _get_ws_data(self, attr_name):
           if not self._ws or not hasattr(self._ws, attr_name):
               return None
           return getattr(self._ws, attr_name)
   ```

4. **Image Entity** (image.py)
   - Tracks media player state changes
   - Detects artwork changes via `current_artwork` attribute
   - Requests thumbnail from WebSocket cache
   - Invalidates cache when artwork changes

### Art Mode Entities

**Sensors** (sensor.py):
- `ArtModeStatusSensor`: On/Off/Unavailable status
- `CurrentArtworkSensor`: Current artwork name/ID
- `SlideshowStatusSensor`: Slideshow state
- `ArtBrightnessSensor`: Brightness value
- `ArtColorTemperatureSensor`: Color temperature

**Image** (image.py):
- `ArtModeImageEntity`: Displays current artwork thumbnail

**Number** (number.py):
- `ArtBrightnessNumber`: Brightness control (0-100)
- `ArtColorTemperatureNumber`: Color temperature (0-100)

**Select** (select.py):
- `ArtMatteSelect`: Matte style selection
- `ArtPhotoFilterSelect`: Photo filter selection

## Platform Interaction Patterns

### 1. Media Player → Other Platforms

Media player is the "hub" that:
- Creates the WebSocket instance
- Stores it in `hass.data[DOMAIN][entry_id][DATA_WS]`
- Provides state via attributes (art_mode_supported, current_artwork, etc.)

### 2. Art Entities → Media Player

Art entities:
- Read media player state/attributes
- Use shared WebSocket instance for operations
- Track media player state changes via `async_track_state_change_event`

### 3. Remote → Media Player

Remote entity:
- Delegates all operations to media player via service calls
- Acts as a simplified interface

```python
# Remote calls media player services
await async_call_from_config(hass, {
    CONF_SERVICE: f"{MP_DOMAIN}.play_media",
    CONF_SERVICE_ENTITY_ID: self._mp_entity_id,
    CONF_SERVICE_DATA: {
        ATTR_MEDIA_CONTENT_TYPE: MEDIA_TYPE_KEY,
        ATTR_MEDIA_CONTENT_ID: command,
    }
})
```

## Configuration & Options

### Entry Data (config.data)
- `CONF_HOST`: TV IP address
- `CONF_MAC`: MAC address (for WOL)
- `CONF_PORT`: WebSocket port (8001/8002)
- `CONF_TOKEN`: WebSocket authentication token
- `CONF_ID`: Unique device ID
- `CONF_DEVICE_MODEL/NAME/OS`: Device information
- `CONF_API_KEY`: SmartThings API key (deprecated, use ST integration)
- `CONF_ST_ENTRY_UNIQUE_ID`: SmartThings integration link

### Entry Options (config.options)
- Source/App/Channel lists (dict)
- Art mode settings
- Power control preferences
- SmartThings feature toggles
- Synced entity lists

### YAML Config (legacy)
Supported for backward compatibility, imported to options on first load:
```python
# In __init__.py async_setup
if DOMAIN in config:
    for entry_config in config[DOMAIN]:
        data_yaml = {...}  # Extract YAML config
        hass.data[DOMAIN][entry_id] = {DATA_CFG_YAML: data_yaml}
```

## SmartThings Integration

Two modes:
1. **Legacy**: Direct API key in integration config (deprecated)
2. **Modern**: Link to SmartThings integration via `CONF_ST_ENTRY_UNIQUE_ID`

```python
# Get API key from SmartThings integration
api_key = get_smartthings_api_key(hass, st_unique_id)
```

## Development Workflow

### Setup
```bash
./scripts/setup               # Install dependencies
./scripts/develop            # Run local HA instance
```

### Testing
```bash
pytest                       # Run tests
pytest --cov                 # With coverage
```

### Linting
```bash
./scripts/lint               # Run ruff with auto-fix
flake8 .                     # Check style
isort --diff --check .       # Check imports
black --check .              # Check formatting
```

### CI/CD
- **Linting**: flake8, isort, black (on push/PR)
- **Validation**: hassfest, HACS validation
- **Release**: Automatic ZIP creation on version tag

## Key Files to Understand

1. **`__init__.py`**: Entry point, platform registration, migrations
2. **`media_player.py`**: Main entity, WebSocket lifecycle, state management
3. **`api/samsungws.py`**: WebSocket protocol, art mode, caching
4. **`entity.py`**: Base class for device info
5. **`const.py`**: All constants, enums, default values

## Common Development Tasks

### Adding a New Art Mode Entity

1. Create entity class inheriting from base (e.g., `ArtModeSelectBase`)
2. Implement required properties/methods
3. Add to setup function with `async_call_later` pattern
4. Access WebSocket instance via `self._ws`
5. Track media player state if needed

### Extending WebSocket API

1. Add new message handler in `_on_message_control` or `_on_message_art`
2. Update response processing in `_process_api_response`
3. Add public method to `SamsungTVWS` class
4. Cache data in instance variables if needed

### Adding New Configuration Option

1. Add constant to `const.py`
2. Update `config_flow.py` for UI
3. Handle in `_migrate_options_format` if migrating from YAML
4. Access via `hass.data[DOMAIN][entry_id][DATA_OPTIONS]`

## Important Concepts

### 1. Token Management
- WebSocket token stored in config entry data
- Auto-migrated from file to registry
- Token refresh handled automatically by WebSocket

### 2. Power State Detection
- Ping probe (ICMP or port check)
- SmartThings status (if configured)
- Mute state heuristic (fake power on detection)
- External binary sensor (optional)

### 3. App Launch Methods
- `Standard`: Control WebSocket channel
- `Remote`: Remote WebSocket channel
- `Rest`: HTTP REST API (fallback)

### 4. Source Management
- Sources: KEY-based inputs (KEY_HDMI, KEY_TV)
- Apps: Application IDs (Netflix, YouTube)
- Channels: TV channel numbers with optional source

### 5. Logo System
- Remote API for channel/app logos
- Local custom logos in `www/samsungtv_smart_logos/`
- Cached with configurable background/color options

## Testing Notes

- Tests use `pytest-homeassistant-custom-component`
- Mock WebSocket connections for unit tests
- Integration tests require actual TV or simulator
- Coverage configured in `setup.cfg`

## Migration Patterns

The integration handles several migrations:
1. **Token**: File → Registry entry
2. **Options**: String → List (for sync entities)
3. **YAML**: Config → Options (one-time import)
4. **Unique ID**: Various formats → Standardized
5. **SmartThings**: Direct API key → Integration link

## Debugging Tips

1. **Enable debug logging**:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.samsungtv_smart: debug
   ```

2. **WebSocket issues**: Check `_ws_remote`, `_ws_control`, `_ws_art` threads
3. **Art mode**: Verify `art_mode_supported` attribute on media player
4. **Entity not appearing**: Check delay in `async_call_later` (may need to wait)
5. **State updates**: Monitor `async_dispatcher_send(SIGNAL_CONFIG_ENTITY)`

## Version Requirements

- **Home Assistant**: 2025.6.0+
- **Python**: 3.13+
- **Dependencies**:
  - `websocket-client!=1.4.0,>=0.58.0`
  - `wakeonlan>=2.0.0`
  - `aiofiles>=0.8.0`
  - `casttube>=0.2.1`

## Resources

- [Documentation](https://github.com/ollo69/ha-samsungtv-smart)
- [Key Codes](docs/Key_codes.md)
- [Key Chaining](docs/Key_chaining.md)
- [SmartThings Setup](docs/Smartthings.md)
- [App List Guide](docs/App_list.md)
