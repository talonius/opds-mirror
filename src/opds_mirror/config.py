"""Load settings from a TOML file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    url: str
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.url


@dataclass
class Config:
    output_dir: Path
    servers: list[ServerConfig]
    library_dirs: list[Path] = field(default_factory=list)
    request_delay: float = 0.0
    timeout: float = 60.0
    user_agent: str = "opds-mirror/0.1"


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    base = path.parent
    if "output_dir" not in raw:
        raise ConfigError("config is missing 'output_dir'")

    servers_raw = raw.get("servers", [])
    if not servers_raw:
        raise ConfigError("config needs at least one [[servers]] entry")
    servers = []
    for entry in servers_raw:
        if isinstance(entry, str):
            entry = {"url": entry}
        if "url" not in entry:
            raise ConfigError("each [[servers]] entry needs a 'url'")
        servers.append(ServerConfig(url=entry["url"], name=entry.get("name", "")))

    def resolve(p: str) -> Path:
        q = Path(p).expanduser()
        return q if q.is_absolute() else (base / q).resolve()

    return Config(
        output_dir=resolve(raw["output_dir"]),
        servers=servers,
        library_dirs=[resolve(p) for p in raw.get("library_dirs", [])],
        request_delay=float(raw.get("request_delay", 0.0)),
        timeout=float(raw.get("timeout", 60.0)),
        user_agent=str(raw.get("user_agent", "opds-mirror/0.1")),
    )
