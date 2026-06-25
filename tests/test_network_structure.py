"""Tests for tools.analysis.network structure helpers."""

from __future__ import annotations

from dataclasses import replace

from tools.analysis.network.io import DEFAULT
from tools.analysis.network.io import load_enumeration_payload
from tools.analysis.network.pipeline import _snapshots_from_payload
from tools.analysis.network.core import (
    compute_structural_signature,
    detect_phases,
    detect_transitions,
    signature_diff,
)


def test_signature_is_sorted_and_order_independent():
    rows = {
        "facility_open.csv": [
            {"family": "y_s", "supplier": "s2", "active": 1},
            {"family": "y_s", "supplier": "s1", "active": 1},
            {"family": "y_f", "factory": "f1", "active": 1},
        ],
    }
    sig = compute_structural_signature(rows, ("y_s", "y_f"))
    assert sig == ("y_f[f1]", "y_s[s1]", "y_s[s2]")


def test_signature_ignores_inactive_and_off_families():
    rows = {
        "facility_open.csv": [
            {"family": "y_s", "supplier": "s1", "active": 0},
        ],
        "production.csv": [
            {"family": "q", "product": "p1", "factory": "f1", "tech": "t",
             "period": "1", "active": 1, "value": 5.0},
        ],
    }
    sig = compute_structural_signature(rows, ("y_s", "y_f"))
    assert sig == ()


def test_detect_phases_merges_consecutive_identical_signatures(
    synthetic_results_base, synthetic_instance,
):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    payload = load_enumeration_payload(synthetic_instance, cfg)
    snapshots, _, _ = _snapshots_from_payload(payload, lf_lex_hat_tau=2, cfg=cfg)
    phases = detect_phases(snapshots)
    # synthetic fixture: tau in {0,1} share signature; tau in {2,3} share another
    assert len(phases) == 2
    assert phases[0].tau_start == 0 and phases[0].tau_end == 1 and phases[0].n_taus == 2
    assert phases[1].tau_start == 2 and phases[1].tau_end == 3 and phases[1].n_taus == 2
    assert phases[1].contains_lf_lex_incumbent is True


def test_detect_transitions_finds_added_supplier(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    payload = load_enumeration_payload(synthetic_instance, cfg)
    snapshots, _, _ = _snapshots_from_payload(payload, lf_lex_hat_tau=2, cfg=cfg)
    transitions = detect_transitions(snapshots)
    assert len(transitions) == 1
    t = transitions[0]
    assert t.tau_from == 1 and t.tau_to == 2
    assert any("y_s[s2]" == a for a in t.added)
    assert t.removed == ()


def test_signature_diff_handles_added_and_removed():
    added, removed = signature_diff(("a", "b"), ("b", "c"))
    assert added == ("c",) and removed == ("a",)


