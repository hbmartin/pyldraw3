"""Read and write pyldraw configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from ldraw.dirs import get_cache_dir, get_config_dir, get_data_dir

CONFIG_FILE = Path(get_config_dir()) / "config.yml"


def get_config(config_file: str | Path | None = None) -> Path:
    """Return the given configuration file path, or the default location.

    This never inspects ``sys.argv``: pyldraw is a library, and embedding
    applications own their own command lines.
    """
    return CONFIG_FILE if config_file is None else Path(config_file)


class Config:
    """Configuration settings for pyldraw."""

    ldraw_library_path: str
    generated_path: str

    def __init__(
        self,
        ldraw_library_path: str | None = None,
        generated_path: str | None = None,
    ) -> None:
        self.ldraw_library_path = (
            ldraw_library_path
            if ldraw_library_path is not None
            else str(Path(get_cache_dir()) / "complete")
        )
        self.generated_path = (
            generated_path
            if generated_path is not None
            else str(Path(get_data_dir()) / "generated")
        )

    @classmethod
    def load(cls, config_file: str | Path | None = None) -> Config:
        """Load configuration from YAML file or create default configuration."""
        config_path = get_config(config_file)

        try:
            with config_path.open() as config_file_handle:
                cfg = yaml.load(config_file_handle, Loader=yaml.SafeLoader) or {}
                return cls(
                    ldraw_library_path=cfg.get("ldraw_library_path"),
                    generated_path=cfg.get("generated_path"),
                )
        except FileNotFoundError:
            return cls()

    def __str__(self) -> str:
        return f"Config({self.ldraw_library_path=}, {self.generated_path=})"

    def to_dict(self) -> dict[str, str]:
        """Return public configuration values for serialization."""
        written = {}
        if self.ldraw_library_path is not None:
            written["ldraw_library_path"] = self.ldraw_library_path
        if self.generated_path is not None:
            written["generated_path"] = self.generated_path
        return written

    def write(self, config_file: str | Path | None = None) -> None:
        """Write the config to config.yml."""
        config_path = get_config(config_file=config_file)

        with config_path.open("w") as config_file_handle:
            yaml.dump(self.to_dict(), config_file_handle)
