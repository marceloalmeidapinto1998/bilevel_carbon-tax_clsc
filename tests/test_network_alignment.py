"""Tests for tools.analysis.network alignment helpers."""

from __future__ import annotations

from dataclasses import replace

from tools.analysis.network.core import build_alignment
from tools.analysis.network.io import DEFAULT
from tools.analysis.network.io import (
    load_enumeration_payload,
    load_lf_lex_payload,
)


def test_alignment_match(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    enum_payload = load_enumeration_payload(synthetic_instance, cfg)
    lf = load_lf_lex_payload(synthetic_instance, cfg)
    rep = build_alignment(enum_payload, lf, cfg.eps)
    assert rep.lf_lex_present is True
    assert rep.hat_tau_match is True
    assert rep.emissions_match is True
    assert rep.cost_delta_at_same_tau == 0.0


def test_alignment_mismatch_on_hat_tau(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    enum_payload = load_enumeration_payload(synthetic_instance, cfg)
    enum_payload["selected_hat_tau"] = 1  # disagrees with lf_lex (=2)
    lf = load_lf_lex_payload(synthetic_instance, cfg)
    rep = build_alignment(enum_payload, lf, cfg.eps)
    assert rep.hat_tau_match is False
    assert rep.lf_lex_present is True


def test_alignment_none_when_lf_lex_missing(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    enum_payload = load_enumeration_payload(synthetic_instance, cfg)
    rep = build_alignment(enum_payload, None, cfg.eps)
    assert rep.lf_lex_present is False
    assert rep.lf_lex_hat_tau is None
    assert rep.hat_tau_match is False
    assert rep.emissions_match is False
    assert rep.cost_delta_at_same_tau is None


