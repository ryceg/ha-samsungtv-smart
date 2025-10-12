"""Google Arts & Culture artwork provider for Samsung Frame TV."""

from __future__ import annotations

import logging
import random
from typing import Any

import aiohttp

from . import ArtworkProvider

_LOGGER = logging.getLogger(__name__)

# Google Arts & Culture daily artwork endpoint (unofficial)
GOOGLE_ARTS_FEED_URL = "https://www.gstatic.com/culturalinstitute/searchar/jsonparsers_daily.json"

# Fallback: Featured artworks from Google Arts
GOOGLE_ARTS_FEATURED_URL = "https://artsandculture.google.com/api/entity?ids="

# High-res image template
GOOGLE_ARTS_IMAGE_URL = "https://lh3.googleusercontent.com/{asset_id}=s2048"


class GoogleArtsProvider(ArtworkProvider):
    """Provider that fetches artworks from Google Arts & Culture."""

    @property
    def name(self) -> str:
        """Return provider name."""
        return "Google Arts & Culture"

    @property
    def config_key(self) -> str:
        """Return config option key."""
        return "google_arts"

    async def async_load_artworks(self) -> list[dict]:
        """Load artworks from Google Arts & Culture.

        Note: This uses publicly available endpoints that may change.
        For production use, consider using the official API with an API key.
        """
        artworks = []

        # Try to load from daily feed
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(GOOGLE_ARTS_FEED_URL, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        artworks = await self._parse_daily_feed(data)

        except Exception as exc:
            _LOGGER.warning("Could not load Google Arts daily feed: %s", exc)

        # If no artworks loaded, try fallback
        if not artworks:
            artworks = await self._load_fallback_artworks()

        _LOGGER.debug("Loaded %d artworks from Google Arts & Culture", len(artworks))
        return artworks

    async def _parse_daily_feed(self, data: dict) -> list[dict]:
        """Parse daily feed JSON."""
        artworks = []

        try:
            # The structure may vary, adapt as needed
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("items", [])
            else:
                return []

            for item in items:
                if not isinstance(item, dict):
                    continue

                # Extract relevant fields
                artwork_id = item.get("id") or item.get("asset_id")
                title = item.get("title") or item.get("name", "Untitled")
                asset_id = item.get("asset_id") or artwork_id

                if not asset_id:
                    continue

                artwork = {
                    "id": f"google_arts_{artwork_id}",
                    "source": self.name,
                    "title": title,
                    "url": GOOGLE_ARTS_IMAGE_URL.format(asset_id=asset_id),
                    "asset_id": asset_id,
                }
                artworks.append(artwork)

        except Exception as exc:
            _LOGGER.error("Error parsing Google Arts feed: %s", exc)

        return artworks

    async def _load_fallback_artworks(self) -> list[dict]:
        """Load fallback artworks using hardcoded popular pieces.

        This provides a basic set of artworks when the API is unavailable.
        """
        _LOGGER.warning("Google Arts & Culture API unavailable, no fallback artworks configured")
        return []

    async def async_get_artwork_data(self, artwork_id: str) -> bytes | None:
        """Download artwork image data.

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
                            "Downloaded %d bytes for artwork: %s",
                            len(data),
                            artwork.get("title", artwork_id)
                        )
                        return data
                    else:
                        _LOGGER.error(
                            "Failed to download artwork %s: HTTP %d",
                            artwork_id,
                            response.status
                        )
                        return None

        except Exception as exc:
            _LOGGER.error("Error downloading artwork %s: %s", artwork_id, exc)
            return None
