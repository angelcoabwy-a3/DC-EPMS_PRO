"""
tests/test_skill_audit.py
=========================
Tests for H16 — Skill Resolution Feedback Harness.

Strict TDD discipline: RED phase. All tests fail until
`backend/skill_audit.py` exists with the documented surface.

Coverage:

  Block A — Citation parser (regex extraction of canonical S-XXX-NN ids
            from commit-message-style text).
  Block B — Skill registry loader (parses docs/skills/skill-registry.md).
  Block C — File-path → expected-skills heuristic table.
  Block D — Per-commit auditor (gaps + unknown citations).
  Block E — Acceptance: audit the last 3 real commits in this repo's
            git history.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.skill_audit import (
    SKILL_ID_PATTERN,
    SkillAuditReport,
    SkillCitation,
    audit_commit,
    audit_commit_range,
    expected_skills_for_files,
    load_skill_registry,
    parse_commit_citations,
)


# ─── Block A — citation parser ────────────────────────────────────────────
class TestParseCommitCitations:

    def test_extracts_single_canonical_id(self):
        text = "feat(agent): H13 -- citing S-CONTINUITY-01 in the body."
        out = parse_commit_citations(text)
        assert out == ["S-CONTINUITY-01"]

    def test_extracts_multiple_distinct_ids(self):
        text = (
            "feat(ledger): closes audit by S-LEDGER-01 + S-PROPOSER-01. "
            "Also S-DET-02 stays untouched."
        )
        out = parse_commit_citations(text)
        # Order preserved from first appearance.
        assert out == ["S-LEDGER-01", "S-PROPOSER-01", "S-DET-02"]

    def test_deduplicates_repeated_ids(self):
        text = "S-DET-01 ... S-DET-01 again ... S-DET-01"
        out = parse_commit_citations(text)
        assert out == ["S-DET-01"]

    def test_ignores_false_positives(self):
        # `S-3-2` is not canonical (digits where letters expected).
        # `service-XX-01` is missing the leading `S-`.
        # `SH-FOO-01` starts with `SH` not `S-`.
        # `S-FOO-9` is only 1 digit (canonical demands 2+).
        text = "S-3-2, service-XX-01, SH-FOO-01, S-FOO-9 are NOT citations."
        out = parse_commit_citations(text)
        assert out == []

    def test_extracts_from_multi_line_commit_message(self):
        text = """feat(ai): wire new agent

        Per S-DET-01 the verdict computes pre-LLM. Tests follow
        S-TEST-01 floor. Audit gate per S-SAFETY-01.
        """
        out = parse_commit_citations(text)
        assert set(out) == {"S-DET-01", "S-TEST-01", "S-SAFETY-01"}

    def test_skill_id_pattern_is_exported(self):
        # The regex is part of the module's public surface for callers
        # that want to do their own scanning.
        assert SKILL_ID_PATTERN.search("foo S-LEDGER-01 bar") is not None
        assert SKILL_ID_PATTERN.search("S-XYZ-01") is not None
        assert SKILL_ID_PATTERN.search("S-FOO-9") is None  # single digit
        assert SKILL_ID_PATTERN.search("S-XXX") is None    # missing -NN


# ─── Block B — skill registry loader ──────────────────────────────────────
class TestLoadSkillRegistry:

    def test_loads_default_registry_has_minimum_skills(self):
        # The repo's registry must include the core IDs that have shipped.
        registry = load_skill_registry()
        for required in (
            "S-ROUTE-01", "S-DET-01", "S-DET-02", "S-TEST-01",
            "S-TEST-02", "S-TEST-03", "S-SEC-01", "S-SEC-02",
            "S-LEDGER-01", "S-PROPOSER-01", "S-COMMIT-01",
            "S-CONTINUITY-01",
        ):
            assert required in registry, f"registry missing {required}"

    def test_missing_file_returns_empty_set_no_crash(self, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist.md"
        out = load_skill_registry(nonexistent)
        assert out == set()

    def test_parses_explicit_registry_fixture(self, tmp_path: Path):
        # Minimal synthetic registry — proves the parser depends only on
        # the canonical pattern, not on the full repo doc.
        fixture = tmp_path / "mini-registry.md"
        fixture.write_text(
            "# Skills\n\n"
            "### `S-FOO-01` · Headline\n"
            "Body. Cross-ref [[S-BAR-02]].\n\n"
            "### `S-BAR-02` · Other\n"
            "Body.\n",
            encoding="utf-8",
        )
        out = load_skill_registry(fixture)
        assert out == {"S-FOO-01", "S-BAR-02"}


# ─── Block C — file path → expected skills heuristic ──────────────────────
class TestExpectedSkillsForFiles:

    def test_agents_path_includes_det_01(self):
        out = expected_skills_for_files(["backend/agents/procedure_architect.py"])
        assert "S-DET-01" in out

    def test_ledger_path_includes_ledger_01(self):
        out = expected_skills_for_files(["backend/ledger/forensic_ledger.py"])
        assert "S-LEDGER-01" in out

    def test_test_file_includes_test_01(self):
        out = expected_skills_for_files(["tests/test_phase_dag.py"])
        assert "S-TEST-01" in out

    def test_mop_path_includes_safety_01(self):
        out = expected_skills_for_files(["docs/operaciones/mops/MOP-001-ups.md"])
        assert "S-SAFETY-01" in out

    def test_frontend_view_includes_route_and_sec(self):
        out = expected_skills_for_files(["frontend/assets/js/views/optimizer.js"])
        assert "S-ROUTE-01" in out
        assert "S-SEC-01" in out

    def test_continuity_file_includes_continuity_01(self):
        out = expected_skills_for_files(["backend/agent_continuity.py"])
        assert "S-CONTINUITY-01" in out

    def test_unrelated_path_returns_empty(self):
        out = expected_skills_for_files(["LICENSE", "random/file.txt"])
        assert out == set()

    def test_multiple_files_union(self):
        out = expected_skills_for_files([
            "backend/ledger/forensic_ledger.py",
            "tests/test_forensic_ledger.py",
        ])
        # Union of {S-LEDGER-01} + {S-TEST-01}.
        assert "S-LEDGER-01" in out
        assert "S-TEST-01" in out


# ─── Block D — per-commit auditor (using synthetic git) ───────────────────
class TestAuditCommit:

    def test_clean_commit_has_no_gaps_no_unknowns(self, monkeypatch):
        # Synthetic commit: cites S-CONTINUITY-01 and touches the matching
        # file. Should report 0 gaps, 0 unknowns.
        def fake_git_show(sha: str) -> tuple[str, str, list[str]]:
            return (
                sha,
                "feat(agent): H13 per S-CONTINUITY-01",
                ["backend/agent_continuity.py"],
            )
        monkeypatch.setattr("backend.skill_audit._git_show", fake_git_show)

        report = audit_commit("abc1234")
        assert isinstance(report, SkillAuditReport)
        assert report.commit_sha == "abc1234"
        assert [c.skill_id for c in report.citations] == ["S-CONTINUITY-01"]
        assert "S-CONTINUITY-01" in report.expected_skills
        assert report.gap_skills == []
        assert report.unknown_citations == []

    def test_flags_unknown_citation(self, monkeypatch):
        def fake_git_show(sha: str) -> tuple[str, str, list[str]]:
            return (sha, "feat(x): per S-FAKE-99 (fictitious)", ["docs/note.md"])
        monkeypatch.setattr("backend.skill_audit._git_show", fake_git_show)

        report = audit_commit("def5678")
        assert "S-FAKE-99" in report.unknown_citations

    def test_flags_gap_when_expected_skill_not_cited(self, monkeypatch):
        # Touches backend/agents/ but cites NO skill — expected to flag
        # S-DET-01 as gap.
        def fake_git_show(sha: str) -> tuple[str, str, list[str]]:
            return (
                sha,
                "refactor(ai): cleanup imports",
                ["backend/agents/procedure_architect.py"],
            )
        monkeypatch.setattr("backend.skill_audit._git_show", fake_git_show)

        report = audit_commit("aaa1111")
        assert "S-DET-01" in report.gap_skills
        # No citations -> citations list is empty.
        assert report.citations == []

    def test_citation_carries_commit_sha_provenance(self, monkeypatch):
        def fake_git_show(sha: str) -> tuple[str, str, list[str]]:
            return (sha, "feat: S-DET-01", ["backend/agents/x.py"])
        monkeypatch.setattr("backend.skill_audit._git_show", fake_git_show)

        report = audit_commit("bbb2222")
        assert len(report.citations) == 1
        cit = report.citations[0]
        assert isinstance(cit, SkillCitation)
        assert cit.skill_id == "S-DET-01"
        assert cit.commit_sha == "bbb2222"


# ─── Block E — acceptance against real git history ────────────────────────
class TestAuditCommitRangeAcceptance:

    def test_audit_last_3_commits_returns_reports(self):
        """Audit the last 3 commits from this repo's actual git log.

        Skip when ``git`` is unavailable (CI containers without VCS) so
        the test does not become a flake on minimal images.
        """
        if subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).returncode != 0:
            pytest.skip("git not available in this environment")

        reports = audit_commit_range(since="HEAD~3")

        assert isinstance(reports, list)
        # `HEAD~3..HEAD` enumerates every commit reachable from HEAD but
        # not from HEAD~3 -- this includes branch ancestors when one of
        # those commits is a merge. So the lower bound is "at least 1"
        # and there is no meaningful upper bound for an audit harness.
        assert len(reports) >= 1
        for r in reports:
            assert isinstance(r, SkillAuditReport)
            # Every commit has at least a SHA (subject may be empty on
            # very early merge commits authored without a body).
            assert r.commit_sha
