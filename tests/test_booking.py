"""Tests for the booking link generator."""

from datetime import datetime

import pytest

from pointsmaxxer.booking import (
    generate_booking_url,
    generate_booking_url_from_deal,
    get_booking_url_display,
)
from pointsmaxxer.models import Award, Deal, Flight, CabinClass


@pytest.fixture
def sample_flight():
    """Create a sample flight."""
    return Flight(
        flight_no="NH7",
        airline_code="NH",
        airline_name="ANA",
        origin="SFO",
        destination="NRT",
        departure=datetime(2025, 6, 15, 10, 30),
        arrival=datetime(2025, 6, 16, 14, 30),
        duration_minutes=660,
    )


@pytest.fixture
def sample_aa_award(sample_flight):
    """Create a sample AA award."""
    return Award(
        flight=sample_flight,
        program="aa",
        miles=70000,
        cash_fees=5.60,
        cabin=CabinClass.BUSINESS,
        is_saver=True,
    )


@pytest.fixture
def sample_united_award(sample_flight):
    """Create a sample United award."""
    return Award(
        flight=sample_flight,
        program="united",
        miles=80000,
        cash_fees=25.00,
        cabin=CabinClass.FIRST,
        is_saver=False,
    )


@pytest.fixture
def sample_aeroplan_award(sample_flight):
    """Create a sample Aeroplan award."""
    return Award(
        flight=sample_flight,
        program="aeroplan",
        miles=75000,
        cash_fees=150.00,
        cabin=CabinClass.BUSINESS,
        is_saver=True,
    )


@pytest.fixture
def sample_deal(sample_aa_award):
    """Create a sample deal."""
    return Deal(
        award=sample_aa_award,
        cash_price=5000.00,
        cpp=7.1,
        is_unicorn=True,
    )


class TestGenerateBookingUrl:
    """Tests for generate_booking_url function."""

    def test_aa_url_generation(self, sample_aa_award):
        """Test AA booking URL generation."""
        url = generate_booking_url(sample_aa_award)

        assert url is not None
        assert "aa.com" in url
        assert "SFO" in url
        assert "NRT" in url
        assert "2025-06-15" in url
        assert "awardTravel=true" in url
        assert "BUSINESS" in url

    def test_united_url_generation(self, sample_united_award):
        """Test United booking URL generation."""
        url = generate_booking_url(sample_united_award)

        assert url is not None
        assert "united.com" in url
        assert "f=SFO" in url
        assert "t=NRT" in url
        assert "at=1" in url  # Award travel flag

    def test_aeroplan_url_generation(self, sample_aeroplan_award):
        """Test Aeroplan booking URL generation."""
        url = generate_booking_url(sample_aeroplan_award)

        assert url is not None
        assert "aircanada.com" in url
        assert "org0=SFO" in url
        assert "dest0=NRT" in url
        assert "awardBooking=true" in url

    def test_delta_url_generation(self, sample_flight):
        """Test Delta booking URL generation."""
        award = Award(
            flight=sample_flight,
            program="delta",
            miles=85000,
            cash_fees=5.60,
            cabin=CabinClass.BUSINESS,
        )
        url = generate_booking_url(award)

        assert url is not None
        assert "delta.com" in url
        assert "SFO" in url
        assert "NRT" in url
        assert "awardTravel=true" in url

    def test_alaska_url_generation(self, sample_flight):
        """Test Alaska booking URL generation."""
        award = Award(
            flight=sample_flight,
            program="alaska",
            miles=70000,
            cash_fees=12.50,
            cabin=CabinClass.FIRST,
        )
        url = generate_booking_url(award)

        assert url is not None
        assert "alaskaair.com" in url
        assert "O=SFO" in url
        assert "D=NRT" in url
        assert "IR=1" in url  # Award travel flag

    def test_ba_url_generation(self, sample_flight):
        """Test British Airways booking URL generation."""
        award = Award(
            flight=sample_flight,
            program="ba",
            miles=100000,
            cash_fees=500.00,
            cabin=CabinClass.FIRST,
        )
        url = generate_booking_url(award)

        assert url is not None
        assert "britishairways.com" in url
        assert "from=SFO" in url
        assert "to=NRT" in url
        assert "cabin=F" in url  # First class

    def test_unsupported_program_returns_none(self, sample_flight):
        """Test that unsupported programs return None."""
        award = Award(
            flight=sample_flight,
            program="unknown_airline",
            miles=50000,
            cabin=CabinClass.ECONOMY,
        )
        url = generate_booking_url(award)

        assert url is None


class TestGenerateBookingUrlFromDeal:
    """Tests for generate_booking_url_from_deal function."""

    def test_generates_url_from_deal(self, sample_deal):
        """Test URL generation from a deal object."""
        url = generate_booking_url_from_deal(sample_deal)

        assert url is not None
        assert "aa.com" in url


class TestGetBookingUrlDisplay:
    """Tests for get_booking_url_display function."""

    def test_returns_url_for_supported_program(self, sample_aa_award):
        """Test that supported programs return URLs."""
        display = get_booking_url_display(sample_aa_award)

        assert "aa.com" in display
        assert display.startswith("http")

    def test_returns_message_for_unsupported_program(self, sample_flight):
        """Test that unsupported programs return a message."""
        award = Award(
            flight=sample_flight,
            program="unknown",
            miles=50000,
            cabin=CabinClass.ECONOMY,
        )
        display = get_booking_url_display(award)

        assert "unknown" in display
        assert "Visit" in display


class TestCabinClassMappings:
    """Test that cabin class mappings work correctly."""

    def test_economy_cabin(self, sample_flight):
        """Test economy cabin URL generation."""
        award = Award(
            flight=sample_flight,
            program="aa",
            miles=35000,
            cabin=CabinClass.ECONOMY,
        )
        url = generate_booking_url(award)

        assert "COACH" in url

    def test_premium_economy_cabin(self, sample_flight):
        """Test premium economy cabin URL generation."""
        award = Award(
            flight=sample_flight,
            program="aa",
            miles=50000,
            cabin=CabinClass.PREMIUM_ECONOMY,
        )
        url = generate_booking_url(award)

        assert "PREMIUM_ECONOMY" in url

    def test_first_cabin(self, sample_flight):
        """Test first class cabin URL generation."""
        award = Award(
            flight=sample_flight,
            program="aa",
            miles=110000,
            cabin=CabinClass.FIRST,
        )
        url = generate_booking_url(award)

        assert "FIRST" in url
