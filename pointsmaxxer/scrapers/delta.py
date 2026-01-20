from __future__ import annotations

"""Delta SkyMiles scraper for PointsMaxxer."""

import re
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from ..models import Award, CabinClass
from ..utils.mouse import HumanMouse
from .base import BaseScraper, register_scraper, ParseError


@register_scraper("delta")
class DeltaScraper(BaseScraper):
    """Scraper for Delta SkyMiles awards."""

    PROGRAM_CODE = "delta"
    PROGRAM_NAME = "Delta SkyMiles"
    BASE_URL = "https://www.delta.com"

    CABIN_MAP = {
        CabinClass.ECONOMY: "MAIN",
        CabinClass.PREMIUM_ECONOMY: "PREM",
        CabinClass.BUSINESS: "BUS",
        CabinClass.FIRST: "FIRST",
    }

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for Delta award availability."""
        browser = await self._ensure_browser()
        cache = await self._ensure_cache()

        cache_key = f"delta_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
        cached = cache.get(cache_key)
        if cached:
            return [Award.model_validate(a) for a in cached]

        awards = []

        async with browser.get_page() as page:
            mouse = HumanMouse(page)

            try:
                search_url = self._build_search_url(origin, destination, date, cabin)
                await page.goto(search_url, wait_until="networkidle")

                await page.wait_for_selector(
                    ".flight-results, .search-results, .no-results",
                    timeout=30000
                )

                awards = await self._parse_results(page, origin, destination, date, cabin)
                cache.set(cache_key, [a.model_dump() for a in awards], ttl_hours=6)

            except Exception as e:
                raise ParseError(f"Failed to parse Delta results: {e}")

        return awards

    def _build_search_url(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> str:
        """Build Delta search URL."""
        date_str = date.strftime("%m/%d/%Y")
        cabin_code = self.CABIN_MAP.get(cabin, "MAIN")

        return (
            f"{self.BASE_URL}/flight-search/book-a-flight"
            f"?cacheKeySuffix=award"
            f"&tripType=ONE_WAY"
            f"&paxCount=1"
            f"&originCity={origin}"
            f"&destinationCity={destination}"
            f"&departureDate={date_str}"
            f"&selectedCabin={cabin_code}"
            f"&awardTravel=true"
        )

    async def _parse_results(
        self,
        page: Page,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Parse Delta search results."""
        awards = []

        no_results = await page.query_selector(".no-results, .no-flights")
        if no_results:
            return []

        flight_cards = await page.query_selector_all(
            ".flight-card, [data-testid='flight-card']"
        )

        for card in flight_cards:
            try:
                award = await self._parse_flight_card(card, origin, destination, cabin)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    async def _parse_flight_card(
        self,
        card,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> Optional[Award]:
        """Parse a single Delta flight card."""
        try:
            flight_no_elem = await card.query_selector(
                ".flight-number, [data-testid='flight-number']"
            )
            flight_no = await flight_no_elem.inner_text() if flight_no_elem else "DL???"

            dep_time_elem = await card.query_selector(".departure-time")
            arr_time_elem = await card.query_selector(".arrival-time")

            dep_time = await dep_time_elem.inner_text() if dep_time_elem else "00:00"
            arr_time = await arr_time_elem.inner_text() if arr_time_elem else "00:00"

            duration_elem = await card.query_selector(".duration, .flight-duration")
            duration_text = await duration_elem.inner_text() if duration_elem else "0h 0m"
            duration_minutes = self._parse_duration(duration_text)

            miles_elem = await card.query_selector(".miles, .award-miles")
            miles_text = await miles_elem.inner_text() if miles_elem else "0"
            miles = self._parse_miles(miles_text)

            if miles <= 0:
                return None

            fees_elem = await card.query_selector(".taxes, .cash-price")
            fees_text = await fees_elem.inner_text() if fees_elem else "$0"
            fees = self._parse_price(fees_text)

            aircraft_elem = await card.query_selector(".aircraft")
            aircraft = await aircraft_elem.inner_text() if aircraft_elem else None

            departure = self._parse_time(dep_time)
            arrival = self._parse_time(arr_time)

            # Delta awards are typically not marked as "saver" but they have
            # partner availability which functions similarly
            is_saver = False
            partner_elem = await card.query_selector(".partner-award")
            if partner_elem:
                is_saver = True

            flight = self.create_flight(
                flight_no=flight_no.strip(),
                airline_code="DL",
                airline_name="Delta Air Lines",
                origin=origin,
                destination=destination,
                departure=departure,
                arrival=arrival,
                duration_minutes=duration_minutes,
                aircraft=aircraft,
            )

            return self.create_award(
                flight=flight,
                miles=miles,
                cabin=cabin,
                cash_fees=fees,
                is_saver=is_saver,
            )

        except Exception:
            return None

    def _parse_duration(self, text: str) -> int:
        match = re.search(r"(\d+)h\s*(\d+)?m?", text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) if match.group(2) else 0
            return hours * 60 + minutes
        return 0

    def _parse_miles(self, text: str) -> int:
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else 0

    def _parse_price(self, text: str) -> float:
        match = re.search(r"\$?([\d,]+(?:\.\d{2})?)", text)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0

    def _parse_time(self, text: str) -> datetime:
        now = datetime.now()
        try:
            text = text.strip().upper()
            if "AM" in text or "PM" in text:
                time_obj = datetime.strptime(text, "%I:%M %p")
            else:
                time_obj = datetime.strptime(text, "%H:%M")
            return now.replace(
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return now
