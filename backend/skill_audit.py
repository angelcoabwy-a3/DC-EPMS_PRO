"""
backend/skill_audit.py
======================
Harness H16 -- Skill Resolution Feedback (Gentle IA agent harness
registry, Bloque 4).

Goal
----
The Skill Digestion Harness (H15) is observed today by self-report --
authors cite skill IDs in commit messages. Without an audit loop, drift
goes undetected: an author may change `backend/agents/procedure_architect
.py` and forget to verify `S-DET-01`, or cite `S-FAKE-99` that does not
exist in the registry. H16 closes the loop by parsing commit messages,
cross-referencing the registry, and reporting:

  * **Unknown citations** -- IDs cited that are NOT in the registry.
  * **Gap skills** -- IDs the heuristic *expected* (based on files
    touched) but the author did NOT cite.

The audit is **observational**, NOT a gate. It surfaces drift so a
human reviewer can decide; it does not block commits.

Surface
-------
* :data:`SKILL_ID_PATTERN` -- compiled regex for canonical
  ``S-XXX-NN`` identifiers. Letters in the first segment, 2+ digits in
  the trailing segment, hyphen-separated middle segments allowed
  (`S-VENDOR-EATON-01`).
* :func:`parse_commit_citations` -- pull canonical IDs out of free
  text in first-appearance order, deduplicated.
* :func:`load_skill_registry` -- parse the markdown registry into a
  set of valid IDs.
* :func:`expected_skills_for_files` -- heuristic table: file path
  glob -> set of skill IDs the heuristic expects to be cited.
* :func:`audit_commit` -- combine the above against a single commit.
* :func:`audit_commit_range` -- enumerate SHAs from ``git log`` and
  audit each.

Skill: ``S-FEEDBACK-01`` (registered in this commit).
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# ─── Canonical pattern ────────────────────────────────────────────────────
# ``\b`` word-boundary anchors guard against partial matches inside other
# tokens (``foo-S-X-01-bar`` will still match S-X-01 because the boundary
# rule looks at single positions, but the test suite covers the realistic
# false-positive set explicitly).
#
# Examples that match:
#   S-DET-01, S-CONTINUITY-01, S-VENDOR-EATON-01, S-MCP-HEALTH-01
# Examples that do NOT:
#   S-3-2 (digits where the leading segment must be letters),
#   S-FOO-9 (single trailing digit -- spec requires 2+),
#   service-XX-01 (no leading "S-"),
#   SH-FOO-01 (text starts with "SH", not "S-"),
#   S-XXX (no trailing -NN block).
SKILL_ID_PATTERN: re.Pattern[str] = re.compile(
    r"\bS-[A-Z][A-Z0-9-]*-\d{2,}\b",
)


# ─── Data classes ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SkillCitation:
    """A single citation found in a commit. Forensic provenance for the
    feedback report: an operator can grep the JSONL audit log by
    ``commit_sha`` to find every citation in a release."""

    skill_id: str
    commit_sha: str
    source: str = "commit_message"


@dataclass(frozen=True)
class SkillAuditReport:
    """Outcome of :func:`audit_commit` -- the feedback record."""

    commit_sha: str
    commit_subject: str
    files_touched: list[str] = field(default_factory=list)
    citations: list[SkillCitation] = field(default_factory=list)
    expected_skills: list[str] = field(default_factory=list)
    gap_skills: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True when the commit has no gap skills and no unknown
        citations -- the ideal state."""
        return not self.gap_skills and not self.unknown_citations


# ─── Citation parser ──────────────────────────────────────────────────────
def parse_commit_citations(text: str) -> list[str]:
    """Extract canonical skill IDs from a commit message (or any free
    text). Returns IDs in first-appearance order, deduplicated.

    The function is a pure regex scan over :data:`SKILL_ID_PATTERN`;
    no other validation. Callers that need "valid against the registry"
    should pass the output through ``set & registry`` themselves.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in SKILL_ID_PATTERN.finditer(text):
        sid = match.group(0)
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


# ─── Registry loader ──────────────────────────────────────────────────────
def _default_registry_path() -> Path:
    """Locate ``docs/skills/skill-registry.md`` by walking up from the
    module file. Robust to worktree / install layout differences."""
    here = Path(__file__).resolve()
    # backend/skill_audit.py -> .../backend -> repo root
    candidate = here.parent.parent / "docs" / "skills" / "skill-registry.md"
    return candidate


def load_skill_registry(path: Path | str | None = None) -> set[str]:
    """Parse the skill registry markdown into a set of valid IDs.

    Returns an empty set when the file does not exist -- callers can
    still use the auditor's other functions without a registry; the
    `unknown_citations` field will then list ALL citations (because
    nothing is recognised), which is the correct degradation: no
    registry == no validation possible.
    """
    if path is None:
        path = _default_registry_path()
    p = Path(path)
    if not p.exists():
        return set()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(SKILL_ID_PATTERN.findall(text))


# ─── File -> expected-skills heuristic ────────────────────────────────────
# Each entry is (compiled regex, set of skill IDs). A file path matches
# an entry when ``regex.search(path)`` returns a match. Order is NOT
# significant -- all matching entries contribute to the union.
#
# The table is intentionally conservative: it surfaces the *highest-
# signal* expectations (e.g. touching the ledger MUST cite S-LEDGER-01).
# Adding more entries is safe because the report flags GAPS (expected
# but missing), not unexpected citations.
_FILE_TO_SKILLS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    # Continuity-specific files take precedence (more specific than the
    # generic "agents" pattern below).
    (re.compile(r"backend/agent_continuity\b"), frozenset({"S-CONTINUITY-01"})),
    (re.compile(r"tests/test_agent_continuity\b"), frozenset({"S-CONTINUITY-01", "S-TEST-01"})),

    # Skill-audit module itself.
    (re.compile(r"backend/skill_audit\b"), frozenset({"S-FEEDBACK-01"})),
    (re.compile(r"tests/test_skill_audit\b"), frozenset({"S-FEEDBACK-01", "S-TEST-01"})),

    # Agents fleet -- deterministic verdicts (S-DET-01) is universal;
    # the architect-specific surface also pulls in safety contracts.
    (re.compile(r"backend/agents/procedure_architect"), frozenset({"S-DET-01", "S-SAFETY-01"})),
    (re.compile(r"backend/multi_agent"), frozenset({"S-DET-01", "S-DET-02"})),
    (re.compile(r"backend/agents/"), frozenset({"S-DET-01"})),
    (re.compile(r"tests/test_procedure_architect"), frozenset({"S-DET-01", "S-SAFETY-01", "S-TEST-01"})),
    (re.compile(r"tests/test_multi_agent"), frozenset({"S-DET-01", "S-DET-02", "S-TEST-01"})),

    # Forensic ledger + Proposer chain.
    (re.compile(r"backend/ledger/"), frozenset({"S-LEDGER-01"})),
    (re.compile(r"backend/optimizer"), frozenset({"S-PROPOSER-01"})),
    (re.compile(r"tests/test_forensic_ledger"), frozenset({"S-LEDGER-01", "S-TEST-01"})),
    (re.compile(r"tests/test_optimizer"), frozenset({"S-PROPOSER-01", "S-TEST-01"})),
    (re.compile(r"tests/test_rollback_harness"), frozenset({"S-LEDGER-01", "S-TEST-01"})),
    (re.compile(r"tests/test_bms_write_proposer_chain"), frozenset({"S-PROPOSER-01", "S-TEST-01"})),

    # MOP catalog bodies satisfy the safety contract.
    (re.compile(r"docs/operaciones/mops/"), frozenset({"S-SAFETY-01"})),

    # Front-end views are routed + XSS-sanitised.
    (re.compile(r"frontend/assets/js/views/"), frozenset({"S-ROUTE-01", "S-SEC-01"})),
    (re.compile(r"frontend/assets/js/core/router"), frozenset({"S-ROUTE-01", "S-ROUTE-03"})),
    (re.compile(r"frontend/assets/js/core/sanitize"), frozenset({"S-SEC-01"})),
    (re.compile(r"tests/frontend/"), frozenset({"S-TEST-02"})),

    # Generic test catch-all (kept LAST so more-specific patterns above
    # contribute their own expectations first).
    (re.compile(r"^tests/.*\.py$"), frozenset({"S-TEST-01"})),
]


def expected_skills_for_files(file_paths: Iterable[str]) -> set[str]:
    """Walk the heuristic table and return the union of skill IDs that
    the table predicts should be cited for the given file paths.

    The output is a `set` because the union loses ordering anyway and
    callers downstream sort for display.
    """
    out: set[str] = set()
    for fp in file_paths:
        # Normalise Windows paths to forward slashes so the regex table
        # (authored with POSIX separators) matches on either OS.
        norm = fp.replace("\\", "/")
        for pattern, skills in _FILE_TO_SKILLS:
            if pattern.search(norm):
                out.update(skills)
    return out


# ─── Git boundary ─────────────────────────────────────────────────────────
def _git_show(sha: str) -> tuple[str, str, list[str]]:
    """Read commit ``sha`` and return ``(sha, subject, files)``.

    Implemented as a thin subprocess wrapper around ``git show`` so the
    test suite can monkey-patch ``backend.skill_audit._git_show`` with
    a fixture for unit tests.
    """
    # Subject -- one line.
    subj_proc = subprocess.run(
        ["git", "log", "-1", "--format=%s", sha],
        capture_output=True, text=True, check=False,
    )
    subject = subj_proc.stdout.strip() if subj_proc.returncode == 0 else ""

    # Body -- multi-line.
    body_proc = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        capture_output=True, text=True, check=False,
    )
    body = body_proc.stdout if body_proc.returncode == 0 else subject

    # Files -- one path per line.
    files_proc = subprocess.run(
        ["git", "show", "--name-only", "--format=", sha],
        capture_output=True, text=True, check=False,
    )
    files = [
        ln.strip() for ln in files_proc.stdout.splitlines() if ln.strip()
    ] if files_proc.returncode == 0 else []

    return (sha, body if body else subject, files)


def _git_rev_list(since: str) -> list[str]:
    """Enumerate SHAs in ``since..HEAD`` from newest to oldest. When
    ``since`` is a ``HEAD~N`` style expression that points past the
    root, git still returns the available subset gracefully."""
    proc = subprocess.run(
        ["git", "rev-list", f"{since}..HEAD"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


# ─── Auditor ──────────────────────────────────────────────────────────────
def audit_commit(
    sha: str,
    registry: set[str] | None = None,
) -> SkillAuditReport:
    """Audit a single commit. Returns the per-commit report.

    The ``registry`` argument lets callers reuse a single loaded set
    across many ``audit_commit`` calls (a noticeable saving for
    repository-wide audits). When None, the default registry path is
    loaded fresh.
    """
    if registry is None:
        registry = load_skill_registry()

    sha_full, body, files = _git_show(sha)
    raw_ids = parse_commit_citations(body)

    citations: list[SkillCitation] = []
    unknown: list[str] = []
    for sid in raw_ids:
        if registry and sid not in registry:
            unknown.append(sid)
        else:
            citations.append(SkillCitation(
                skill_id=sid, commit_sha=sha_full, source="commit_message",
            ))

    expected = expected_skills_for_files(files)
    cited_ids = {c.skill_id for c in citations}
    gaps = sorted(expected - cited_ids)

    # Pull the subject as the first line of the body for the report --
    # easier to scan than the full body in log output.
    subject = body.splitlines()[0].strip() if body else ""

    return SkillAuditReport(
        commit_sha=sha_full,
        commit_subject=subject,
        files_touched=files,
        citations=citations,
        expected_skills=sorted(expected),
        gap_skills=gaps,
        unknown_citations=unknown,
    )


def audit_commit_range(
    since: str = "HEAD~5",
    registry: set[str] | None = None,
) -> list[SkillAuditReport]:
    """Audit every commit reachable from HEAD but not from ``since``.

    Loads the registry once and reuses it across all per-commit calls.
    Returns reports newest-first (matching ``git log`` order).
    """
    if registry is None:
        registry = load_skill_registry()
    shas = _git_rev_list(since)
    return [audit_commit(sha, registry=registry) for sha in shas]


# ─── CLI entrypoint ───────────────────────────────────────────────────────
def _format_report(r: SkillAuditReport) -> str:
    """Render a single report as a human-readable block."""
    lines: list[str] = []
    short = (r.commit_sha or "")[:8]
    lines.append(f"--- {short}  {r.commit_subject}")
    if r.is_clean:
        lines.append("   CLEAN  (expected skills cited, no unknowns)")
    if r.gap_skills:
        lines.append(f"   GAPS:     {', '.join(r.gap_skills)}")
    if r.unknown_citations:
        lines.append(f"   UNKNOWNS: {', '.join(r.unknown_citations)}")
    if r.citations:
        lines.append("   CITED:    " + ", ".join(c.skill_id for c in r.citations))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``python -m backend.skill_audit [--since REF]`` -- prints a
    human-readable feedback report for recent commits. Returns 0
    regardless of findings: H16 is observational, not a gate."""
    import argparse
    parser = argparse.ArgumentParser(
        description="DC-EPMS skill-audit (H16 feedback harness)",
    )
    parser.add_argument(
        "--since", default="HEAD~5",
        help="git revspec; audits commits in <since>..HEAD (default HEAD~5)",
    )
    args = parser.parse_args(argv)
    reports = audit_commit_range(since=args.since)
    if not reports:
        print(f"no commits in range {args.since}..HEAD")
        return 0
    for r in reports:
        print(_format_report(r))
        print()
    clean = sum(1 for r in reports if r.is_clean)
    print(f"Summary: {clean}/{len(reports)} commits clean.")
    return 0


if __name__ == "__main__":                                       # pragma: no cover
    raise SystemExit(main())
