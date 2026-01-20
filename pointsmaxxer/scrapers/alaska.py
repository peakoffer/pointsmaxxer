from __future__ import annotations

"""Alaska Airlines Mileage Plan scraper for PointsMaxxer."""

import re
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from ..models import Award, CabinClass
from ..utils.mouse import HumanMouse
from .base import BaseScraper, register_scraper, ParseError


@register_scraper("alaska")
class AlaskaScraper(BaseScraper):
    """Scraper for Alaska Airlines Mileage Plan awards."""

    PROGRAM_CODE = "alaska"
    PROGRAM_NAME = "Alaska Mileage Plan"
    BASE_URL = "https://www.alaskaair.com"

    CABIN_MAP = {
        CabinClass.ECONOMY: "coach",
        CabinClass.PREMIUM_ECONOMY: "premium",
        CabinClass.BUSINESS: "business",
        CabinClass.FIRST: "first",
    }

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for Alaska award availability."""
        browser = await self._ensure_browser()
        cache = await self._ensure_cache()

        cache_key = f"alaska_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
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
                    ".flight-result, .no-flights-message",
                    timeout=30000
                )

                awards = await self._parse_results(page, origin, destination, date, cabin)
                cache.set(cache_key, [a.model_dump() for a in awards], ttl_hours=6)

            except Exception as e:
                raise ParseError(f"Failed to parse Alaska results: {e}")

        return awards

    def _build_search_url(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> str:
        """Build Alaska search URL."""
        date_str = date.strftime("%m/%d/%Y")
        cabin_code = self.CABIN_MAP.get(cabin, "coach")

        return (
            f"{self.BASE_URL}/shopping/flights/search"
            f"?A=1"  # Adults
            f"&FT=true"  # Award travel
            f"&O={origin}"
            f"&D={destination}"
            f"&OD={date_str}"
            f"&OT=ANY"
            f"&RT=false"  # One-way
            f"&ShopType=A"  # Award
            f"&C={cabin_code}"
        )

    async def _parse_results(
        self,
        page: Page,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Parse Alaska search results."""
        awards = []

        no_results = await page.query_selector(".no-flights-message")
        if no_results:
            return []

        flight_results = await page.query_selector_all(".flight-result, [data-testid='flight-row']")

        for result in flight_results:
            try:
                award = await self._parse_flight_result(result, origin, destination, cabin)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    async def _parse_flight_result(
        self,
        result,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> Optional[Award]:
        """Parse a single Alaska flight result."""
        try:
            flight_no_elem = await result.query_selector(".flight-number")
            flight_no = await flight_no_elem.inner_text() if flight_no_elem else "AS???"

            dep_time_elem = await result.query_selector(".depart-time")
            arr_time_elem = await result.query_selector(".arrive-time")

            dep_time = await dep_time_elem.inner_text() if dep_time_elem else "00:00"
            arr_time = await arr_time_elem.inner_text() if arr_time_elem else "00:00"

            duration_elem = await result.query_selector(".flight-duration")
            duration_text = await duration_elem.inner_text() if duration_elem else "0h 0m"
            duration_minutes = self._parse_duration(duration_text)

            miles_elem = await result.query_selector(".miles-required, .award-miles")
            miles_text = await miles_elem.inner_text() if miles_elem else "0"
            miles = self._parse_miles(miles_text)

            if miles <= 0:
                return None

            fees_elem = await result.query_selector(".taxes-fees")
            fees_text = await fees_elem.inner_text() if fees_elem else "$0"
            fees = self._parse_price(fees_text)

            # Alaska marks saver awards
            is_saver = False
            saver_elem = await result.query_selector(".saver-award, .saver")
            if saver_elem:
                is_saver = True

            # Determine operating carrier (Alaska partners with many airlines)
            operating_elem = await result.query_selector(".operated-by")
            airline_name = "Alaska Airlines"
            airline_code = "AS"
            if operating_elem:
                operating_text = await operating_elem.inner_text()
                carriers = {
                    "American": ("AA", "American Airlines"),
                    "Japan Airlines": ("JL", "Japan Airlines"),
                    "JAL": ("JL", "Japan Airlines"),
                    "Cathay": ("CX", "Cathay Pacific"),
                    "Qantas": ("QF", "Qantas"),
                    "Finnair": ("AY", "Finnair"),
                    "Emirates": ("EK", "Emirates"),
                    "Korean": ("KE", "Korean Air"),
                    "Singapore": ("SQ", "Singapore Airlines"),
                }
                for carrier_name, (code, full_name) in carriers.items():
                    if carrier_name in operating_text:
                        airline_code = code
                        airline_name = full_name
                        break

            aircraft_elem = await result.query_selector(".aircraft-type")
            aircraft = await aircraft_elem.inner_text() if aircraft_elem else None

            departure = self._parse_time(dep_time)
            arrival = self._parse_time(arr_time)

            flight = self.create_flight(
                flight_no=flight_no.strip(),
                airline_code=airline_code,
                airline_name=airline_name,
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
