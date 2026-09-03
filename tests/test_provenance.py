"""Run provenance: the guarantee that a recorded result names the code and data that produced it.

Every `campaign_manifest.json` records `code_version` as a commit hash. That hash is only
meaningful if the working tree actually matched it, so the orchestrator refuses to start a
campaign against a dirty tree and stamps what it verified onto every manifest it writes.

The parsing here is worth pinning specifically. `git status --porcelain` encodes the index state
in column 0 and the worktree state in column 1, and column 0 is a *significant space* for an
unstaged change. An implementation that strips the output before slicing the path loses that
space and reports `rc/clsc/...` instead of `src/clsc/...` -- paths that still look plausible in an
error message, so nothing surfaces the mistake. That regression is pinned below.
"""
from __future__ import annotations

import json

import pytest

from clsc.campaign import orchestrator as campaign
from clsc.campaign.designs._common import DesignPoint


# ===========================================================================
# Porcelain parsing
# ===========================================================================

def test_unstaged_change_keeps_its_leading_space_column() -> None:
    """The regression: ' M src/x.py' has a significant space in column 0."""
    assert campaign._porcelain_paths(" M src/clsc/campaign/orchestrator.py") == (
        "src/clsc/campaign/orchestrator.py",
    )


def test_staged_and_untracked_entries_parse_to_the_same_shape() -> None:
    status = "M  src/a.py\n?? src/b.py\n D data/instances/base/STD_I17_M4_T3.json"
    assert campaign._porcelain_paths(status) == (
        "data/instances/base/STD_I17_M4_T3.json",
        "src/a.py",
        "src/b.py",
    )


def test_rename_records_the_destination_not_the_source() -> None:
    """`old -> new` names the path that exists now; that is the one a re-run would read."""
    assert campaign._porcelain_paths("R  src/old_name.py -> src/new_name.py") == ("src/new_name.py",)


def test_quoted_paths_are_unquoted() -> None:
    assert campaign._porcelain_paths(' M "src/wéird.py"') == ("src/wéird.py",)


def test_blank_and_truncated_lines_are_ignored() -> None:
    assert campaign._porcelain_paths("\n M \n\n M src/a.py\n") == ("src/a.py",)


# ===========================================================================
# CodeProvenance
# ===========================================================================

def test_clean_tree_at_a_known_commit_is_publication_safe() -> None:
    provenance = campaign.CodeProvenance(commit="a" * 40, dirty=False)
    assert provenance.is_publication_safe


def test_dirty_tree_is_not_publication_safe() -> None:
    provenance = campaign.CodeProvenance(commit="a" * 40, dirty=True, dirty_paths=("src/x.py",))
    assert not provenance.is_publication_safe


def test_unknown_git_state_is_not_treated_as_clean() -> None:
    """`dirty is None` means git could not answer -- which is not the same as verified clean."""
    assert not campaign.CodeProvenance(commit="a" * 40, dirty=None).is_publication_safe
    assert not campaign.CodeProvenance(commit="unknown", dirty=False).is_publication_safe


def test_manifest_fields_carry_all_three_provenance_facts() -> None:
    fields = campaign.CodeProvenance(
        commit="a" * 40, dirty=True, dirty_paths=("src/x.py",),
    ).as_manifest_fields()
    assert fields == {
        "code_version": "a" * 40,
        "code_dirty": True,
        "code_dirty_paths": ["src/x.py"],
    }


def test_capture_reports_unknown_when_git_cannot_answer(monkeypatch) -> None:
    monkeypatch.setattr(campaign, "_git", lambda *args: None)
    provenance = campaign.capture_code_provenance()
    assert provenance.commit == "unknown"
    assert provenance.dirty is None
    assert not provenance.is_publication_safe


def test_capture_only_watches_the_result_bearing_paths() -> None:
    """A dirty paper/ or docs/ must never block a campaign; a dirty src/ must."""
    assert "src" in campaign.PROVENANCE_PATHS
    assert "data/instances/base" in campaign.PROVENANCE_PATHS
    assert not any(p.startswith(("paper", "docs", "tests", "results")) for p in campaign.PROVENANCE_PATHS)


# ===========================================================================
# The guard
# ===========================================================================

def test_clean_tree_passes_the_guard() -> None:
    campaign.require_clean_worktree(campaign.CodeProvenance(commit="a" * 40, dirty=False))


def test_dirty_tree_is_refused_and_the_error_names_the_paths() -> None:
    provenance = campaign.CodeProvenance(
        commit="b" * 40, dirty=True, dirty_paths=("src/clsc/models/subproblems.py",),
    )
    with pytest.raises(campaign.DirtyWorkingTreeError) as excinfo:
        campaign.require_clean_worktree(provenance)
    assert "src/clsc/models/subproblems.py" in str(excinfo.value)
    assert "--allow-dirty" in str(excinfo.value)


def test_unverifiable_tree_is_refused_too() -> None:
    with pytest.raises(campaign.DirtyWorkingTreeError):
        campaign.require_clean_worktree(campaign.CodeProvenance(commit="c" * 40, dirty=None))


def test_long_dirty_lists_are_truncated_with_a_count() -> None:
    provenance = campaign.CodeProvenance(
        commit="d" * 40, dirty=True, dirty_paths=tuple(f"src/f{i}.py" for i in range(25)),
    )
    with pytest.raises(campaign.DirtyWorkingTreeError) as excinfo:
        campaign.require_clean_worktree(provenance)
    assert "... and 5 more" in str(excinfo.value)


def test_run_experiment_refuses_a_dirty_tree_before_solving_anything(monkeypatch) -> None:
    """The guard must fire before any design point is built, not part-way through."""
    def explode(*args, **kwargs):
        raise AssertionError("run_experiment must not reach a design point on a dirty tree")

    monkeypatch.setattr(campaign, "run_point", explode)
    dirty = campaign.CodeProvenance(commit="e" * 40, dirty=True, dirty_paths=("src/x.py",))
    with pytest.raises(campaign.DirtyWorkingTreeError):
        campaign.run_experiment("exp1", provenance=dirty)


def test_allow_dirty_lets_a_development_run_through(monkeypatch) -> None:
    seen: list[campaign.CodeProvenance] = []

    def fake_run_point(point, *, overwrite=False, provenance=None):
        seen.append(provenance)
        return {"solve_status": "success"}

    monkeypatch.setattr(campaign, "run_point", fake_run_point)
    dirty = campaign.CodeProvenance(commit="e" * 40, dirty=True, dirty_paths=("src/x.py",))
    campaign.run_experiment("exp1", allow_dirty=True, provenance=dirty)

    assert seen, "expected design points to run"
    # One snapshot, threaded through every point: a campaign's manifests must agree with each
    # other rather than each re-asking git.
    assert all(p is dirty for p in seen)


# ===========================================================================
# Manifest contents
# ===========================================================================

def _toy_point() -> DesignPoint:
    return DesignPoint(
        experiment_id="exp1",
        design_point_id="exp1_prov_probe",
        run_code="prov_probe",
        base_instance_id="STD_TOY1",
        execution_mode="bilevel",
        per_subproblem_time_limit_seconds=5.0,
        per_run_wall_clock_cap_seconds=5.0,
        is_toy=True,
    )


def test_manifest_records_provenance_and_the_instance_digest(tmp_path, monkeypatch) -> None:
    """The three facts that make a result checkable after the fact: which commit, whether the
    tree matched it, and which exact instance bytes went in."""
    instance_path = tmp_path / "toy.json"
    instance_path.write_text(json.dumps({"name": "STD_TOY1"}), encoding="utf-8")

    monkeypatch.setattr(campaign, "RESULTS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(campaign, "HEARTBEAT_LOG", tmp_path / "runs" / "_heartbeat.log")
    monkeypatch.setattr(
        "clsc.campaign.toy.materialize_toy", lambda point, output_root: instance_path,
    )
    monkeypatch.setattr(
        campaign, "_solve_bilevel",
        lambda point, path, out_dir: {"success": True, "termination_reason": "relative_gap"},
    )

    provenance = campaign.CodeProvenance(commit="f" * 40, dirty=False)
    manifest = campaign.run_point(_toy_point(), provenance=provenance)

    assert manifest["code_version"] == "f" * 40
    assert manifest["code_dirty"] is False
    assert manifest["code_dirty_paths"] == []
    # sha256 of the bytes actually written, not of the path string.
    import hashlib

    assert manifest["instance_sha256"] == hashlib.sha256(
        instance_path.read_bytes()
    ).hexdigest()


def test_content_digest_ignores_the_regeneration_timestamp(tmp_path) -> None:
    """The reason the file digest alone is not enough: materialize() stamps a fresh
    `generated_at_utc` on every run, so two runs of an IDENTICAL instance get different file
    digests for a reason that has nothing to do with the optimization problem."""
    body = {"name": "X", "sets": {"P": ["p1"]}, "parameters": {"a": 1.5}}
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(
        json.dumps({**body, "metadata": {"generated_at_utc": "2026-09-02T15:42:53Z"}}), encoding="utf-8",
    )
    second.write_text(
        json.dumps({**body, "metadata": {"generated_at_utc": "2026-09-03T10:48:35Z"}}), encoding="utf-8",
    )

    assert campaign._sha256_file(first) != campaign._sha256_file(second)
    assert campaign._sha256_instance_content(first) == campaign._sha256_instance_content(second)


def test_content_digest_still_separates_genuinely_different_instances(tmp_path) -> None:
    base = {"name": "X", "sets": {"P": ["p1"]}, "metadata": {}}
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(json.dumps({**base, "parameters": {"a": 1.5}}), encoding="utf-8")
    second.write_text(json.dumps({**base, "parameters": {"a": 1.6}}), encoding="utf-8")

    assert campaign._sha256_instance_content(first) != campaign._sha256_instance_content(second)


def test_content_digest_is_key_order_independent(tmp_path) -> None:
    """Two writers emitting the same instance with different key order must agree."""
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text('{"name":"X","sets":{"P":["p1"]},"parameters":{"a":1,"b":2}}', encoding="utf-8")
    second.write_text('{"parameters":{"b":2,"a":1},"sets":{"P":["p1"]},"name":"X"}', encoding="utf-8")

    assert campaign._sha256_instance_content(first) == campaign._sha256_instance_content(second)


def test_content_digest_is_none_for_a_malformed_instance(tmp_path) -> None:
    """Never invent a digest: the file digest is recorded regardless, so None here is honest."""
    broken = tmp_path / "broken.json"
    broken.write_text("not json at all", encoding="utf-8")
    assert campaign._sha256_instance_content(broken) is None

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"name": "X"}', encoding="utf-8")
    assert campaign._sha256_instance_content(incomplete) is None


def test_running_manifest_declares_the_provenance_fields_up_front(tmp_path, monkeypatch) -> None:
    """A run killed mid-solve leaves a "running" manifest. It must already show which fields a
    completed run carries, so a half-written manifest is not mistaken for an old-schema one."""
    monkeypatch.setattr(campaign, "RESULTS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(campaign, "HEARTBEAT_LOG", tmp_path / "runs" / "_heartbeat.log")

    captured: dict[str, object] = {}

    def capture_then_fail(point, output_root):
        path = campaign._manifest_path(point)
        captured.update(json.loads(path.read_text(encoding="utf-8")))
        raise RuntimeError("stop here")

    monkeypatch.setattr("clsc.campaign.toy.materialize_toy", capture_then_fail)

    campaign.run_point(_toy_point(), provenance=campaign.CodeProvenance(commit="a" * 40, dirty=False))

    assert captured["solve_status"] == "running"
    assert captured["code_dirty"] is False
    assert "instance_sha256" in captured
    assert captured["instance_sha256"] is None
    assert "instance_content_sha256" in captured


# ===========================================================================
# Aggregation
# ===========================================================================

def test_master_table_carries_provenance_through(tmp_path, monkeypatch) -> None:
    """Provenance that stops at the manifest is provenance nobody reads."""
    from clsc.analysis.campaign_01 import aggregate as agg

    runs = tmp_path / "runs"
    run_dir = runs / "exp1_verification" / "STD_I17_M4_T3" / "base"
    run_dir.mkdir(parents=True)
    (run_dir / "campaign_manifest.json").write_text(
        json.dumps(
            {
                "campaign_id": "campaign_01",
                "experiment_id": "exp1",
                "base_instance_id": "STD_I17_M4_T3",
                "solve_status": "success",
                "code_version": "a" * 40,
                "code_dirty": False,
                "instance_sha256": "b" * 64,
                "instance_content_sha256": "c" * 64,
                "objective_values": {"cost": 1.0, "emissions": 2.0},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(agg, "RUNS", runs)
    monkeypatch.setattr(agg, "TABLES", tmp_path / "tables")
    monkeypatch.setattr(agg, "ensure_analysis_dirs", lambda: (tmp_path / "tables").mkdir(exist_ok=True))

    frame = agg.aggregate()

    assert frame.loc[0, "code_dirty"] == False  # noqa: E712 -- pandas truth value
    assert frame.loc[0, "instance_sha256"] == "b" * 64
    assert frame.loc[0, "instance_content_sha256"] == "c" * 64
