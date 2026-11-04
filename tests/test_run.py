"""The resumable runner: a stage re-runs exactly when its inputs moved."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import run


def _touch(p: Path, t: float) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    os.utime(p, (t, t))
    return p


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    return tmp_path


def test_missing_artifact_is_stale(root):
    assert run.stale(run.Stage("s", ["x"], Path("out.parquet"), [Path("src.py")]))


def test_source_newer_than_artifact_is_stale(root):
    _touch(root / "out.parquet", 1_000)
    _touch(root / "src.py", 2_000)
    assert run.stale(run.Stage("s", ["x"], Path("out.parquet"), [Path("src.py")]))


def test_artifact_newer_than_every_source_is_current(root):
    _touch(root / "src.py", 1_000)
    _touch(root / "out.parquet", 2_000)
    assert not run.stale(run.Stage("s", ["x"], Path("out.parquet"), [Path("src.py")]))


def test_a_directory_source_counts_its_newest_file(root):
    _touch(root / "out" / "index.html", 2_000)
    _touch(root / "web" / "a.ts", 1_000)
    _touch(root / "web" / "deep" / "b.ts", 3_000)
    assert run.stale(run.Stage("s", ["x"], Path("out/index.html"), [Path("web")]))


def test_a_stage_without_an_artifact_always_runs(root):
    assert run.stale(run.Stage("lint", ["x"]))


def test_stage_names_are_unique_and_paths_have_no_control_characters():
    names = [s.name for s in run.STAGES]
    assert len(names) == len(set(names))
    # The bug this runner replaced: "\t", "\v", "\f" inside Windows path strings.
    for s in run.STAGES:
        for p in [s.artifact, *s.sources]:
            if p is not None:
                assert not any(c in str(p) for c in "\t\v\f\r\n"), (s.name, p)


def test_contracts_run_before_the_models_that_trust_them():
    order = [s.name for s in run.STAGES]
    assert order.index("ds-contracts") < min(order.index(n) for n in order if n.startswith("ds-")
                                             and n != "ds-contracts")
    assert order.index("call-response") < order.index("sizing")


def test_unknown_stage_is_rejected(capsys):
    with pytest.raises(SystemExit):
        run.main(["--only", "no-such-stage", "--skip-web"])
    assert "unknown stage" in capsys.readouterr().err


def test_a_failing_critical_stage_stops_the_run(root, monkeypatch):
    calls = []
    stages = [run.Stage("a", ["x"], critical=True), run.Stage("b", ["x"])]
    monkeypatch.setattr(run, "STAGES", stages)
    monkeypatch.setattr(run, "LOG", root / "run.log")
    monkeypatch.setattr(run, "run_stage", lambda s: calls.append(s.name) or False)
    assert run.main(["--skip-web"]) == 1
    assert calls == ["a"]
