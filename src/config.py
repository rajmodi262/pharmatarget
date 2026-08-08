"""Configuration loading.

Single source of truth for every tunable in the project. Nothing in src/ or
api/ hard-codes a parameter that belongs in config/.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def _load(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def params() -> dict[str, Any]:
    """Pipeline parameters (config/params.yaml)."""
    return _load("params.yaml")


@lru_cache(maxsize=1)
def economics() -> dict[str, Any]:
    """Economic assumptions (config/economics.yaml)."""
    return _load("economics.yaml")


@lru_cache(maxsize=1)
def manufacturers() -> dict[str, Any]:
    """Open Payments manufacturer normalisation (config/manufacturers.yaml)."""
    return _load("manufacturers.yaml")


def econ(key: str, which: str = "base") -> float:
    """Fetch one economic assumption.

    Deliberately verbose at the call site -- ``econ("rep_cost_annual")`` reads
    as an assumption lookup, which is what it is. Never inline these values.
    """
    node = economics()[key]
    return float(node[which])


def path(key: str) -> Path:
    """Resolve a configured path relative to the repo root, creating it."""
    p = ROOT / params()["paths"][key]
    p.mkdir(parents=True, exist_ok=True)
    return p


def class_generic_names() -> list[str]:
    """Every generic name in the therapeutic class, upper-cased.

    Matching on generic rather than brand name: brand strings in the CMS files
    drift across years, generic strings do not.
    """
    cd = params()["class_definition"]
    names: list[str] = list(cd["focus_brand"]["generic_names"])
    for group in ("competitors", "comparators"):
        for entry in cd[group]:
            names.extend(entry["generic_names"])
    return [n.upper() for n in names]


def focus_generic_names() -> list[str]:
    return [n.upper() for n in params()["class_definition"]["focus_brand"]["generic_names"]]


def years() -> list[int]:
    return list(params()["years"]["all"])
