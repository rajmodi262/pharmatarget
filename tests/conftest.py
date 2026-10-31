"""Shared test fixtures.

THE MANIFEST IS RUN STATE, NOT TEST STATE.

`src.utils.io.record()` writes to data/manifest.json, and that file is what the
API, the deck and the summary read. Several model functions record as a side
effect (fit_potential, head_to_head, gate_g3_verdict, ...), so an unpatched test
run used to overwrite the real pipeline's numbers with fixture values: the
manifest once reported frontier coverage 0.785 from a 400-row test frame, and
gate G3 with the exact 1.4x / 0.8x / 1.5x ratios hard-coded in test_backtest.py.
Those figures then reached the README and the deck.

Per-test monkeypatching was the old defence and it was incomplete. This fixture
is autouse: every test, present and future, writes to a throwaway manifest.
"""
from __future__ import annotations

import pytest

from src.utils import io


@pytest.fixture(autouse=True)
def _isolated_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "MANIFEST", tmp_path / "manifest.json")
    yield
