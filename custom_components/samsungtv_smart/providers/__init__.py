"""Artwork provider framework for Samsung Frame TV slideshow."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ArtworkProvider(ABC):
    """Base class for artwork providers."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the provider."""
        self._config = config
        self._enabled = False
        self._last_error: str | None = None
        self._artworks: list[dict] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""

    @property
    @abstractmethod
    def config_key(self) -> str:
        """Return config option key (e.g., 'media_folder_enabled')."""

    @property
    def enabled(self) -> bool:
        """Return if provider is enabled."""
        return self._enabled

    @property
    def last_error(self) -> str | None:
        """Return last error message."""
        return self._last_error

    @property
    def artwork_count(self) -> int:
        """Return count of available artworks."""
        return len(self._artworks)

    def is_enabled(self) -> bool:
        """Check if provider is enabled in config."""
        return self._config.get(f"{self.config_key}_enabled", False)

    @abstractmethod
    async def async_load_artworks(self) -> list[dict]:
        """Load available artworks from provider.

        Returns:
            List of artwork dicts with keys:
            - id: Unique identifier
            - source: Provider name
            - title: Optional title
            - url: Optional URL for download
            - local_path: Optional local file path
        """

    @abstractmethod
    async def async_get_artwork_data(self, artwork_id: str) -> bytes | None:
        """Download/retrieve artwork data.

        Args:
            artwork_id: Artwork identifier from async_load_artworks

        Returns:
            Image data as bytes, or None if failed
        """

    async def async_initialize(self) -> bool:
        """Initialize the provider.

        Returns:
            True if initialization successful
        """
        self._enabled = self.is_enabled()
        if not self._enabled:
            _LOGGER.debug("Provider %s is disabled", self.name)
            return False

        try:
            self._artworks = await self.async_load_artworks()
            _LOGGER.info(
                "Provider %s loaded %d artworks",
                self.name,
                len(self._artworks)
            )
            self._last_error = None
            return True
        except Exception as exc:
            _LOGGER.error("Error initializing provider %s: %s", self.name, exc)
            self._last_error = str(exc)
            self._enabled = False
            return False

    async def async_refresh(self) -> None:
        """Refresh available artworks."""
        if not self._enabled:
            return

        try:
            self._artworks = await self.async_load_artworks()
            _LOGGER.debug("Provider %s refreshed: %d artworks", self.name, len(self._artworks))
            self._last_error = None
        except Exception as exc:
            _LOGGER.error("Error refreshing provider %s: %s", self.name, exc)
            self._last_error = str(exc)


class ProviderRegistry:
    """Registry for managing artwork providers."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._providers: dict[str, ArtworkProvider] = {}

    def register(self, provider: ArtworkProvider) -> None:
        """Register a provider."""
        self._providers[provider.config_key] = provider
        _LOGGER.debug("Registered provider: %s", provider.name)

    def get_provider(self, config_key: str) -> ArtworkProvider | None:
        """Get provider by config key."""
        return self._providers.get(config_key)

    def get_provider_by_name(self, name: str) -> ArtworkProvider | None:
        """Get provider by display name."""
        for provider in self._providers.values():
            if provider.name == name:
                return provider
        return None

    def get_all_providers(self) -> list[ArtworkProvider]:
        """Get all registered providers."""
        return list(self._providers.values())

    def get_enabled_providers(self) -> list[ArtworkProvider]:
        """Get all enabled providers."""
        return [p for p in self._providers.values() if p.enabled]

    async def async_initialize_all(self, config: dict[str, Any]) -> None:
        """Initialize all providers with config."""
        for provider_class in [MediaFolderProvider, GoogleArtsProvider, BingWallpaperProvider]:
            provider = provider_class(config)
            self.register(provider)
            await provider.async_initialize()

    async def async_load_all_artworks(self) -> dict[str, list[dict]]:
        """Load artworks from all enabled providers.

        Returns:
            Dict mapping provider name to artwork list
        """
        result = {}
        for provider in self.get_enabled_providers():
            try:
                artworks = await provider.async_load_artworks()
                result[provider.name] = artworks
            except Exception as exc:
                _LOGGER.error("Error loading artworks from %s: %s", provider.name, exc)
                result[provider.name] = []

        return result


# Import providers here to avoid circular imports
from .media_folder import MediaFolderProvider  # noqa: E402
from .google_arts import GoogleArtsProvider  # noqa: E402
from .bing_wallpaper import BingWallpaperProvider  # noqa: E402

__all__ = [
    "ArtworkProvider",
    "ProviderRegistry",
    "MediaFolderProvider",
    "GoogleArtsProvider",
    "BingWallpaperProvider",
]
