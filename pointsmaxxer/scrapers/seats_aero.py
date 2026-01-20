from __future__ import annotations

"""Seats.aero API scraper for PointsMaxxer.

Seats.aero is a third-party award search aggregator that provides
API access to award availability across multiple programs.
"""

from datetime import datetime
from typing import Optional

import httpx

from ..models import Award, CabinClass, Flight, FlightAmenities
from .base import BaseScraper, register_scraper, ParseError, RateLimitError


@register_scraper("seats_aero")
class SeatsAeroScraper(BaseScraper):
    """Scraper using Seats.aero API."""

    PROGRAM_CODE = "seats_aero"
    PROGRAM_NAME = "Seats.aero"
    BASE_URL = "https://seats.aero/api"

    # Seats.aero program mappings
    PROGRAM_MAP = {
        "united": "united",
        "aeroplan": "aeroplan",
        "aa": "american",
        "delta": "delta",
        "alaska": "alaska",
        "virgin_atlantic": "virgin-atlantic",
        "flying_blue": "flying-blue",
        "ana": "ana",
        "singapore": "singapore",
        "cathay": "cathay",
        "emirates": "emirates",
        "qantas": "qantas",
        "ba_avios": "avios",
    }

    CABIN_MAP = {
        CabinClass.ECONOMY: "economy",
        CabinClass.PREMIUM_ECONOMY: "premium",
        CabinClass.BUSINESS: "business",
        CabinClass.FIRST: "first",
    }

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize Seats.aero scraper.

        Args:
            api_key: Seats.aero API key. Required for API access.
            **kwargs: Additional arguments passed to BaseScraper.
        """
        super().__init__(**kwargs)
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is available."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
        programs: Optional[list[str]] = None,
    ) -> list[Award]:
        """Search for award availability via Seats.aero API.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            date: Search date.
            cabin: Cabin class.
            programs: Optional list of program codes to search.

        Returns:
            List of available awards.
        """
        cache = await self._ensure_cache()

        cache_key = f"seats_aero_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
        cached = cache.get(cache_key)
        if cached:
            return [Award.model_validate(a) for a in cached]

        client = await self._ensure_client()

        try:
            params = {
                "origin": origin,
                "destination": destination,
                "date": date.strftime("%Y-%m-%d"),
                "cabin": self.CABIN_MAP.get(cabin, "economy"),
            }

            if programs:
                params["programs"] = ",".join(programs)

            response = await client.get("/availability", params=params)

            if response.status_code == 429:
                raise RateLimitError("Seats.aero rate limit exceeded")

            if response.status_code != 200:
                raise ParseError(f"Seats.aero API error: {response.status_code}")

            data = response.json()
            awards = self._parse_response(data, origin, destination, cabin)

            cache.set(cache_key, [a.model_dump() for a in awards], ttl_hours=6)
            return awards

        except httpx.HTTPError as e:
            raise ParseError(f"Seats.aero request failed: {e}")

    def _parse_response(
        self,
        data: dict,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> list[Award]:
        """Parse Seats.aero API response."""
        awards = []

        results = data.get("results", [])
        for result in results:
            try:
                award = self._parse_result(result, origin, destination, cabin)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    def _parse_result(
        self,
        result: dict,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> Optional[Award]:
        """Parse a single Seats.aero result."""
        try:
            # Extract flight info
            flight_data = result.get("flight", {})
            flight_no = flight_data.get("number", "???")
            airline_code = flight_data.get("airline", "??")
            airline_name = flight_data.get("airline_name", "")

            departure_str = flight_data.get("departure")
            arrival_str = flight_data.get("arrival")

            if departure_str:
                departure = datetime.fromisoformat(departure_str.replace("Z", "+00:00"))
            else:
                departure = datetime.now()

            if arrival_str:
                arrival = datetime.fromisoformat(arrival_str.replace("Z", "+00:00"))
            else:
                arrival = datetime.now()

            duration = flight_data.get("duration_minutes", 0)
            aircraft = flight_data.get("aircraft")
            stops = flight_data.get("stops", 0)

            # Extract award info
            program = result.get("program", "")
            program_name = result.get("program_name", "")
            miles = result.get("miles", 0)
            cash_fees = result.get("taxes", 0.0)
            is_saver = result.get("is_saver", False)
            availability = result.get("seats", 1)

            if miles <= 0:
                return None

            # Map cabin from response
            result_cabin_str = result.get("cabin", "economy")
            cabin_map_reverse = {v: k for k, v in self.CABIN_MAP.items()}
            result_cabin = cabin_map_reverse.get(result_cabin_str, cabin)

            flight = Flight(
                flight_no=flight_no,
                airline_code=airline_code,
                airline_name=airline_name,
                origin=origin,
                destination=destination,
                departure=departure,
                arrival=arrival,
                duration_minutes=duration,
                aircraft=aircraft,
                stops=stops,
                amenities=FlightAmenities(),
            )

            return Award(
                flight=flight,
                program=program,
                program_name=program_name,
                miles=miles,
                cash_fees=cash_fees,
                cabin=result_cabin,
                is_saver=is_saver,
                availability=availability,
                scraped_at=datetime.now(),
                source="seats.aero",
            )

        except Exception:
            return None

    async def search_all_programs(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search all supported programs via Seats.aero.

        This is the primary method for getting comprehensive award availability.
        """
        return await self.search_awards(
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
            programs=None,  # Search all
        )

    async def close(self) -> None:
        """Cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
        await super().close()
