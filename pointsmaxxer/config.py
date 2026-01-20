from __future__ import annotations

"""Configuration loader for PointsMaxxer."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from .models import AppConfig, CabinClass, Route, PointsProgram, Settings, AlertConfig


DEFAULT_CONFIG_PATHS = [
    Path("config.yaml"),
    Path("config.yml"),
    Path.home() / ".config" / "pointsmaxxer" / "config.yaml",
    Path.home() / ".pointsmaxxer" / "config.yaml",
]


def find_config_file() -> Optional[Path]:
    """Find the configuration file in standard locations."""
    env_path = os.environ.get("POINTSMAXXER_CONFIG")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            return path

    return None


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        AppConfig object with loaded configuration.

    Raises:
        FileNotFoundError: If no config file is found.
        ValidationError: If config file is invalid.
    """
    if config_path is None:
        config_path = find_config_file()

    if config_path is None or not config_path.exists():
        return create_default_config()

    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        return create_default_config()

    return parse_config(raw_config)


def parse_config(raw: dict) -> AppConfig:
    """Parse raw YAML config into AppConfig."""
    portfolio = []
    for item in raw.get("portfolio", []):
        portfolio.append(PointsProgram(
            name=item.get("name", ""),
            code=item.get("code", ""),
            balance=item.get("balance", 0),
            transfer_partners=item.get("transfer_partners", []),
            transfer_ratio=item.get("transfer_ratio", 1.0),
        ))

    routes = []
    for item in raw.get("routes", []):
        cabin_str = item.get("cabin", "economy")
        try:
            cabin = CabinClass(cabin_str.lower())
        except ValueError:
            cabin = CabinClass.ECONOMY

        routes.append(Route(
            origin=item.get("origin", ""),
            destination=item.get("destination", ""),
            cabin=cabin,
            flexible_dates=item.get("flexible_dates", True),
        ))

    raw_settings = raw.get("settings", {})
    settings = Settings(
        home_airports=raw_settings.get("home_airports", ["SFO"]),
        unicorn_threshold_cpp=raw_settings.get("unicorn_threshold_cpp", 7.0),
        search_window_days=raw_settings.get("search_window_days", 90),
        flexible_days=raw_settings.get("flexible_days", 3),
        scan_frequency=raw_settings.get("scan_frequency", "daily"),
        max_stops=raw_settings.get("max_stops", 1),
        cache_ttl_hours=raw_settings.get("cache_ttl_hours", 6),
        request_delay_seconds=raw_settings.get("request_delay_seconds", 2.0),
    )

    raw_alerts = raw.get("alerts", {})
    alerts = AlertConfig(
        terminal=raw_alerts.get("terminal", True),
        email=raw_alerts.get("email"),
        slack_webhook=raw_alerts.get("slack_webhook"),
        discord_webhook=raw_alerts.get("discord_webhook"),
    )

    return AppConfig(
        portfolio=portfolio,
        transfers=raw.get("transfers", {}),
        routes=routes,
        settings=settings,
        alerts=alerts,
    )


def create_default_config() -> AppConfig:
    """Create a default configuration."""
    return AppConfig(
        portfolio=[],
        transfers={},
        routes=[],
        settings=Settings(),
        alerts=AlertConfig(),
    )


def save_config(config: AppConfig, config_path: Path) -> None:
    """Save configuration to YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "portfolio": [
            {
                "name": p.name,
                "code": p.code,
                "balance": p.balance,
            }
            for p in config.portfolio
        ],
        "transfers": config.transfers,
        "routes": [
            {
                "origin": r.origin,
                "destination": r.destination,
                "cabin": r.cabin.value,
                "flexible_dates": r.flexible_dates,
            }
            for r in config.routes
        ],
        "settings": {
            "home_airports": config.settings.home_airports,
            "unicorn_threshold_cpp": config.settings.unicorn_threshold_cpp,
            "search_window_days": config.settings.search_window_days,
            "flexible_days": config.settings.flexible_days,
            "scan_frequency": config.settings.scan_frequency.value,
            "max_stops": config.settings.max_stops,
            "cache_ttl_hours": config.settings.cache_ttl_hours,
            "request_delay_seconds": config.settings.request_delay_seconds,
        },
        "alerts": {
            "terminal": config.alerts.terminal,
            "email": config.alerts.email,
            "slack_webhook": config.alerts.slack_webhook,
            "discord_webhook": config.alerts.discord_webhook,
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_config_path() -> Path:
    """Get the path where config should be stored."""
    found = find_config_file()
    if found:
        return found
    return Path("config.yaml")


# Transfer partner mappings - static data
TRANSFER_PARTNERS = {
    "chase_ur": {
        "united": 1.0,
        "aeroplan": 1.0,
        "virgin_atlantic": 1.0,
        "ba_avios": 1.0,
        "hyatt": 1.0,
        "southwest": 1.0,
        "iberia": 1.0,
        "flying_blue": 1.0,
        "singapore": 1.0,
    },
    "amex_mr": {
        "delta": 1.0,
        "ana": 1.0,
        "virgin_atlantic": 1.0,
        "ba_avios": 1.0,
        "singapore": 1.0,
        "cathay": 1.0,
        "flying_blue": 1.0,
        "emirates": 1.0,
        "etihad": 1.0,
        "avianca": 1.0,
    },
    "cap_one": {
        "turkish": 1.0,
        "avianca": 1.0,
        "flying_blue": 1.0,
        "ba_avios": 1.0,
        "virgin_atlantic": 1.0,
        "singapore": 1.0,
        "emirates": 1.0,
        "etihad": 1.0,
        "finnair": 1.0,
        "qantas": 1.0,
    },
    "bilt": {
        "aa": 1.0,
        "united": 1.0,
        "aeroplan": 1.0,
        "virgin_atlantic": 1.0,
        "turkish": 1.0,
        "flying_blue": 1.0,
        "alaska": 1.0,
        "emirates": 1.0,
        "cathay": 1.0,
    },
    "citi_typ": {
        "turkish": 1.0,
        "singapore": 1.0,
        "virgin_atlantic": 1.0,
        "flying_blue": 1.0,
        "cathay": 1.0,
        "qantas": 1.0,
        "etihad": 1.0,
        "thai": 1.0,
        "eva": 1.0,
    },
}

# Airline program codes and names
AIRLINE_PROGRAMS = {
    "aa": "American AAdvantage",
    "united": "United MileagePlus",
    "delta": "Delta SkyMiles",
    "aeroplan": "Air Canada Aeroplan",
    "alaska": "Alaska Mileage Plan",
    "ba_avios": "British Airways Avios",
    "virgin_atlantic": "Virgin Atlantic Flying Club",
    "ana": "ANA Mileage Club",
    "singapore": "Singapore KrisFlyer",
    "cathay": "Cathay Pacific Asia Miles",
    "flying_blue": "Air France/KLM Flying Blue",
    "turkish": "Turkish Miles&Smiles",
    "emirates": "Emirates Skywards",
    "etihad": "Etihad Guest",
    "qantas": "Qantas Frequent Flyer",
    "jal": "Japan Airlines Mileage Bank",
    "hyatt": "World of Hyatt",
    "southwest": "Southwest Rapid Rewards",
    "iberia": "Iberia Plus",
    "avianca": "Avianca LifeMiles",
    "finnair": "Finnair Plus",
    "thai": "Thai Royal Orchid Plus",
    "eva": "EVA Infinity MileageLands",
}
