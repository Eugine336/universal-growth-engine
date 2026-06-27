"""
Tests for the domain configuration loader.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from core.config.loader import ConfigLoadError, DomainConfigLoader
from core.config.schema import ApplicationConfig
from core.decision.policy import PolicyRegistry
from core.entity.registry import EntityRegistry
from core.entity.state import EntityStateMachine
from core.events.validator import EventValidator


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

def _minimal_config_dict():
    return {
        "application": {"id": "test_app", "name": "Test App", "category": "testing"},
        "entities": [
            {
                "type_name": "Widget",
                "is_asset": True,
                "required_attributes": ["title"],
                "allowed_states": ["draft", "active"],
                "initial_state": "draft",
            },
        ],
        "events": {
            "allowed": ["SESSION_STARTED", "PAGE_VIEWED", "CUSTOM"],
            "require_actor": True,
        },
        "state_machines": [
            {
                "type_name": "Widget",
                "initial_state": "draft",
                "states": ["draft", "active"],
                "transitions": [
                    {
                        "from": "draft",
                        "to": "active",
                        "trigger_events": ["ENTITY_UPDATED"],
                        "label": "Publish widget",
                    },
                ],
            },
        ],
        "policies": [
            {
                "name": "Test Nudge",
                "description": "A test policy",
                "trigger_events": ["SESSION_STARTED"],
                "conditions": [
                    {"field": "churn_score", "operator": "gte", "value": 0.5},
                ],
                "action": {
                    "action_type": "SEND_IN_APP",
                    "priority": 55,
                    "payload_template": {"template": "test_nudge"},
                    "valid_hours": 24,
                },
                "cooldown_hours": 48,
            },
        ],
        "objectives": {"primary": "grow", "secondary": ["retain"]},
        "kpis": ["conversion_rate"],
        "constraints": {"regions": ["US"], "compliance": ["GDPR"], "languages": ["en"]},
    }


def _make_loader():
    return DomainConfigLoader(
        entity_registry=EntityRegistry(),
        state_machine=EntityStateMachine(),
        event_validator=EventValidator(),
        policy_registry=PolicyRegistry(),
    )


def _write_yaml(directory: str, filename: str, data: dict) -> str:
    path = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# ---------------------------------------------------------------
# Schema parsing
# ---------------------------------------------------------------

class TestApplicationConfigParsing:
    def test_parse_minimal(self):
        cfg = ApplicationConfig.model_validate(_minimal_config_dict())
        assert cfg.application.id == "test_app"
        assert cfg.application.name == "Test App"
        assert len(cfg.entities) == 1
        assert cfg.entities[0].type_name == "Widget"
        assert cfg.entities[0].is_asset is True
        assert cfg.events is not None
        assert "SESSION_STARTED" in cfg.events.allowed
        assert len(cfg.state_machines) == 1
        assert len(cfg.policies) == 1
        assert cfg.policies[0].name == "Test Nudge"

    def test_parse_without_optional_sections(self):
        data = {
            "application": {"id": "bare", "name": "Bare"},
        }
        cfg = ApplicationConfig.model_validate(data)
        assert cfg.application.id == "bare"
        assert cfg.entities == []
        assert cfg.events is None
        assert cfg.policies == []
        assert cfg.state_machines == []

    def test_state_transition_alias(self):
        data = _minimal_config_dict()
        sm = data["state_machines"][0]
        t = sm["transitions"][0]
        assert "from" in t and "to" in t
        cfg = ApplicationConfig.model_validate(data)
        trans = cfg.state_machines[0].transitions[0]
        assert trans.from_state == "draft"
        assert trans.to_state == "active"


# ---------------------------------------------------------------
# Loader — load_file
# ---------------------------------------------------------------

class TestDomainConfigLoaderFile:
    def test_load_file_registers_entity(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            loader.load_file(path)

        defn = loader._entity_registry.get("test_app", "Widget")
        assert defn is not None
        assert defn.type_name == "Widget"
        assert defn.is_asset is True
        assert "title" in defn.required_attributes
        assert defn.initial_state == "draft"

    def test_load_file_registers_state_machine(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            loader.load_file(path)

        sm = loader._state_machine.get("test_app", "Widget")
        assert sm is not None
        assert sm.initial_state == "draft"
        assert "active" in sm.states
        assert len(sm.transitions) == 1
        assert sm.transitions[0].to_state == "active"

    def test_load_file_registers_event_policy(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            loader.load_file(path)

        policy = loader._event_validator._policies.get("test_app")
        assert policy is not None
        assert "SESSION_STARTED" in policy.allowed_events
        assert policy.require_actor is True

    def test_load_file_registers_policy(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            loader.load_file(path)

        policies = loader._policy_registry.list_for_application("test_app")
        names = [p.name for p in policies]
        assert "Test Nudge" in names

    def test_load_file_tracks_app_id(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            loader.load_file(path)

        assert "test_app" in loader.loaded_applications

    def test_load_file_returns_config(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", _minimal_config_dict())
            cfg = loader.load_file(path)

        assert isinstance(cfg, ApplicationConfig)
        assert cfg.application.id == "test_app"


# ---------------------------------------------------------------
# Loader — load_directory
# ---------------------------------------------------------------

class TestDomainConfigLoaderDirectory:
    def test_load_directory_multiple_configs(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            app1 = _minimal_config_dict()
            app2 = _minimal_config_dict()
            app2["application"]["id"] = "second_app"
            app2["application"]["name"] = "Second App"

            _write_yaml(os.path.join(tmpdir, "app1"), "config.yaml", app1)
            _write_yaml(os.path.join(tmpdir, "app2"), "config.yaml", app2)

            configs = loader.load_directory(tmpdir)

        assert len(configs) == 2
        loaded_ids = set(loader.loaded_applications)
        assert "test_app" in loaded_ids
        assert "second_app" in loaded_ids

    def test_load_directory_nonexistent(self):
        loader = _make_loader()
        configs = loader.load_directory("/nonexistent/path")
        assert configs == []

    def test_load_directory_skips_bad_files(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            good = _minimal_config_dict()
            _write_yaml(os.path.join(tmpdir, "good"), "config.yaml", good)

            bad_path = os.path.join(tmpdir, "bad", "config.yaml")
            os.makedirs(os.path.dirname(bad_path), exist_ok=True)
            with open(bad_path, "w") as f:
                f.write("not: {valid: [config")

            configs = loader.load_directory(tmpdir)

        assert len(configs) == 1
        assert loader.loaded_applications == ["test_app"]


# ---------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------

class TestDomainConfigLoaderErrors:
    def test_missing_file(self):
        loader = _make_loader()
        with pytest.raises(ConfigLoadError, match="not found"):
            loader.load_file("/nonexistent/config.yaml")

    def test_invalid_yaml(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.yaml")
            with open(path, "w") as f:
                f.write("{{bad yaml::")
            with pytest.raises(ConfigLoadError, match="Invalid YAML"):
                loader.load_file(path)

    def test_schema_validation_error(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", {"wrong": "schema"})
            with pytest.raises(ConfigLoadError, match="validation failed"):
                loader.load_file(path)

    def test_non_mapping_root(self):
        loader = _make_loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.yaml")
            with open(path, "w") as f:
                f.write("- just\n- a\n- list\n")
            with pytest.raises(ConfigLoadError, match="must be a mapping"):
                loader.load_file(path)

    def test_unknown_action_type_skipped(self):
        loader = _make_loader()
        data = _minimal_config_dict()
        data["policies"][0]["action"]["action_type"] = "NONEXISTENT_ACTION"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_yaml(tmpdir, "config.yaml", data)
            loader.load_file(path)

        app_policies = loader._policy_registry.list_for_application("test_app")
        names = [p.name for p in app_policies]
        assert "Test Nudge" not in names


# ---------------------------------------------------------------
# Real config files
# ---------------------------------------------------------------

class TestRealDomainConfigs:
    def test_load_ucmc_config(self):
        loader = _make_loader()
        cfg = loader.load_file("domain/examples/ucmc/config.yaml")
        assert cfg.application.id == "ucmc"
        assert len(cfg.entities) >= 3
        assert cfg.events is not None
        assert len(cfg.state_machines) >= 1
        assert len(cfg.policies) >= 1

        defn = loader._entity_registry.get("ucmc", "Seller")
        assert defn is not None
        assert defn.is_person is True

        sm = loader._state_machine.get("ucmc", "Seller")
        assert sm is not None
        assert sm.initial_state == "onboarding"

    def test_load_trading_config(self):
        loader = _make_loader()
        cfg = loader.load_file("domain/examples/trading/config.yaml")
        assert cfg.application.id == "trading_platform"
        assert len(cfg.entities) >= 3
        assert len(cfg.state_machines) >= 1
        assert len(cfg.policies) >= 1

        defn = loader._entity_registry.get("trading_platform", "Trader")
        assert defn is not None
        assert defn.is_person is True

    def test_load_all_examples(self):
        loader = _make_loader()
        configs = loader.load_directory("domain/examples")
        assert len(configs) == 2
        loaded = set(loader.loaded_applications)
        assert "ucmc" in loaded
        assert "trading_platform" in loaded
