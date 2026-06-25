"""Tests for tools.analysis.network variable schema."""

from __future__ import annotations

import pytest

from tools.analysis.network.models import (
    VARIABLE_SCHEMA,
    family_of,
    is_active,
    parse_var_name,
)


def test_parse_var_name_handles_every_family():
    for family in VARIABLE_SCHEMA:
        dims = VARIABLE_SCHEMA[family]["dims"]
        key = f"{family}[" + ",".join(f"idx{i}" for i in range(len(dims))) + "]"
        parsed = parse_var_name(key)
        assert parsed is not None
        name, indices = parsed
        assert name == family
        assert len(indices) == len(dims)


def test_parse_var_name_rejects_malformed():
    assert parse_var_name("not_a_var") is None
    assert parse_var_name("foo[unbalanced") is None
    assert parse_var_name("[a,b]") is None


def test_family_of_unknown_returns_none():
    assert family_of("ghost[a,b]") is None
    assert family_of("y_s[s1]") == "y_s"


@pytest.mark.parametrize("value,kind,eps,expected", [
    (1.0, "binary", 1e-6, 1),
    (0.0, "binary", 1e-6, 0),
    (0.6, "binary", 1e-6, 1),
    (0.4, "binary", 1e-6, 0),
    (3.0, "integer", 1e-6, 1),
    (1e-7, "continuous", 1e-6, 0),
    (1e-3, "continuous", 1e-6, 1),
    (-1e-3, "continuous", 1e-6, 1),
])
def test_is_active(value, kind, eps, expected):
    assert is_active(value, kind, eps) == expected


