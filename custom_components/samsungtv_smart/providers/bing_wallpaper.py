"""Bing Wallpaper artwork provider for Samsung Frame TV."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp

from . import ArtworkProvider

_LOGGER = logging.getLogger(__name__)

# Bing wallpaper API endpoint
BING_API_URL = "https://www.bing.com/HPImageArchive.aspx"

# High-res image base URL
BING_IMAGE_BASE = "https://www.bing.com"


class BingWallpaperProvider(ArtworkProvider):
    """Provider that fetches Bing daily wallpapers."""

    @property
    def name(self) -> str:
        """Return provider name."""
        return "Bing Wallpapers"

    @property
    def config_key(self) -> str:
        """Return config option key."""
        return "bing_wallpaper"

    def _get_region(self) -> str:
        """Get configured region code."""
        return self._config.get("bing_wallpaper_region", "en-US")

    def _get_history_days(self) -> int:
        """Get number of historical days to fetch."""
        days = self._config.get("bing_wallpaper_history_days", 7)
        return min(max(days, 1), 8)  # Bing API supports up to 8 days

    async def async_load_artworks(self) -> list[dict]:
        """Load Bing daily wallpapers."""
        region = self._get_region()
        history_days = self._get_history_days()

        artworks = []

        try:
            async with aiohttp.ClientSession() as session:
                # Request wallpapers with history
                params = {
                    "format": "js",
                    "idx": 0,
                    "n": history_days,
                    "mkt": region,
                }

                async with session.get(BING_API_URL, params=params, timeout=10) as response:
                    if response.status != 200:
                        _LOGGER.error(
                            "Failed to load Bing wallpapers: HTTP %d",
                            response.status
                        )
                        return []

                    data = await response.json()
                    images = data.get("images", [])

                    for image in images:
                        artwork = self._parse_bing_image(image)
                        if artwork:
                            artworks.append(artwork)

            _LOGGER.debug("Loaded %d Bing wallpapers", len(artworks))
            return artworks

        except Exception as exc:
            _LOGGER.error("Error loading Bing wallpapers: %s", exc)
            return []

    def _parse_bing_image(self, image: dict) -> dict | None:
        """Parse Bing image data."""
        try:
            # Extract data
            url_base = image.get("urlbase", "")
            if not url_base:
                return None

            # Build high-res URL (1920x1080 or UHD)
            url = f"{BING_IMAGE_BASE}{url_base}_UHD.jpg"

            # Extract date
            startdate = image.get("startdate", "")
            if startdate:
                try:
                    date_obj = datetime.strptime(startdate, "%Y%m%d")
                    date_str = date_obj.strftime("%Y-%m-%d")
                except ValueError:
                    date_str = startdate
            else:
                date_str = "unknown"

            # Extract title and copyright
            title = image.get("title", "Bing Wallpaper")
            copyright_text = image.get("copyright", "")

            # Create unique ID
            artwork_id = f"bing_{startdate}_{hash(url_base) & 0xFFFFFFFF:08x}"

            artwork = {
                "id": artwork_id,
                "source": self.name,
                "title": f"{title} ({date_str})",
                "url": url,
                "copyright": copyright_text,
                "date": date_str,
            }

            return artwork

        except Exception as exc:
            _LOGGER.error("Error parsing Bing image: %s", exc)
            return None

    async def async_get_artwork_data(self, artwork_id: str) -> bytes | None:
        """Download Bing wallpaper image data.

        Args:
            artwork_id: Artwork identifier from async_load_artworks

        Returns:
            Image data as bytes
        """
        # Find artwork in cache
        artwork = None
        for art in self._artworks:
            if art["id"] == artwork_id:
                artwork = art
                break

        if not artwork:
            _LOGGER.error("Artwork not found: %s", artwork_id)
            return None

        url = artwork.get("url")
        if not url:
            _LOGGER.error("No URL for artwork: %s", artwork_id)
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        data = await response.read()
                        _LOGGER.debug(
                            "Downloaded %d bytes for Bing wallpaper: %s",
                            len(data),
                            artwork.get("title", artwork_id)
                        )
                        return data
                    else:
                        _LOGGER.error(
                            "Failed to download Bing wallpaper %s: HTTP %d",
                            artwork_id,
                            response.status
                        )
                        return None

        except Exception as exc:
            _LOGGER.error("Error downloading Bing wallpaper %s: %s", artwork_id, exc)
            return None
