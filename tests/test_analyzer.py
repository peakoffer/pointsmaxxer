"""Tests for deal analyzer and CPP calculator."""

from datetime import datetime

import pytest

from pointsmaxxer.models import (
    AppConfig,
    Award,
    CabinClass,
    Flight,
    PointsProgram,
    Settings,
)
from pointsmaxxer.analyzer import DealAnalyzer


@pytest.fixture
def sample_config():
    return AppConfig(
        portfolio=[
            PointsProgram(name="Chase UR", code="chase_ur", balance=180000),
            PointsProgram(name="Amex MR", code="amex_mr", balance=95000),
        ],
        transfers={
            "chase_ur": [
                {"united": 1.0},
                {"aeroplan": 1.0},
            ],
            "amex_mr": [
                {"ana": 1.0},
                {"delta": 1.0},
            ],
        },
        settings=Settings(unicorn_threshold_cpp=7.0),
    )


@pytest.fixture
def sample_flight():
    return Flight(
        flight_no="NH7",
        airline_code="NH",
        airline_name="ANA",
        origin="SFO",
        destination="NRT",
        departure=datetime(2024, 3, 1, 10, 0),
        arrival=datetime(2024, 3, 2, 14, 0),
        duration_minutes=675,
    )


@pytest.fixture
def sample_award(sample_flight):
    return Award(
        flight=sample_flight,
        program="ana",
        program_name="ANA Mileage Club",
        miles=85000,
        cash_fees=87.50,
        cabin=CabinClass.BUSINESS,
        is_saver=True,
    )


class TestCPPCalculation:
    def test_basic_cpp(self, sample_config, sample_award):
        analyzer = DealAnalyzer(sample_config)

        # CPP = (cash_price - fees) / miles * 100
        # (6200 - 87.50) / 85000 * 100 = 7.19
        cpp = analyzer.calculate_cpp(sample_award, 6200)
        assert pytest.approx(cpp, rel=0.01) == 7.19

    def test_cpp_zero_miles_validation(self, sample_config, sample_flight):
        """Test that Award model rejects zero miles."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Award(
                flight=sample_flight,
                program="test",
                miles=0,  # Invalid - should raise validation error
                cash_fees=0,
                cabin=CabinClass.ECONOMY,
            )

    def test_cpp_negative_value(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        # When fees exceed cash price
        award = Award(
            flight=sample_flight,
            program="test",
            miles=10000,
            cash_fees=600,
            cabin=CabinClass.ECONOMY,
        )
        cpp = analyzer.calculate_cpp(award, 500)
        assert cpp == 0.0


class TestUnicornDetection:
    def test_is_unicorn(self, sample_config):
        analyzer = DealAnalyzer(sample_config)

        # Threshold is 7.0 cpp
        assert analyzer.is_unicorn(7.0) is True
        assert analyzer.is_unicorn(8.5) is True
        assert analyzer.is_unicorn(6.9) is False
        assert analyzer.is_unicorn(1.0) is False

    def test_custom_threshold(self):
        config = AppConfig(settings=Settings(unicorn_threshold_cpp=10.0))
        analyzer = DealAnalyzer(config)

        assert analyzer.is_unicorn(10.0) is True
        assert analyzer.is_unicorn(9.9) is False


class TestDealAnalysis:
    def test_analyze_award(self, sample_config, sample_award):
        analyzer = DealAnalyzer(sample_config)

        deal = analyzer.analyze_award(sample_award, 6200)

        assert deal.award == sample_award
        assert deal.cash_price == 6200
        assert pytest.approx(deal.cpp, rel=0.01) == 7.19
        assert deal.is_unicorn is True

    def test_analyze_non_unicorn(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        # Award with low CPP
        award = Award(
            flight=sample_flight,
            program="test",
            miles=100000,
            cash_fees=100,
            cabin=CabinClass.ECONOMY,
        )

        deal = analyzer.analyze_award(award, 500)

        # CPP = (500 - 100) / 100000 * 100 = 0.4
        assert pytest.approx(deal.cpp, rel=0.01) == 0.4
        assert deal.is_unicorn is False

    def test_transferable_from(self, sample_config, sample_award):
        analyzer = DealAnalyzer(sample_config)

        deal = analyzer.analyze_award(sample_award, 6200)

        # ANA can be reached via Amex MR
        assert "amex_mr" in deal.transferable_from


class TestDealRanking:
    def test_rank_deals(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        awards = [
            Award(
                flight=sample_flight,
                program="ana",
                miles=85000,
                cash_fees=100,
                cabin=CabinClass.BUSINESS,
                is_saver=True,
            ),
            Award(
                flight=sample_flight,
                program="united",
                miles=88000,
                cash_fees=50,
                cabin=CabinClass.BUSINESS,
                is_saver=False,
            ),
            Award(
                flight=sample_flight,
                program="aeroplan",
                miles=87500,
                cash_fees=150,
                cabin=CabinClass.BUSINESS,
                is_saver=True,
            ),
        ]

        deals = [analyzer.analyze_award(a, 6200) for a in awards]
        ranked = analyzer.rank_deals(deals)

        # Should be sorted by composite score (CPP is major factor)
        assert len(ranked) == 3
        # Higher CPP should generally rank higher
        assert ranked[0].cpp >= ranked[1].cpp

    def test_rank_empty_list(self, sample_config):
        analyzer = DealAnalyzer(sample_config)
        ranked = analyzer.rank_deals([])
        assert ranked == []


class TestDealFiltering:
    def test_filter_by_cpp(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        awards = [
            Award(
                flight=sample_flight,
                program="test1",
                miles=10000,
                cash_fees=0,
                cabin=CabinClass.ECONOMY,
            ),
            Award(
                flight=sample_flight,
                program="test2",
                miles=50000,
                cash_fees=0,
                cabin=CabinClass.BUSINESS,
            ),
        ]

        deals = [analyzer.analyze_award(a, 500) for a in awards]

        # Filter for min_cpp > 2.0
        filtered = analyzer.filter_deals(deals, min_cpp=2.0)

        # Only the 10k miles deal should pass (500/10000*100 = 5 cpp)
        assert len(filtered) == 1

    def test_filter_unicorns_only(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        awards = [
            Award(
                flight=sample_flight,
                program="test1",
                miles=85000,
                cash_fees=100,
                cabin=CabinClass.BUSINESS,
            ),
            Award(
                flight=sample_flight,
                program="test2",
                miles=100000,
                cash_fees=100,
                cabin=CabinClass.BUSINESS,
            ),
        ]

        deals = [analyzer.analyze_award(a, 6200) for a in awards]

        filtered = analyzer.filter_deals(deals, unicorns_only=True)

        # Only deals with CPP >= 7.0 should pass
        for deal in filtered:
            assert deal.is_unicorn is True

    def test_filter_by_cabin(self, sample_config, sample_flight):
        analyzer = DealAnalyzer(sample_config)

        awards = [
            Award(
                flight=sample_flight,
                program="test1",
                miles=10000,
                cash_fees=0,
                cabin=CabinClass.ECONOMY,
            ),
            Award(
                flight=sample_flight,
                program="test2",
                miles=50000,
                cash_fees=0,
                cabin=CabinClass.BUSINESS,
            ),
        ]

        deals = [analyzer.analyze_award(a, 500) for a in awards]

        filtered = analyzer.filter_deals(deals, cabins=[CabinClass.BUSINESS])

        assert len(filtered) == 1
        assert filtered[0].award.cabin == CabinClass.BUSINESS
