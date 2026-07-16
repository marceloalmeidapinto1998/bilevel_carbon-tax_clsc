from __future__ import annotations

import pytest

from src.config.gap_tol import DEFAULT, ToleranceConfig


def test_default_tolerance_config_is_self_consistent() -> None:
    assert DEFAULT.eps < DEFAULT.mip_gap
    assert DEFAULT.eps < DEFAULT.dbp_relative_gap
    assert DEFAULT.lex_epsilon_prime < DEFAULT.mip_gap
    assert DEFAULT.dbp_cut_epsilon < DEFAULT.mip_gap
    assert DEFAULT.stagnation_limit > 0
    assert DEFAULT.elastic_penalty_mult > 1.0
    assert DEFAULT.threads >= 1
    assert DEFAULT.mip_focus in {0, 1, 2, 3}


def test_tolerance_config_dataclass_is_immutable() -> None:
    with pytest.raises((AttributeError, TypeError)):
        DEFAULT.eps = 0.0  # type: ignore[misc]


def test_relative_optimality_gap_is_zero_at_convergence() -> None:
    from src.solvers.dbp_lex import relative_optimality_gap

    assert relative_optimality_gap(upper_bound=100.0, lower_bound=100.0) == 0.0
    assert relative_optimality_gap(upper_bound=1.0, lower_bound=0.5) == pytest.approx(0.5)
    assert relative_optimality_gap(upper_bound=0.0, lower_bound=-1.0) == pytest.approx(1.0)


def test_relative_optimality_gap_is_never_negative() -> None:
    from src.solvers.dbp_lex import relative_optimality_gap

    # Floating-point noise can make lower_bound slightly exceed upper_bound.
    assert relative_optimality_gap(upper_bound=1.0, lower_bound=1.0 + 1e-12) == 0.0
