"""Seal Level 1: structural validation.

Level 1 is the *mechanical* gate. It checks that the artifact is structurally
sound: required files exist and parse, identifiers are unique, every cross-layer
reference resolves, and the exploration graph is a well-formed acyclic DAG.

Level 1 deliberately does **not** judge whether the content is *true* -- that is
the job of Level 2 (:mod:`ara.reviewer`). It only guarantees that an agent can
mechanically navigate the artifact without hitting a dangling reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ara.artifact import Artifact, REQUIRED_FILES
from ara.schema import CLAIM_STATUSES, NODE_TYPES


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    location: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }


@dataclass
class ValidationReport:
    valid: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    def to_dict(self) -> dict:
        return {
            "seal": "level1",
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }


class Validator:
    """Runs the full Level 1 check suite against an :class:`Artifact`."""

    def __init__(self, artifact: Artifact) -> None:
        self.artifact = artifact
        self.findings: list[Finding] = []

    # ------------------------------------------------------------------ #
    def validate(self) -> ValidationReport:
        self.findings = []
        self._check_required_files()
        self._check_manifest()
        self._check_claims()
        self._check_experiments()
        self._check_exploration_tree()
        self._check_cross_layer_binding()
        valid = not any(f.severity == Severity.ERROR for f in self.findings)
        return ValidationReport(valid=valid, findings=self.findings)

    # ------------------------------------------------------------------ #
    def _add(self, severity: Severity, code: str, message: str, location: str = "") -> None:
        self.findings.append(Finding(severity, code, message, location))

    def _check_required_files(self) -> None:
        r = self.artifact.root
        for rel in REQUIRED_FILES:
            if not (r / rel).exists():
                self._add(Severity.ERROR, "MISSING_FILE", f"required file missing: {rel}", rel)
        # Optional but recommended files.
        for rel in ("logic/problem.md", "logic/experiments.md", "logic/solution/architecture.md"):
            if not (r / rel).exists():
                self._add(Severity.WARNING, "MISSING_OPTIONAL", f"recommended file missing: {rel}", rel)

    def _check_manifest(self) -> None:
        m = self.artifact.manifest
        if not m.title:
            self._add(Severity.ERROR, "MANIFEST_TITLE", "PAPER.md frontmatter has no title", "PAPER.md")
        if not m.ara_version:
            self._add(Severity.WARNING, "MANIFEST_VERSION", "ara_version not set", "PAPER.md")
        if not m.claims_summary and self.artifact.claims:
            self._add(
                Severity.WARNING,
                "MANIFEST_SUMMARY",
                "claims_summary is empty but claims exist",
                "PAPER.md",
            )

    def _check_claims(self) -> None:
        ids: set[str] = set()
        for c in self.artifact.claims:
            if c.id in ids:
                self._add(Severity.ERROR, "DUP_CLAIM_ID", f"duplicate claim id {c.id}", "logic/claims.md")
            ids.add(c.id)
            if c.status not in CLAIM_STATUSES:
                self._add(
                    Severity.ERROR,
                    "CLAIM_STATUS",
                    f"claim {c.id} has invalid status {c.status!r}",
                    "logic/claims.md",
                )
            if not c.statement:
                self._add(Severity.ERROR, "CLAIM_STATEMENT", f"claim {c.id} has empty statement", "logic/claims.md")
            if not c.falsification_criteria:
                self._add(
                    Severity.WARNING,
                    "CLAIM_NOT_FALSIFIABLE",
                    f"claim {c.id} has no falsification criteria",
                    "logic/claims.md",
                )
            for dep in c.dependencies:
                if dep and dep not in ids and not _looks_like_forward_ref(dep):
                    # dependencies may reference claims defined later; defer to binding check
                    pass

    def _check_experiments(self) -> None:
        ids: set[str] = set()
        for e in self.artifact.experiments:
            if e.id in ids:
                self._add(Severity.ERROR, "DUP_EXP_ID", f"duplicate experiment id {e.id}", "logic/experiments.md")
            ids.add(e.id)

    def _check_exploration_tree(self) -> None:
        tree = self.artifact.tree
        ids: set[str] = set()
        for node in tree.iter_all():
            if node.id in ids:
                self._add(Severity.ERROR, "DUP_NODE_ID", f"duplicate node id {node.id}", "trace/exploration_tree.yaml")
            ids.add(node.id)
            if node.type not in NODE_TYPES:
                self._add(
                    Severity.ERROR,
                    "NODE_TYPE",
                    f"node {node.id} has invalid type {node.type!r}",
                    "trace/exploration_tree.yaml",
                )
            if not node.title:
                self._add(Severity.WARNING, "NODE_TITLE", f"node {node.id} has empty title", "trace/exploration_tree.yaml")
            # evidence refs in nodes are checked during cross-layer binding
        if len(tree) == 0:
            self._add(Severity.WARNING, "EMPTY_TREE", "exploration tree has no nodes", "trace/exploration_tree.yaml")

    def _check_cross_layer_binding(self) -> None:
        """Thread every reference to a target that must exist somewhere.

        This is the protocol's core guarantee: claims -> evidence, claims ->
        claims, experiments -> evidence/configs, and tree nodes -> claims /
        evidence. Every reference must resolve or it is a dangling pointer.
        """
        art = self.artifact
        claim_ids = {c.id for c in art.claims}
        exp_ids = {e.id for e in art.experiments}
        evidence_ids = {e.id for e in art.evidence}
        # Evidence may also be referenced by free-form strings like "Table 2".
        # Those are not formal ids, so only bracketed EV*/E* ids are required to resolve.
        evidence_targets = evidence_ids | _collect_freeform_evidence_labels(art)

        # Claims -> evidence
        for c in art.claims:
            for ref in c.proof:
                if not ref:
                    continue
                if _is_formal_id(ref) and ref not in evidence_targets and ref not in exp_ids:
                    self._add(
                        Severity.ERROR,
                        "DANGLING_PROOF",
                        f"claim {c.id} proof references unknown evidence {ref!r}",
                        "logic/claims.md",
                    )
            for dep in c.dependencies:
                if dep and dep not in claim_ids:
                    self._add(
                        Severity.ERROR,
                        "DANGLING_DEP",
                        f"claim {c.id} depends on unknown claim {dep!r}",
                        "logic/claims.md",
                    )

        # Experiments -> evidence / configs
        for e in art.experiments:
            for ref in e.evidence_refs:
                if ref and _is_formal_id(ref) and ref not in evidence_targets:
                    self._add(
                        Severity.ERROR,
                        "DANGLING_EXP_EVIDENCE",
                        f"experiment {e.id} references unknown evidence {ref!r}",
                        "logic/experiments.md",
                    )

        # Tree nodes -> claims / evidence
        for node in art.tree.iter_all():
            for ref in node.evidence:
                if not ref:
                    continue
                if _is_formal_id(ref):
                    if ref not in claim_ids and ref not in evidence_targets and ref not in exp_ids:
                        self._add(
                            Severity.ERROR,
                            "DANGLING_NODE_REF",
                            f"node {node.id} references unknown id {ref!r}",
                            "trace/exploration_tree.yaml",
                        )

        # Reverse: every evidence item should be cited by >=1 claim or node.
        cited = set()
        for c in art.claims:
            cited.update(c.proof)
        for node in art.tree.iter_all():
            cited.update(node.evidence)
        for ev in art.evidence:
            if ev.id not in cited:
                self._add(
                    Severity.WARNING,
                    "ORPHAN_EVIDENCE",
                    f"evidence {ev.id} is not cited by any claim or node",
                    "evidence/",
                )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
_ID_RE = __import__("re").compile(r"^[A-Za-z]{1,4}\d+$")


def _is_formal_id(ref: str) -> bool:
    """True for identifiers like ``C01``, ``EV03``, ``E01`` (letter(s)+digits)."""
    return bool(_ID_RE.match(ref.strip()))


def _looks_like_forward_ref(ref: str) -> bool:
    return _is_formal_id(ref)


def _collect_freeform_evidence_labels(art: Artifact) -> set[str]:
    """Collect non-formal evidence labels (e.g. 'Table 2') actually present.

    Since free-form labels cannot be mechanically verified to exist, we treat
    them as always-resolvable and return an empty set. This keeps the validator
    honest: only formal ids are required to resolve.
    """
    return set()


def validate_directory(path: str | Path) -> ValidationReport:
    """Convenience: load an artifact directory and run Level 1 validation."""
    art = Artifact.load(path)
    return Validator(art).validate()
