from __future__ import annotations

"""Google Flights scraper for cash price baseline in PointsMaxxer."""

import re
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from ..models import CabinClass
from ..utils.mouse import HumanMouse
from .base import BaseScraper, register_scraper, ParseError


@register_scraper("google_flights")
class GoogleFlightsScraper(BaseScraper):
    """Scraper for Google Flights cash prices."""

    PROGRAM_CODE = "google_flights"
    PROGRAM_NAME = "Google Flights"
    BASE_URL = "https://www.google.com/travel/flights"

    CABIN_MAP = {
        CabinClass.ECONOMY: "1",
        CabinClass.PREMIUM_ECONOMY: "2",
        CabinClass.BUSINESS: "3",
        CabinClass.FIRST: "4",
    }

    async def search_awards(self, *args, **kwargs):
        """Not applicable for Google Flights."""
        return []

    async def get_cash_price(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> Optional[float]:
        """Get cash price for a route.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            date: Search date.
            cabin: Cabin class.

        Returns:
            Cash price in USD, or None if not found.
        """
        browser = await self._ensure_browser()
        cache = await self._ensure_cache()

        # Check cache first
        cache_key = f"gf_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
        cached = cache.get(cache_key, max_age_hours=24)
        if cached is not None:
            return cached

        async with browser.get_page() as page:
            mouse = HumanMouse(page)

            try:
                search_url = self._build_search_url(origin, destination, date, cabin)
                await page.goto(search_url, wait_until="networkidle")

                # Wait for results to load
                await page.wait_for_selector(
                    "[data-price], .price-text, .gws-flights-results__price",
                    timeout=30000
                )

                price = await self._extract_price(page)

                if price:
                    cache.set(cache_key, price, ttl_hours=24)

                return price

            except Exception as e:
                raise ParseError(f"Failed to get Google Flights price: {e}")

    def _build_search_url(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> str:
        """Build Google Flights search URL."""
        date_str = date.strftime("%Y-%m-%d")
        cabin_code = self.CABIN_MAP.get(cabin, "1")

        # Google Flights URL format
        return (
            f"{self.BASE_URL}/search"
            f"?tfs=CBwQAhooagcIARIDU0ZPEgoyMDI0LTAzLTAxcgwIAhIIL20vMDdkZmsYAXABggELCP___________wFAAUgBmAEC"
            f"&hl=en"
            f"&gl=us"
            f"&curr=USD"
        )

    async def _extract_price(self, page: Page) -> Optional[float]:
        """Extract the lowest price from the page."""
        try:
            # Try multiple selectors for price
            price_selectors = [
                "[data-price]",
                ".gws-flights-results__price",
                ".price-text",
                "[aria-label*='$']",
                ".YMlIz",  # Google's obfuscated class
            ]

            for selector in price_selectors:
                elements = await page.query_selector_all(selector)
                for elem in elements:
                    text = await elem.inner_text()
                    price = self._parse_price(text)
                    if price and price > 0:
                        return price

                    # Also check data-price attribute
                    data_price = await elem.get_attribute("data-price")
                    if data_price:
                        price = self._parse_price(data_price)
                        if price and price > 0:
                            return price

            return None

        except Exception:
            return None

    def _parse_price(self, text: str) -> Optional[float]:
        """Parse price from text."""
        if not text:
            return None

        # Remove currency symbols and commas
        match = re.search(r"\$?([\d,]+(?:\.\d{2})?)", text)
        if match:
            price_str = match.group(1).replace(",", "")
            return float(price_str)
        return None

    async def get_prices_for_range(
        self,
        origin: str,
        destination: str,
        start_date: datetime,
        end_date: datetime,
        cabin: CabinClass,
    ) -> dict[str, float]:
        """Get cash prices for a date range.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            start_date: Start of search range.
            end_date: End of search range.
            cabin: Cabin class.

        Returns:
            Dict mapping date strings to prices.
        """
        import asyncio

        prices = {}
        current_date = start_date

        while current_date <= end_date:
            try:
                price = await self.get_cash_price(origin, destination, current_date, cabin)
                if price:
                    prices[current_date.strftime("%Y-%m-%d")] = price
            except Exception:
                pass

            current_date = datetime(
                current_date.year,
                current_date.month,
                current_date.day + 1
            )

            # Delay between requests
            await asyncio.sleep(self.request_delay)

        return prices


class CashPriceFetcher:
    """Utility class for fetching cash prices."""

    def __init__(self, scraper: Optional[GoogleFlightsScraper] = None):
        """Initialize cash price fetcher.

        Args:
            scraper: Google Flights scraper instance.
        """
        self.scraper = scraper or GoogleFlightsScraper()

    async def get_price(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> Optional[float]:
        """Get cash price for a flight.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            date: Flight date.
            cabin: Cabin class.

        Returns:
            Price in USD or None.
        """
        return await self.scraper.get_cash_price(origin, destination, date, cabin)

    async def close(self) -> None:
        """Cleanup resources."""
        await self.scraper.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Fallback price estimates when scraping fails
FALLBACK_PRICES = {
    # (region_from, region_to, cabin): typical_price
    ("US", "US", CabinClass.ECONOMY): 200,
    ("US", "US", CabinClass.BUSINESS): 600,
    ("US", "US", CabinClass.FIRST): 1200,
    ("US", "EU", CabinClass.ECONOMY): 600,
    ("US", "EU", CabinClass.BUSINESS): 4000,
    ("US", "EU", CabinClass.FIRST): 8000,
    ("US", "ASIA", CabinClass.ECONOMY): 800,
    ("US", "ASIA", CabinClass.BUSINESS): 6000,
    ("US", "ASIA", CabinClass.FIRST): 12000,
}


def get_fallback_price(
    origin: str,
    destination: str,
    cabin: CabinClass,
) -> float:
    """Get a fallback price estimate when scraping fails.

    Args:
        origin: Origin airport.
        destination: Destination airport.
        cabin: Cabin class.

    Returns:
        Estimated price in USD.
    """
    # Simple region detection
    us_airports = {"SFO", "LAX", "JFK", "ORD", "DFW", "SEA", "MIA", "BOS", "ATL", "DEN"}
    eu_airports = {"LHR", "CDG", "FRA", "AMS", "FCO", "MAD", "MUC", "BCN", "DUB", "ZRH"}
    asia_airports = {"NRT", "HND", "HKG", "SIN", "ICN", "PVG", "BKK", "TPE", "KUL", "MNL"}

    def get_region(code: str) -> str:
        if code in us_airports:
            return "US"
        if code in eu_airports:
            return "EU"
        if code in asia_airports:
            return "ASIA"
        return "OTHER"

    origin_region = get_region(origin)
    dest_region = get_region(destination)

    key = (origin_region, dest_region, cabin)
    if key in FALLBACK_PRICES:
        return FALLBACK_PRICES[key]

    # Try reverse
    key = (dest_region, origin_region, cabin)
    if key in FALLBACK_PRICES:
        return FALLBACK_PRICES[key]

    # Default fallback
    defaults = {
        CabinClass.ECONOMY: 500,
        CabinClass.PREMIUM_ECONOMY: 1200,
        CabinClass.BUSINESS: 4000,
        CabinClass.FIRST: 10000,
    }
    return defaults.get(cabin, 1000)
