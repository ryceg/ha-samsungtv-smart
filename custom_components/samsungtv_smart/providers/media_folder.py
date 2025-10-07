"""Media folder artwork provider for Samsung Frame TV."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import ArtworkProvider

_LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class MediaFolderProvider(ArtworkProvider):
    """Provider that scans a local media folder for images."""

    @property
    def name(self) -> str:
        """Return provider name."""
        return "Media Folder"

    @property
    def config_key(self) -> str:
        """Return config option key."""
        return "media_folder"

    def _get_folder_path(self) -> Path | None:
        """Get configured folder path."""
        folder_path = self._config.get("media_folder_path")
        if not folder_path:
            _LOGGER.warning("Media folder path not configured")
            return None

        path = Path(folder_path)
        if not path.exists():
            _LOGGER.error("Media folder does not exist: %s", folder_path)
            return None

        if not path.is_dir():
            _LOGGER.error("Media folder path is not a directory: %s", folder_path)
            return None

        return path

    def _get_patterns(self) -> list[str]:
        """Get file patterns from config."""
        patterns = self._config.get("media_folder_patterns", "*.jpg,*.jpeg,*.png")
        if isinstance(patterns, str):
            return [p.strip() for p in patterns.split(",")]
        return patterns

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if file should be included."""
        # Check extension
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False

        # Check if it's a hidden file
        if file_path.name.startswith("."):
            return False

        # Check patterns
        patterns = self._get_patterns()
        for pattern in patterns:
            if file_path.match(pattern):
                return True

        # If no patterns match but extension is supported, include it
        if not patterns or patterns == ["*"]:
            return True

        return False

    async def async_load_artworks(self) -> list[dict]:
        """Load artworks from media folder."""
        folder_path = self._get_folder_path()
        if not folder_path:
            return []

        artworks = []
        recursive = self._config.get("media_folder_recursive", True)

        try:
            # Scan for image files
            if recursive:
                files = folder_path.rglob("*")
            else:
                files = folder_path.glob("*")

            for file_path in files:
                if not file_path.is_file():
                    continue

                if not self._should_include_file(file_path):
                    continue

                # Create artwork entry
                artwork = {
                    "id": str(file_path),
                    "source": self.name,
                    "title": file_path.stem,
                    "local_path": str(file_path),
                    "filename": file_path.name,
                }
                artworks.append(artwork)

            _LOGGER.debug("Found %d images in media folder: %s", len(artworks), folder_path)
            return artworks

        except Exception as exc:
            _LOGGER.error("Error scanning media folder %s: %s", folder_path, exc)
            return []

    async def async_get_artwork_data(self, artwork_id: str) -> bytes | None:
        """Read artwork data from file.

        Args:
            artwork_id: File path as string

        Returns:
            Image data as bytes
        """
        try:
            file_path = Path(artwork_id)
            if not file_path.exists():
                _LOGGER.error("Artwork file not found: %s", artwork_id)
                return None

            with open(file_path, "rb") as f:
                data = f.read()

            _LOGGER.debug("Read %d bytes from %s", len(data), file_path.name)
            return data

        except Exception as exc:
            _LOGGER.error("Error reading artwork file %s: %s", artwork_id, exc)
            return None
