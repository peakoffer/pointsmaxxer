"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest
import yaml

from pointsmaxxer.config import (
    load_config,
    parse_config,
    save_config,
    create_default_config,
    TRANSFER_PARTNERS,
    AIRLINE_PROGRAMS,
)
from pointsmaxxer.models import CabinClass


class TestLoadConfig:
    def test_load_from_file(self):
        config_data = {
            "portfolio": [
                {"name": "Test Program", "code": "test", "balance": 50000}
            ],
            "routes": [
                {"origin": "SFO", "destination": "NRT", "cabin": "business"}
            ],
            "settings": {
                "unicorn_threshold_cpp": 8.0
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)

            assert len(config.portfolio) == 1
            assert config.portfolio[0].code == "test"
            assert config.portfolio[0].balance == 50000
            assert config.settings.unicorn_threshold_cpp == 8.0
        finally:
            temp_path.unlink()

    def test_load_default_when_missing(self):
        config = load_config(Path("/nonexistent/config.yaml"))
        assert config is not None
        assert len(config.portfolio) == 0


class TestParseConfig:
    def test_parse_portfolio(self):
        raw = {
            "portfolio": [
                {"name": "Chase UR", "code": "chase_ur", "balance": 100000},
                {"name": "Amex MR", "code": "amex_mr", "balance": 50000},
            ]
        }

        config = parse_config(raw)

        assert len(config.portfolio) == 2
        assert config.portfolio[0].name == "Chase UR"
        assert config.portfolio[1].balance == 50000

    def test_parse_routes(self):
        raw = {
            "routes": [
                {"origin": "SFO", "destination": "NRT", "cabin": "business"},
                {"origin": "SFO", "destination": "*", "cabin": "first"},
            ]
        }

        config = parse_config(raw)

        assert len(config.routes) == 2
        assert config.routes[0].cabin == CabinClass.BUSINESS
        assert config.routes[1].destination == "*"
        assert config.routes[1].is_wildcard_destination() is True

    def test_parse_settings(self):
        raw = {
            "settings": {
                "home_airports": ["SFO", "OAK"],
                "unicorn_threshold_cpp": 10.0,
                "search_window_days": 120,
                "max_stops": 0,
            }
        }

        config = parse_config(raw)

        assert config.settings.home_airports == ["SFO", "OAK"]
        assert config.settings.unicorn_threshold_cpp == 10.0
        assert config.settings.search_window_days == 120
        assert config.settings.max_stops == 0

    def test_parse_transfers(self):
        raw = {
            "transfers": {
                "chase_ur": [
                    {"united": 1.0},
                    {"aeroplan": 1.0},
                ]
            }
        }

        config = parse_config(raw)

        partners = config.get_transfer_partners("chase_ur")
        assert len(partners) == 2
        assert partners[0].partner_code == "united"

    def test_parse_invalid_cabin_defaults_to_economy(self):
        raw = {
            "routes": [
                {"origin": "SFO", "destination": "NRT", "cabin": "invalid_cabin"},
            ]
        }

        config = parse_config(raw)
        assert config.routes[0].cabin == CabinClass.ECONOMY


class TestSaveConfig:
    def test_save_and_reload(self):
        from pointsmaxxer.models import AppConfig, PointsProgram, Route, Settings

        config = AppConfig(
            portfolio=[
                PointsProgram(name="Test", code="test", balance=100000),
            ],
            routes=[
                Route(origin="SFO", destination="NRT", cabin=CabinClass.BUSINESS),
            ],
            settings=Settings(unicorn_threshold_cpp=8.0),
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_config(config, temp_path)
            loaded = load_config(temp_path)

            assert len(loaded.portfolio) == 1
            assert loaded.portfolio[0].code == "test"
            assert loaded.settings.unicorn_threshold_cpp == 8.0
        finally:
            temp_path.unlink()


class TestDefaultConfig:
    def test_create_default(self):
        config = create_default_config()

        assert config is not None
        assert len(config.portfolio) == 0
        assert len(config.routes) == 0
        assert config.settings.unicorn_threshold_cpp == 7.0


class TestStaticData:
    def test_transfer_partners_exist(self):
        assert "chase_ur" in TRANSFER_PARTNERS
        assert "amex_mr" in TRANSFER_PARTNERS
        assert "united" in TRANSFER_PARTNERS["chase_ur"]
        assert "ana" in TRANSFER_PARTNERS["amex_mr"]

    def test_airline_programs_exist(self):
        assert "aa" in AIRLINE_PROGRAMS
        assert "united" in AIRLINE_PROGRAMS
        assert "ana" in AIRLINE_PROGRAMS
        assert AIRLINE_PROGRAMS["aa"] == "American AAdvantage"
