"""Make ``import pagedistiller`` work when pytest runs from the repo root, and
declare the custom markers used to gate integration tests.

``integration`` marks tests that reach a real browser and/or the real network;
the offline suite (``pytest -q`` with no network) skips them via ``skipif``.
There is no ``pyproject.toml`` yet (packaging is a later PLAN step), so the
mark is registered here instead, keeping the run warning-free.
"""

import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: needs a real browser and/or the network; skipped offline",
    )
