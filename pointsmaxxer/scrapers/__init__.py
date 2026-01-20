from __future__ import annotations

"""Scraper modules for PointsMaxxer."""

from .base import BaseScraper, ScraperRegistry
from .aa import AAScraper
from .united import UnitedScraper
from .delta import DeltaScraper
from .aeroplan import AeroplanScraper
from .alaska import AlaskaScraper
from .ba import BAScraper
from .seats_aero import SeatsAeroScraper
from .google_flights import GoogleFlightsScraper
from .demo import DemoScraper, get_demo_cash_price

__all__ = [
    "BaseScraper",
    "ScraperRegistry",
    "AAScraper",
    "UnitedScraper",
    "DeltaScraper",
    "AeroplanScraper",
    "AlaskaScraper",
    "BAScraper",
    "SeatsAeroScraper",
    "GoogleFlightsScraper",
    "DemoScraper",
    "get_demo_cash_price",
]
