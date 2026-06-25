"""Tests for tools.analysis.network.io."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.analysis.network import io as ts_io
from tools.analysis.network.io import DEFAULT


def test_load_enumeration_happy_path(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    payload = ts_io.load_enumeration_payload(synthetic_instance, cfg)
    assert payload["instance"] == synthetic_instance
    assert len(payload["tax_solutions"]) == 4


def test_load_lf_lex_returns_none_when_missing(synthetic_results_base, synthetic_instance, tmp_path):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    payload = ts_io.load_lf_lex_payload(synthetic_instance, cfg)
    assert payload is not None
    cfg2 = replace(DEFAULT, results_base=tmp_path / "does_not_exist")
    assert ts_io.load_lf_lex_payload(synthetic_instance, cfg2) is None


def test_discover_instances(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    assert ts_io.discover_instances(cfg) == [synthetic_instance]


def test_sha256_is_deterministic(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    a = ts_io.sha256_file(f)
    b = ts_io.sha256_file(f)
    assert a == b
    assert len(a) == 64


def test_ensure_output_dirs_creates_subfolders(tmp_path, synthetic_instance):
    cfg = replace(DEFAULT, results_base=tmp_path / "out")
    paths = ts_io.ensure_output_dirs(synthetic_instance, cfg)
    assert paths.root.is_dir()
    assert paths.figures.is_dir()


def test_enumeration_missing_raises(tmp_path, synthetic_instance):
    cfg = replace(DEFAULT, results_base=tmp_path / "empty")
    with pytest.raises(FileNotFoundError):
        ts_io.load_enumeration_payload(synthetic_instance, cfg)

