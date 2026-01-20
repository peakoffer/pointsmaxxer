from __future__ import annotations

"""Booking link generator for PointsMaxxer.

Generates deep links to airline award booking pages.
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from .models import Award, Deal, CabinClass


# Cabin class mappings per airline
CABIN_CODES = {
    "aa": {
        CabinClass.ECONOMY: "COACH",
        CabinClass.PREMIUM_ECONOMY: "PREMIUM_ECONOMY",
        CabinClass.BUSINESS: "BUSINESS",
        CabinClass.FIRST: "FIRST",
    },
    "united": {
        CabinClass.ECONOMY: "economy",
        CabinClass.PREMIUM_ECONOMY: "premium-economy",
        CabinClass.BUSINESS: "business",
        CabinClass.FIRST: "first",
    },
    "delta": {
        CabinClass.ECONOMY: "MAIN",
        CabinClass.PREMIUM_ECONOMY: "PREMIUM_SELECT",
        CabinClass.BUSINESS: "DELTA_ONE",
        CabinClass.FIRST: "FIRST",
    },
    "aeroplan": {
        CabinClass.ECONOMY: "economy",
        CabinClass.PREMIUM_ECONOMY: "premium-economy",
        CabinClass.BUSINESS: "business",
        CabinClass.FIRST: "first",
    },
    "alaska": {
        CabinClass.ECONOMY: "Coach",
        CabinClass.PREMIUM_ECONOMY: "PremiumClass",
        CabinClass.BUSINESS: "First",  # Alaska calls business "First" on partners
        CabinClass.FIRST: "First",
    },
    "ba": {
        CabinClass.ECONOMY: "M",
        CabinClass.PREMIUM_ECONOMY: "W",
        CabinClass.BUSINESS: "J",
        CabinClass.FIRST: "F",
    },
}


def generate_booking_url(award: Award) -> Optional[str]:
    """Generate a booking URL for an award.

    Args:
        award: The Award object containing flight and program details.

    Returns:
        A URL string to the airline's award booking page, or None if unsupported.
    """
    program = award.program.lower()
    flight = award.flight

    generators = {
        "aa": _generate_aa_url,
        "united": _generate_united_url,
        "delta": _generate_delta_url,
        "aeroplan": _generate_aeroplan_url,
        "alaska": _generate_alaska_url,
        "ba": _generate_ba_url,
    }

    generator = generators.get(program)
    if generator:
        return generator(award)

    return None


def generate_booking_url_from_deal(deal: Deal) -> Optional[str]:
    """Generate a booking URL from a Deal object."""
    return generate_booking_url(deal.award)


def _format_date_aa(dt: datetime) -> str:
    """Format date for AA: YYYY-MM-DD"""
    return dt.strftime("%Y-%m-%d")


def _format_date_united(dt: datetime) -> str:
    """Format date for United: YYYY-MM-DD"""
    return dt.strftime("%Y-%m-%d")


def _format_date_delta(dt: datetime) -> str:
    """Format date for Delta: YYYYMMDD"""
    return dt.strftime("%Y%m%d")


def _format_date_aeroplan(dt: datetime) -> str:
    """Format date for Aeroplan: YYYY-MM-DD"""
    return dt.strftime("%Y-%m-%d")


def _format_date_alaska(dt: datetime) -> str:
    """Format date for Alaska: MM/DD/YYYY"""
    return dt.strftime("%m/%d/%Y")


def _format_date_ba(dt: datetime) -> str:
    """Format date for BA: YYYYMMDD"""
    return dt.strftime("%Y%m%d")


def _generate_aa_url(award: Award) -> str:
    """Generate American Airlines award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["aa"].get(award.cabin, "BUSINESS")

    params = {
        "originAirport": flight.origin,
        "destinationAirport": flight.destination,
        "departureDate": _format_date_aa(flight.departure),
        "tripType": "OneWay",
        "cabinType": cabin,
        "awardTravel": "true",
        "passengers": "1",
    }

    base_url = "https://www.aa.com/booking/find-flights"
    return f"{base_url}?{urlencode(params)}"


def _generate_united_url(award: Award) -> str:
    """Generate United Airlines award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["united"].get(award.cabin, "business")

    params = {
        "f": flight.origin,
        "t": flight.destination,
        "d": _format_date_united(flight.departure),
        "tt": "1",  # One way
        "ct": cabin,
        "px": "1",
        "taxng": "1",
        "idx": "1",
        "st": "bestmatches",
        "at": "1",  # Award travel
    }

    base_url = "https://www.united.com/en/us/fsr/choose-flights"
    return f"{base_url}?{urlencode(params)}"


def _generate_delta_url(award: Award) -> str:
    """Generate Delta award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["delta"].get(award.cabin, "DELTA_ONE")

    params = {
        "action": "findFlights",
        "tripType": "ONE_WAY",
        "priceSchedule": "price",
        "paxCount": "1",
        "searchByCabin": "true",
        "cabinFareClass": cabin,
        "awardTravel": "true",
        "departureDate": _format_date_delta(flight.departure),
        "originCity": flight.origin,
        "destinationCity": flight.destination,
    }

    base_url = "https://www.delta.com/flight-search/book-a-flight"
    return f"{base_url}?{urlencode(params)}"


def _generate_aeroplan_url(award: Award) -> str:
    """Generate Air Canada Aeroplan award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["aeroplan"].get(award.cabin, "business")

    # Map cabin to Aeroplan's market/cabin format
    cabin_param = cabin

    params = {
        "org0": flight.origin,
        "dest0": flight.destination,
        "departureDate0": _format_date_aeroplan(flight.departure),
        "ADT": "1",
        "YTH": "0",
        "CHD": "0",
        "INF": "0",
        "INS": "0",
        "tripType": "O",  # One way
        "marketCode": "INT",
        "cabinClass": cabin_param,
        "awardBooking": "true",
    }

    base_url = "https://www.aircanada.com/aeroplan/redeem/availability/outbound"
    return f"{base_url}?{urlencode(params)}"


def _generate_alaska_url(award: Award) -> str:
    """Generate Alaska Airlines award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["alaska"].get(award.cabin, "First")

    params = {
        "O": flight.origin,
        "D": flight.destination,
        "OD": _format_date_alaska(flight.departure),
        "A": "1",  # Adults
        "C": "0",  # Children
        "IR": "1",  # Award travel
        "FT": cabin,
    }

    base_url = "https://www.alaskaair.com/search/results"
    return f"{base_url}?{urlencode(params)}"


def _generate_ba_url(award: Award) -> str:
    """Generate British Airways Avios award booking URL."""
    flight = award.flight
    cabin = CABIN_CODES["ba"].get(award.cabin, "J")

    params = {
        "eId": "111099",
        "from": flight.origin,
        "to": flight.destination,
        "depDate": _format_date_ba(flight.departure),
        "cabin": cabin,
        "adult": "1",
        "child": "0",
        "infant": "0",
        "redemption": "AVIOS_PART_PAY",
    }

    base_url = "https://www.britishairways.com/travel/redeem/execclub/_gf/en_us"
    return f"{base_url}?{urlencode(params)}"


def get_booking_url_display(award: Award) -> str:
    """Get a display-friendly booking URL or message.

    Returns the URL if available, or a message indicating
    the program doesn't have direct booking links.
    """
    url = generate_booking_url(award)
    if url:
        return url
    return f"[Visit {award.program} website to book]"
