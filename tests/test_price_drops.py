"""Tests for price drop detection."""

from datetime import datetime

import pytest

from pointsmaxxer.price_drops import (
    PriceDrop,
    PriceDropDetector,
    format_price_drop_alert,
)
from pointsmaxxer.models import Award, Flight, CabinClass


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
def sample_award(sample_flight):
    """Create a sample award at current price."""
    return Award(
        flight=sample_flight,
        program="aeroplan",
        miles=75000,
        cash_fees=150.00,
        cabin=CabinClass.BUSINESS,
        is_saver=True,
    )


class TestPriceDrop:
    """Tests for PriceDrop dataclass."""

    def test_price_drop_creation(self):
        """Test creating a PriceDrop."""
        drop = PriceDrop(
            origin="SFO",
            destination="NRT",
            program="aeroplan",
            cabin=CabinClass.BUSINESS,
            departure_date=datetime(2025, 6, 15),
            old_miles=100000,
            new_miles=75000,
            drop_amount=25000,
            drop_percent=25.0,
            is_saver_now=True,
            detected_at=datetime.now(),
        )

        assert drop.origin == "SFO"
        assert drop.destination == "NRT"
        assert drop.drop_amount == 25000
        assert drop.drop_percent == 25.0

    def test_is_significant_by_percent(self):
        """Test significant drop detection by percentage."""
        drop = PriceDrop(
            origin="SFO",
            destination="NRT",
            program="aeroplan",
            cabin=CabinClass.BUSINESS,
            departure_date=datetime(2025, 6, 15),
            old_miles=100000,
            new_miles=88000,
            drop_amount=12000,
            drop_percent=12.0,
            is_saver_now=False,
            detected_at=datetime.now(),
        )

        assert drop.is_significant is True
        assert drop.is_major is False

    def test_is_significant_by_miles(self):
        """Test significant drop detection by absolute miles."""
        drop = PriceDrop(
            origin="SFO",
            destination="NRT",
            program="aa",
            cabin=CabinClass.FIRST,
            departure_date=datetime(2025, 6, 15),
            old_miles=200000,
            new_miles=193000,
            drop_amount=7000,
            drop_percent=3.5,  # Below 10% threshold
            is_saver_now=False,
            detected_at=datetime.now(),
        )

        # 7000 miles >= 5000 threshold
        assert drop.is_significant is True

    def test_is_major_by_percent(self):
        """Test major drop detection by percentage."""
        drop = PriceDrop(
            origin="SFO",
            destination="LHR",
            program="ba",
            cabin=CabinClass.FIRST,
            departure_date=datetime(2025, 6, 15),
            old_miles=150000,
            new_miles=100000,
            drop_amount=50000,
            drop_percent=33.3,
            is_saver_now=True,
            detected_at=datetime.now(),
        )

        assert drop.is_major is True

    def test_is_major_by_miles(self):
        """Test major drop detection by absolute miles."""
        drop = PriceDrop(
            origin="SFO",
            destination="SIN",
            program="united",
            cabin=CabinClass.BUSINESS,
            departure_date=datetime(2025, 6, 15),
            old_miles=200000,
            new_miles=180000,
            drop_amount=20000,
            drop_percent=10.0,
            is_saver_now=False,
            detected_at=datetime.now(),
        )

        # 20000 >= 15000 threshold
        assert drop.is_major is True

    def test_summary(self):
        """Test price drop summary string."""
        drop = PriceDrop(
            origin="SFO",
            destination="NRT",
            program="aeroplan",
            cabin=CabinClass.BUSINESS,
            departure_date=datetime(2025, 6, 15),
            old_miles=100000,
            new_miles=75000,
            drop_amount=25000,
            drop_percent=25.0,
            is_saver_now=True,
            detected_at=datetime.now(),
        )

        summary = drop.summary
        assert "SFO→NRT" in summary
        assert "AEROPLAN" in summary
        assert "100,000" in summary
        assert "75,000" in summary
        assert "25%" in summary


class TestPriceDropDetector:
    """Tests for PriceDropDetector."""

    def test_detect_drop_found(self, sample_award):
        """Test detecting a price drop."""
        detector = PriceDropDetector(min_drop_percent=10.0, min_drop_miles=5000)

        # Historical price was 100,000, current is 75,000
        drop = detector.detect_drop(sample_award, historical_miles=100000)

        assert drop is not None
        assert drop.old_miles == 100000
        assert drop.new_miles == 75000
        assert drop.drop_amount == 25000
        assert drop.drop_percent == 25.0

    def test_detect_drop_no_change(self, sample_award):
        """Test no drop detected when price unchanged."""
        detector = PriceDropDetector()

        drop = detector.detect_drop(sample_award, historical_miles=75000)

        assert drop is None

    def test_detect_drop_price_increased(self, sample_award):
        """Test no drop when price increased."""
        detector = PriceDropDetector()

        drop = detector.detect_drop(sample_award, historical_miles=50000)

        assert drop is None

    def test_detect_drop_below_threshold(self, sample_award):
        """Test no alert when drop is below threshold."""
        detector = PriceDropDetector(min_drop_percent=10.0, min_drop_miles=5000)

        # 5% drop, 4000 miles - below both thresholds
        award = Award(
            flight=sample_award.flight,
            program="aeroplan",
            miles=76000,
            cabin=CabinClass.BUSINESS,
        )

        drop = detector.detect_drop(award, historical_miles=80000)

        assert drop is None

    def test_detect_drops_batch(self, sample_flight):
        """Test batch drop detection."""
        detector = PriceDropDetector()

        awards = [
            Award(
                flight=sample_flight,
                program="aeroplan",
                miles=75000,
                cabin=CabinClass.BUSINESS,
            ),
            Award(
                flight=sample_flight,
                program="united",
                miles=80000,
                cabin=CabinClass.BUSINESS,
            ),
        ]

        historical = {
            "SFO:NRT:aeroplan:business:2025-06-15": 100000,  # 25% drop
            "SFO:NRT:united:business:2025-06-15": 82000,  # 2.4% drop (below threshold)
        }

        drops = detector.detect_drops_batch(awards, historical)

        assert len(drops) == 1
        assert drops[0].program == "aeroplan"


class TestFormatPriceDropAlert:
    """Tests for alert formatting."""

    def test_format_major_drop(self):
        """Test formatting a major price drop."""
        drop = PriceDrop(
            origin="SFO",
            destination="NRT",
            program="aeroplan",
            cabin=CabinClass.BUSINESS,
            departure_date=datetime(2025, 6, 15),
            old_miles=100000,
            new_miles=70000,
            drop_amount=30000,
            drop_percent=30.0,
            is_saver_now=True,
            detected_at=datetime.now(),
        )

        alert = format_price_drop_alert(drop)

        assert "MAJOR" in alert
        assert "SAVER" in alert
        assert "SFO" in alert
        assert "NRT" in alert
        assert "30%" in alert

    def test_format_significant_drop(self):
        """Test formatting a significant (non-major) drop."""
        drop = PriceDrop(
            origin="JFK",
            destination="LHR",
            program="ba",
            cabin=CabinClass.FIRST,
            departure_date=datetime(2025, 7, 20),
            old_miles=100000,
            new_miles=88000,
            drop_amount=12000,  # Below 15000 miles threshold for major
            drop_percent=12.0,  # Below 25% threshold for major
            is_saver_now=False,
            detected_at=datetime.now(),
        )

        alert = format_price_drop_alert(drop)

        assert "SIGNIFICANT" in alert
        assert "SAVER" not in alert  # Not saver
        assert "JFK" in alert
        assert "LHR" in alert


class TestPriceDropEdgeCases:
    """Edge case tests."""

    def test_zero_historical_price(self, sample_award):
        """Test handling of zero historical price."""
        detector = PriceDropDetector()

        # Should not crash with zero historical
        drop = detector.detect_drop(sample_award, historical_miles=0)

        # No drop detected (price increased from 0)
        assert drop is None

    def test_very_small_drop(self, sample_flight):
        """Test very small drop is ignored."""
        detector = PriceDropDetector(min_drop_percent=10.0, min_drop_miles=5000)

        award = Award(
            flight=sample_flight,
            program="delta",
            miles=99000,
            cabin=CabinClass.ECONOMY,
        )

        # 1% drop, 1000 miles
        drop = detector.detect_drop(award, historical_miles=100000)

        assert drop is None

    def test_exact_threshold_drop(self, sample_flight):
        """Test drop at exact threshold is detected."""
        detector = PriceDropDetector(min_drop_percent=10.0, min_drop_miles=5000)

        award = Award(
            flight=sample_flight,
            program="alaska",
            miles=90000,
            cabin=CabinClass.FIRST,
        )

        # Exactly 10% drop
        drop = detector.detect_drop(award, historical_miles=100000)

        assert drop is not None
        assert drop.drop_percent == 10.0
