"""Installed-wheel proof and isolated namespace fixtures, with no corpus data.

The unchanged discovery checks intentionally require a non-editable wheel in a
fresh virtual environment. No source-root insertion or PYTHONPATH is used.
"""
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from salmongraph import config, discovery


@pytest.fixture(scope="session", autouse=True)
def _installed_wheel():
    prefix = Path(sys.prefix).resolve()
    assert sys.prefix != sys.base_prefix, "Use the fresh wheel-test environment."
    distribution = importlib.metadata.distribution("smn-data-graph")
    origin = Path(discovery.__file__).resolve()
    assert origin.is_relative_to(prefix), "Discovery must load from the installed wheel."
    assert origin == Path(distribution.locate_file("salmongraph/discovery.py")).resolve()
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable"), "Editable installs are not wheel proof."
    assert importlib.util.find_spec("metasalmonpy") is None, "Discovery needs no SDK."
    print(json.dumps({"proof": "installed-wheel", "distribution": distribution.metadata["Name"],
        "version": distribution.version, "module_origin": str(origin), "prefix": str(prefix),
        "sdk_installed": False, "editable": False}))


@pytest.fixture(autouse=True)
def _clean_layout(monkeypatch):
    for name in (config.ENV_BASE, config.ENV_PROFILE_BASE, config.ENV_SDPV_NS):
        monkeypatch.delenv(name, raising=False)
    config.reset()
    yield
    config.reset()
