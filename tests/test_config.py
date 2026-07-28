from __future__ import annotations

import pytest

from plexadm.config import InventoryConfig, load_inventory_config, load_logging_config, resolve_bool_setting


class TestResolveBoolSetting:
    def test_returns_config_value_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLEXADM_TEST_FLAG", raising=False)
        assert resolve_bool_setting("PLEXADM_TEST_FLAG", True) is True
        assert resolve_bool_setting("PLEXADM_TEST_FLAG", False) is False

    @pytest.mark.parametrize("raw", ["1", "true", "True", "yes", "on"])
    def test_truthy_env_values_override_config(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("PLEXADM_TEST_FLAG", raw)
        assert resolve_bool_setting("PLEXADM_TEST_FLAG", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off"])
    def test_falsy_env_values_override_config(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("PLEXADM_TEST_FLAG", raw)
        assert resolve_bool_setting("PLEXADM_TEST_FLAG", True) is False


class TestLoadLoggingConfigQuietOpensearchLog:
    def test_defaults_to_true_when_unset(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLEXADM_QUIET_OPENSEARCH_LOG", raising=False)
        config_path = tmp_path / "config.ini"
        config_path.write_text("[default]\nplexHost = x\n")

        assert load_logging_config(config_path).quiet_opensearch_log is True

    def test_config_file_can_disable_it(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLEXADM_QUIET_OPENSEARCH_LOG", raising=False)
        config_path = tmp_path / "config.ini"
        config_path.write_text("[logging]\nquiet_opensearch_log = false\n")

        assert load_logging_config(config_path).quiet_opensearch_log is False

    def test_env_var_overrides_config_file(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLEXADM_QUIET_OPENSEARCH_LOG", "0")
        config_path = tmp_path / "config.ini"
        config_path.write_text("[logging]\nquiet_opensearch_log = true\n")

        assert load_logging_config(config_path).quiet_opensearch_log is False


class TestLoadInventoryConfig:
    def test_returns_none_when_section_missing(self, tmp_path) -> None:
        config_path = tmp_path / "config.ini"
        config_path.write_text("[default]\nplexHost = x\n")

        assert load_inventory_config(config_path) is None

    def test_parses_section_when_present(self, tmp_path) -> None:
        config_path = tmp_path / "config.ini"
        config_path.write_text(
            "[inventory]\nurl = http://truenas.example:9200\nindex = custom-index\nverify_tls = false\n"
        )

        config = load_inventory_config(config_path)

        assert config == InventoryConfig(url="http://truenas.example:9200", index="custom-index", verify_tls=False)

    def test_missing_url_raises(self, tmp_path) -> None:
        config_path = tmp_path / "config.ini"
        config_path.write_text("[inventory]\nindex = custom-index\n")

        with pytest.raises(KeyError):
            load_inventory_config(config_path)
