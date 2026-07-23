from __future__ import annotations

import pytest

from plexadm.config import InventoryConfig, load_inventory_config


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
