"""Tests for portfolio manager."""

import pytest

from pointsmaxxer.models import AppConfig, PointsProgram, Settings
from pointsmaxxer.portfolio import PortfolioManager, TransferPath


@pytest.fixture
def sample_config():
    return AppConfig(
        portfolio=[
            PointsProgram(name="Chase UR", code="chase_ur", balance=180000),
            PointsProgram(name="Amex MR", code="amex_mr", balance=95000),
            PointsProgram(name="AA Miles", code="aa", balance=55000),
        ],
        transfers={
            "chase_ur": [
                {"united": 1.0},
                {"aeroplan": 1.0},
                {"hyatt": 1.0},
            ],
            "amex_mr": [
                {"ana": 1.0},
                {"delta": 1.0},
            ],
        },
    )


class TestPortfolioManager:
    def test_get_balance(self, sample_config):
        manager = PortfolioManager(sample_config)

        assert manager.get_balance("chase_ur") == 180000
        assert manager.get_balance("amex_mr") == 95000
        assert manager.get_balance("nonexistent") == 0

    def test_get_total_points(self, sample_config):
        manager = PortfolioManager(sample_config)
        assert manager.get_total_points() == 180000 + 95000 + 55000

    def test_can_transfer_to(self, sample_config):
        manager = PortfolioManager(sample_config)

        assert manager.can_transfer_to("chase_ur", "united") is True
        assert manager.can_transfer_to("chase_ur", "aeroplan") is True
        assert manager.can_transfer_to("chase_ur", "ana") is False
        assert manager.can_transfer_to("amex_mr", "ana") is True
        assert manager.can_transfer_to("aa", "united") is False

    def test_get_transfer_ratio(self, sample_config):
        manager = PortfolioManager(sample_config)

        assert manager.get_transfer_ratio("chase_ur", "united") == 1.0
        assert manager.get_transfer_ratio("chase_ur", "ana") == 0.0


class TestTransferPaths:
    def test_find_transfer_paths_direct(self, sample_config):
        manager = PortfolioManager(sample_config)

        # AA is directly owned, so should find direct path
        paths = manager.find_transfer_paths("aa", 40000)

        direct_paths = [p for p in paths if p.is_direct]
        assert len(direct_paths) == 1
        assert direct_paths[0].source_program == "aa"
        assert direct_paths[0].points_needed == 40000

    def test_find_transfer_paths_transfer(self, sample_config):
        manager = PortfolioManager(sample_config)

        # United not directly owned, but accessible via Chase UR
        paths = manager.find_transfer_paths("united", 50000)

        transfer_paths = [p for p in paths if not p.is_direct]
        assert len(transfer_paths) >= 1

        chase_path = next((p for p in transfer_paths if p.source_program == "chase_ur"), None)
        assert chase_path is not None
        assert chase_path.points_needed == 50000  # 1:1 ratio
        assert chase_path.can_afford is True

    def test_can_afford(self, sample_config):
        manager = PortfolioManager(sample_config)

        # Chase UR has 180k, so can afford 150k united
        paths = manager.find_transfer_paths("united", 150000)
        chase_path = next((p for p in paths if p.source_program == "chase_ur"), None)
        assert chase_path.can_afford is True

        # But can't afford 200k
        paths = manager.find_transfer_paths("united", 200000)
        chase_path = next((p for p in paths if p.source_program == "chase_ur"), None)
        assert chase_path.can_afford is False

    def test_get_best_transfer_path(self, sample_config):
        manager = PortfolioManager(sample_config)

        # Get best path to united
        path = manager.get_best_transfer_path("united", 50000)

        assert path is not None
        assert path.can_afford is True
        # Should be Chase UR since it's the only option
        assert path.source_program == "chase_ur"


class TestProgramsTransferTo:
    def test_get_programs_that_transfer_to(self, sample_config):
        manager = PortfolioManager(sample_config)

        # United is accessible from Chase UR
        programs = manager.get_programs_that_transfer_to("united")
        assert "chase_ur" in programs

        # ANA is accessible from Amex MR
        programs = manager.get_programs_that_transfer_to("ana")
        assert "amex_mr" in programs

        # AA is directly owned
        programs = manager.get_programs_that_transfer_to("aa")
        assert "aa" in programs


class TestPortfolioSummary:
    def test_get_portfolio_summary(self, sample_config):
        manager = PortfolioManager(sample_config)

        summary = manager.get_portfolio_summary()

        assert summary.total_points == 180000 + 95000 + 55000
        assert summary.total_estimated_value > 0
        assert len(summary.programs) == 3

        # Each program should have a best value
        for program in summary.programs:
            assert program.code in summary.best_values


class TestPortfolioModification:
    def test_update_balance(self, sample_config):
        manager = PortfolioManager(sample_config)

        assert manager.update_balance("chase_ur", 200000) is True
        assert manager.get_balance("chase_ur") == 200000

        assert manager.update_balance("nonexistent", 100) is False

    def test_add_program(self, sample_config):
        manager = PortfolioManager(sample_config)

        new_program = PointsProgram(name="Bilt", code="bilt", balance=45000)
        manager.add_program(new_program)

        assert manager.get_balance("bilt") == 45000

    def test_add_program_update_existing(self, sample_config):
        manager = PortfolioManager(sample_config)

        # Update existing program
        updated = PointsProgram(name="Chase UR", code="chase_ur", balance=250000)
        manager.add_program(updated)

        assert manager.get_balance("chase_ur") == 250000
        # Should not duplicate
        assert len(sample_config.portfolio) == 3

    def test_remove_program(self, sample_config):
        manager = PortfolioManager(sample_config)

        assert manager.remove_program("aa") is True
        assert manager.get_balance("aa") == 0
        assert len(sample_config.portfolio) == 2

        assert manager.remove_program("nonexistent") is False
