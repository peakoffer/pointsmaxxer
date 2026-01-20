"""Tests for Pydantic data models."""

from datetime import datetime

import pytest

from pointsmaxxer.models import (
    Award,
    CabinClass,
    Deal,
    Flight,
    FlightAmenities,
    PointsProgram,
    Route,
    AppConfig,
    Settings,
)


class TestPointsProgram:
    def test_create_program(self):
        program = PointsProgram(
            name="Chase Ultimate Rewards",
            code="chase_ur",
            balance=150000,
        )
        assert program.name == "Chase Ultimate Rewards"
        assert program.code == "chase_ur"
        assert program.balance == 150000
        assert program.transfer_ratio == 1.0

    def test_default_values(self):
        program = PointsProgram(name="Test", code="test")
        assert program.balance == 0
        assert program.transfer_partners == []
        assert program.transfer_ratio == 1.0


class TestRoute:
    def test_create_route(self):
        route = Route(
            origin="SFO",
            destination="NRT",
            cabin=CabinClass.BUSINESS,
        )
        assert route.origin == "SFO"
        assert route.destination == "NRT"
        assert route.cabin == CabinClass.BUSINESS
        assert route.flexible_dates is True

    def test_wildcard_destination(self):
        route = Route(origin="SFO", destination="*")
        assert route.is_wildcard_destination() is True

        route2 = Route(origin="SFO", destination="NRT")
        assert route2.is_wildcard_destination() is False


class TestFlight:
    def test_create_flight(self):
        flight = Flight(
            flight_no="NH7",
            airline_code="NH",
            airline_name="ANA",
            origin="SFO",
            destination="NRT",
            departure=datetime(2024, 3, 1, 10, 0),
            arrival=datetime(2024, 3, 2, 14, 0),
            duration_minutes=675,
        )
        assert flight.flight_no == "NH7"
        assert flight.duration_formatted == "11h15m"

    def test_duration_formatting(self):
        flight = Flight(
            flight_no="TEST",
            airline_code="XX",
            origin="AAA",
            destination="BBB",
            departure=datetime.now(),
            arrival=datetime.now(),
            duration_minutes=125,
        )
        assert flight.duration_formatted == "2h05m"


class TestAward:
    @pytest.fixture
    def sample_flight(self):
        return Flight(
            flight_no="NH7",
            airline_code="NH",
            origin="SFO",
            destination="NRT",
            departure=datetime.now(),
            arrival=datetime.now(),
            duration_minutes=675,
        )

    def test_create_award(self, sample_flight):
        award = Award(
            flight=sample_flight,
            program="ana",
            miles=85000,
            cash_fees=87.50,
            cabin=CabinClass.BUSINESS,
            is_saver=True,
        )
        assert award.miles == 85000
        assert award.is_saver is True
        assert "85,000 miles" in award.total_cost_description

    def test_total_cost_description(self, sample_flight):
        award = Award(
            flight=sample_flight,
            program="test",
            miles=100000,
            cash_fees=150.00,
            cabin=CabinClass.FIRST,
        )
        assert award.total_cost_description == "100,000 miles + $150.00"


class TestDeal:
    @pytest.fixture
    def sample_award(self):
        flight = Flight(
            flight_no="NH7",
            airline_code="NH",
            origin="SFO",
            destination="NRT",
            departure=datetime.now(),
            arrival=datetime.now(),
            duration_minutes=675,
        )
        return Award(
            flight=flight,
            program="ana",
            miles=85000,
            cash_fees=100,
            cabin=CabinClass.BUSINESS,
        )

    def test_create_deal(self, sample_award):
        deal = Deal(
            award=sample_award,
            cash_price=6200,
            cpp=7.2,
            is_unicorn=True,
        )
        assert deal.cpp == 7.2
        assert deal.is_unicorn is True

    def test_value_calculation(self, sample_award):
        deal = Deal(
            award=sample_award,
            cash_price=6200,
            cpp=7.2,
            is_unicorn=True,
        )
        # value = (cpp * miles) / 100 = (7.2 * 85000) / 100 = 6120
        assert deal.value_dollars == 6120.0

    def test_savings_calculation(self, sample_award):
        deal = Deal(
            award=sample_award,
            cash_price=6200,
            cpp=7.2,
            is_unicorn=True,
        )
        # savings = cash_price - fees = 6200 - 100 = 6100
        assert deal.savings_dollars == 6100.0


class TestAppConfig:
    def test_get_transfer_partners(self):
        config = AppConfig(
            transfers={
                "chase_ur": [
                    {"united": 1.0},
                    {"aeroplan": 1.0},
                ]
            }
        )
        partners = config.get_transfer_partners("chase_ur")
        assert len(partners) == 2
        assert partners[0].partner_code == "united"
        assert partners[0].ratio == 1.0

    def test_get_program_by_code(self):
        config = AppConfig(
            portfolio=[
                PointsProgram(name="Chase UR", code="chase_ur", balance=100000),
            ]
        )
        program = config.get_program_by_code("chase_ur")
        assert program is not None
        assert program.balance == 100000

        missing = config.get_program_by_code("nonexistent")
        assert missing is None

    def test_get_total_points(self):
        config = AppConfig(
            portfolio=[
                PointsProgram(name="Chase UR", code="chase_ur", balance=100000),
                PointsProgram(name="Amex MR", code="amex_mr", balance=50000),
            ]
        )
        assert config.get_total_points() == 150000
