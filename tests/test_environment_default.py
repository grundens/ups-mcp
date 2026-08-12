"""The environment default is production, and that must not drift.

CIE returns canned data that looks real: ask for one tracking number and it
hands back a different one. So an accidental default of "test" does not fail,
it fabricates. Upstream defaults to CIE, which is correct for a sample server
and wrong here, so this is pinned.
"""
import importlib
import os
from unittest.mock import patch

from ups_mcp import constants


def _base_url(env: dict):
    with patch.dict(os.environ, env, clear=False):
        for k in ("ENVIRONMENT", "UPS_ENVIRONMENT"):
            if k not in env:
                os.environ.pop(k, None)
        mod = importlib.reload(importlib.import_module("ups_mcp.server"))
        return mod.base_url


def test_default_is_production_when_nothing_is_set():
    assert _base_url({}) == constants.PRODUCTION_URL


def test_test_opts_into_cie():
    assert _base_url({"UPS_ENVIRONMENT": "test"}) == constants.CIE_URL
    assert _base_url({"ENVIRONMENT": "test"}) == constants.CIE_URL


def test_anything_else_stays_on_production():
    for value in ("production", "PRODUCTION", "prod", "", "  "):
        assert _base_url({"UPS_ENVIRONMENT": value}) == constants.PRODUCTION_URL
