from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest.mock import patch

from plexadm import cli


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "config": "config.ini",
        "dry_run": False,
        "with_stash_ids": True,
        "stash_endpoint": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestInventorySnapshotStashGating:
    def test_correlates_by_default_when_stash_is_configured(self) -> None:
        with (
            patch("plexadm.cli.build_context"),
            patch("plexadm.cli._require_inventory_config", return_value=SimpleNamespace(index="plexadm-inventory")),
            patch("plexadm.config.load_config", return_value=SimpleNamespace(stash_endpoint="http://stash:9999")),
            patch("plexadm.stash.StashClient") as mock_client,
            patch("plexadm.inventory.take_snapshot", return_value=5) as mock_snapshot,
        ):
            assert cli.inventory_snapshot(_args()) == 0

        mock_client.assert_called_once_with("http://stash:9999")
        assert mock_snapshot.call_args.kwargs["stash"] is mock_client.return_value

    def test_no_stash_ids_flag_skips_correlation_even_when_configured(self) -> None:
        with (
            patch("plexadm.cli.build_context"),
            patch("plexadm.cli._require_inventory_config", return_value=SimpleNamespace(index="plexadm-inventory")),
            patch("plexadm.config.load_config", return_value=SimpleNamespace(stash_endpoint="http://stash:9999")),
            patch("plexadm.stash.StashClient") as mock_client,
            patch("plexadm.inventory.take_snapshot", return_value=5) as mock_snapshot,
        ):
            assert cli.inventory_snapshot(_args(with_stash_ids=False)) == 0

        mock_client.assert_not_called()
        assert mock_snapshot.call_args.kwargs["stash"] is None

    def test_skips_silently_when_stash_not_in_config_and_no_endpoint_flag(self, capsys: object) -> None:
        with (
            patch("plexadm.cli.build_context"),
            patch("plexadm.cli._require_inventory_config", return_value=SimpleNamespace(index="plexadm-inventory")),
            patch("plexadm.config.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash.StashClient") as mock_client,
            patch("plexadm.inventory.take_snapshot", return_value=5) as mock_snapshot,
        ):
            assert cli.inventory_snapshot(_args()) == 0

        mock_client.assert_not_called()
        assert mock_snapshot.call_args.kwargs["stash"] is None
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "not configured" not in out

    def test_warns_and_skips_when_stash_endpoint_flag_forced_without_config(self, capsys: object) -> None:
        with (
            patch("plexadm.cli.build_context"),
            patch("plexadm.cli._require_inventory_config", return_value=SimpleNamespace(index="plexadm-inventory")),
            patch("plexadm.config.load_config", return_value=SimpleNamespace(stash_endpoint=None)),
            patch("plexadm.stash.StashClient") as mock_client,
            patch("plexadm.inventory.take_snapshot", return_value=5) as mock_snapshot,
        ):
            assert cli.inventory_snapshot(_args(stash_endpoint="http://forced:9999")) == 0

        # --stash-endpoint cannot conjure Stash correlation into existence when the config file
        # has no [stash] endpoint at all - confirmed by direct user request.
        mock_client.assert_not_called()
        assert mock_snapshot.call_args.kwargs["stash"] is None
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "not configured" in out
        assert "--stash-endpoint" in out

    def test_stash_endpoint_flag_overrides_configured_endpoint(self) -> None:
        with (
            patch("plexadm.cli.build_context"),
            patch("plexadm.cli._require_inventory_config", return_value=SimpleNamespace(index="plexadm-inventory")),
            patch("plexadm.config.load_config", return_value=SimpleNamespace(stash_endpoint="http://configured:9999")),
            patch("plexadm.stash.StashClient") as mock_client,
            patch("plexadm.inventory.take_snapshot", return_value=5),
        ):
            assert cli.inventory_snapshot(_args(stash_endpoint="http://override:9999")) == 0

        mock_client.assert_called_once_with("http://override:9999")
