"""Overlay image generator for Samsung Frame TV."""

from __future__ import annotations

from datetime import datetime, timedelta
import io
import logging
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Image dimensions for 4K display
IMAGE_WIDTH = 3840
IMAGE_HEIGHT = 2160

# Color definitions
COLOR_WHITE = (255, 255, 255, 255)
COLOR_BLACK = (0, 0, 0, 200)  # Semi-transparent black
COLOR_TRANSPARENT = (0, 0, 0, 0)

# Layout constants
PADDING = 120
SECTION_SPACING = 60
LINE_SPACING = 15

# Font sizes (larger for 4K display)
FONT_SIZE_TIME = 180
FONT_SIZE_DATE = 100
FONT_SIZE_TITLE = 110
FONT_SIZE_ITEM = 80
FONT_SIZE_WEATHER = 100


class OverlayGenerator:
    """Generate overlay images for Frame TV."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the overlay generator."""
        self.hass = hass
        self._font_cache: dict[int, ImageFont.FreeTypeFont] = {}
        self._font_path: str | None = None
        self._fonts_initialized = False

        # Don't load fonts during __init__ to avoid blocking in async context
        # They will be loaded on first use

    def _ensure_fonts_loaded(self) -> None:
        """Ensure fonts are loaded (called from sync context only)."""
        if self._fonts_initialized:
            return

        self._fonts_initialized = True

        # Try to find a TrueType font
        import os
        font_paths = [
            # Custom font in config/www directory (user can place any TTF here)
            self.hass.config.path("www", "fanwood-webfont.ttf"),
            # Alpine Linux (common in HA containers)
            "/usr/share/fonts/ttf-dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
            # Debian/Ubuntu paths (HA Supervised)
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            # Other common locations
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]

        for path in font_paths:
            if os.path.exists(path):
                try:
                    # Test load
                    test_font = ImageFont.truetype(path, 12)
                    self._font_path = path
                    _LOGGER.info("Using font: %s", path)

                    # Pre-load common sizes
                    for size in [FONT_SIZE_TIME, FONT_SIZE_DATE, FONT_SIZE_TITLE, FONT_SIZE_ITEM, FONT_SIZE_WEATHER]:
                        try:
                            self._font_cache[size] = ImageFont.truetype(self._font_path, size)
                        except OSError:
                            pass
                    return
                except (OSError, IOError):
                    continue

        _LOGGER.warning("Could not find TrueType font, text will be small")
        self._font_path = None

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get a font of specified size, with caching."""
        if size not in self._font_cache:
            if self._font_path:
                try:
                    self._font_cache[size] = ImageFont.truetype(self._font_path, size)
                except (OSError, IOError) as exc:
                    _LOGGER.warning("Failed to load font size %d: %s", size, exc)
                    self._font_cache[size] = ImageFont.load_default()
            else:
                self._font_cache[size] = ImageFont.load_default()

        return self._font_cache[size]

    def _draw_text_with_shadow(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple[int, int, int, int] = COLOR_WHITE,
        shadow_offset: int = 3,
    ) -> None:
        """Draw text with a shadow for better visibility."""
        x, y = position

        # Draw shadow
        draw.text(
            (x + shadow_offset, y + shadow_offset),
            text,
            font=font,
            fill=(0, 0, 0, 200),
        )

        # Draw main text
        draw.text(
            position,
            text,
            font=font,
            fill=fill,
        )

    def _draw_gradient_background(
        self,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
        fade_direction: str = "down",
    ) -> None:
        """Draw a gradient background for text visibility.

        Args:
            image: PIL Image to draw on (RGBA mode)
            bbox: Bounding box (x1, y1, x2, y2)
            fade_direction: 'down' = dark at top fading down, 'up' = dark at bottom fading up
        """
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1

        # Create a gradient overlay
        gradient = Image.new('RGBA', (width, height), (0, 0, 0, 0))

        for i in range(height):
            progress = i / height

            if fade_direction == "down":
                # Dark at top, fade to transparent at bottom
                alpha = int(180 * (1 - progress))
            else:  # fade_direction == "up"
                # Transparent at top, dark at bottom
                alpha = int(180 * progress)

            # Create a line with the calculated alpha
            line = Image.new('RGBA', (width, 1), (0, 0, 0, alpha))
            gradient.paste(line, (0, i))

        # Composite the gradient onto the image
        image.paste(gradient, (x1, y1), gradient)

    async def _get_calendar_events(self, calendar_entities: list[str]) -> list[dict[str, Any]]:
        """Fetch upcoming calendar events."""
        events = []

        for entity_id in calendar_entities:
            state = self.hass.states.get(entity_id)
            if not state:
                continue

            # Get event details from attributes
            attrs = state.attributes

            # Check if event is happening now or soon
            if state.state == "on" or state.state == "active":
                event = {
                    "summary": attrs.get("message", attrs.get("summary", "Event")),
                    "start": attrs.get("start_time"),
                    "end": attrs.get("end_time"),
                }
                events.append(event)

        # Sort by start time
        events.sort(key=lambda x: x.get("start", ""))

        return events[:5]  # Return up to 5 events

    async def _get_weather_data(self, weather_entity: str) -> dict[str, Any] | None:
        """Fetch weather information."""
        state = self.hass.states.get(weather_entity)
        if not state:
            return None

        attrs = state.attributes

        return {
            "condition": state.state,
            "temperature": attrs.get("temperature"),
            "unit": attrs.get("temperature_unit", "°C"),
            "forecast": attrs.get("forecast", []),
        }

    async def _get_todo_items(self, todo_entities: list[str]) -> list[str]:
        """Fetch todo items."""
        items = []

        for entity_id in todo_entities:
            state = self.hass.states.get(entity_id)
            if not state:
                continue

            # Get todo items from attributes
            attrs = state.attributes
            todo_list = attrs.get("items", [])

            for item in todo_list:
                if isinstance(item, dict):
                    summary = item.get("summary", str(item))
                    status = item.get("status", "needs_action")

                    # Only include incomplete items
                    if status != "completed":
                        items.append(summary)
                elif isinstance(item, str):
                    items.append(item)

        return items[:5]  # Return up to 5 items

    def _draw_time_section(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
    ) -> int:
        """Draw the time and date section, return height used."""
        now = dt_util.now()

        # Time
        time_text = now.strftime("%I:%M %p").lstrip("0")
        time_font = self._get_font(FONT_SIZE_TIME)

        # Draw time text
        self._draw_text_with_shadow(draw, (x, y), time_text, time_font)

        # Date
        date_text = now.strftime("%A, %B %d")
        date_font = self._get_font(FONT_SIZE_DATE)
        date_y = y + 180

        # Draw date text
        self._draw_text_with_shadow(draw, (x, date_y), date_text, date_font)

        return 250  # Total height used

    def _draw_weather_section(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        weather_data: dict[str, Any] | None,
    ) -> int:
        """Draw the weather section, return height used."""
        if not weather_data:
            return 0

        font = self._get_font(FONT_SIZE_WEATHER)

        # Format weather text
        temp = weather_data.get("temperature")
        unit = weather_data.get("unit", "°C")
        condition = weather_data.get("condition", "").title()

        if temp is not None:
            weather_text = f"{condition} {temp}{unit}"
        else:
            weather_text = condition

        # Draw weather text
        self._draw_text_with_shadow(draw, (x, y), weather_text, font)

        return 80  # Height used

    def _draw_calendar_section(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        events: list[dict[str, Any]],
    ) -> int:
        """Draw the calendar events section, return height used."""
        if not events:
            return 0

        title_font = self._get_font(FONT_SIZE_TITLE)
        event_font = self._get_font(FONT_SIZE_ITEM)

        # Draw title
        title_text = "📅 Upcoming Events"
        self._draw_text_with_shadow(draw, (x, y), title_text, title_font)
        current_y = y + 90

        # Draw events
        for event in events[:5]:
            summary = event.get("summary", "Event")
            start_time = event.get("start")

            # Format time
            if start_time:
                try:
                    if isinstance(start_time, str):
                        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    else:
                        dt = start_time
                    time_str = dt.strftime("%I:%M %p").lstrip("0")
                    event_text = f"  {time_str} - {summary[:30]}"
                except (ValueError, AttributeError):
                    event_text = f"  {summary[:35]}"
            else:
                event_text = f"  {summary[:35]}"

            # Draw event text
            self._draw_text_with_shadow(draw, (x, current_y), event_text, event_font)
            current_y += 65

        return current_y - y

    def _draw_todo_section(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        items: list[str],
    ) -> int:
        """Draw the todo items section, return height used."""
        if not items:
            return 0

        title_font = self._get_font(FONT_SIZE_TITLE)
        item_font = self._get_font(FONT_SIZE_ITEM)

        # Draw title
        title_text = "✓ To Do"
        self._draw_text_with_shadow(draw, (x, y), title_text, title_font)
        current_y = y + 90

        # Draw items
        for item in items[:5]:
            item_text = f"  • {item[:40]}"

            # Draw item text
            self._draw_text_with_shadow(draw, (x, current_y), item_text, item_font)
            current_y += 65

        return current_y - y

    def generate_overlay_sync(
        self,
        calendar_events: list[dict[str, Any]],
        weather_data: dict[str, Any] | None,
        todo_items: list[str],
        base_image_data: bytes | None = None,
    ) -> bytes:
        """Generate an overlay image with provided data (sync, runs in executor).

        Args:
            calendar_events: List of calendar event dicts
            weather_data: Weather data dict
            todo_items: List of todo item strings
            base_image_data: Optional base image to overlay onto (JPEG/PNG bytes)

        Returns:
            PNG image data as bytes
        """
        _LOGGER.debug(
            "Generating overlay with %d events, weather=%s, %d todos, base_image=%s",
            len(calendar_events),
            "yes" if weather_data else "no",
            len(todo_items),
            "provided" if base_image_data else "none",
        )

        # Ensure fonts are loaded (safe in executor context)
        self._ensure_fonts_loaded()

        # Create base image
        if base_image_data:
            # Load and resize the base image
            try:
                base_image = Image.open(io.BytesIO(base_image_data))
                # Ensure it's RGB
                if base_image.mode != "RGB":
                    base_image = base_image.convert("RGB")
                # Resize to 4K if needed
                if base_image.size != (IMAGE_WIDTH, IMAGE_HEIGHT):
                    base_image = base_image.resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
                # Convert to RGBA for compositing
                image = base_image.convert("RGBA")
                _LOGGER.debug("Loaded base image: %s", base_image.size)
            except Exception as exc:
                _LOGGER.warning("Failed to load base image, using solid color: %s", exc)
                # Fallback to a dark gray background
                image = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), (40, 40, 40, 255))
        else:
            # No base image - use a dark gray background instead of transparent
            image = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), (40, 40, 40, 255))
        draw = ImageDraw.Draw(image)

        # Draw full-width gradient at top (Chromecast-style)
        top_gradient_height = 400
        self._draw_gradient_background(
            image,
            (0, 0, IMAGE_WIDTH, top_gradient_height),
            fade_direction="down"
        )

        # Draw time section (top-left)
        self._draw_time_section(draw, PADDING, PADDING)

        # Draw weather section (top-right)
        if weather_data:
            weather_x = IMAGE_WIDTH - 800  # Right-aligned with some padding
            self._draw_weather_section(draw, weather_x, PADDING, weather_data)

        # Draw full-width gradient at bottom if there's content (Chromecast-style)
        if calendar_events or todo_items:
            bottom_gradient_height = 600
            bottom_gradient_y = IMAGE_HEIGHT - bottom_gradient_height
            self._draw_gradient_background(
                image,
                (0, bottom_gradient_y, IMAGE_WIDTH, IMAGE_HEIGHT),
                fade_direction="up"
            )

        # Draw calendar section (bottom-left)
        if calendar_events:
            calendar_y = IMAGE_HEIGHT - 500  # Bottom area
            self._draw_calendar_section(draw, PADDING, calendar_y, calendar_events)

        # Draw todo section (bottom-right)
        if todo_items:
            todo_x = IMAGE_WIDTH - 900  # Right-aligned
            todo_y = IMAGE_HEIGHT - 500  # Bottom area
            self._draw_todo_section(draw, todo_x, todo_y, todo_items)

        # Convert to PNG bytes
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        png_data = output.getvalue()
        output.close()

        _LOGGER.info("Generated overlay image: %d bytes", len(png_data))

        return png_data

