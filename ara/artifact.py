"""Artifact I/O: load, save, and scaffold an ARA on disk.

An artifact directory has this shape::

    <dir>/
      PAPER.md                 # root manifest + layer index
      logic/                   # cognitive layer
        claims.md
        problem.md
        experiments.md
        solution/
          architecture.md
          algorithm.md
          constraints.md
        related_work.md
      src/                     # physical layer
        configs/
        environment.md
      trace/
        exploration_tree.yaml  # exploration graph (DAG)
      evidence/
        tables/
        figures/

:mod:`ara.artifact` provides a forgiving loader (missing optional files are
simply empty) and a lossless saver, plus :meth:`Artifact.scaffold` which writes a
complete, valid skeleton (the mechanical half of the ``compiler`` skill).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ara.exploration import ExplorationTree
from ara.schema import (
    Claim,
    EvidenceItem,
    Experiment,
    PaperManifest,
    ProblemSpec,
    parse_claims,
    parse_experiments,
    render_claims,
    render_experiments,
)

PAPER_FILE = "PAPER.md"
CLAIMS_FILE = "logic/claims.md"
PROBLEM_FILE = "logic/problem.md"
EXPERIMENTS_FILE = "logic/experiments.md"
ARCH_FILE = "logic/solution/architecture.md"
ALGO_FILE = "logic/solution/algorithm.md"
CONSTRAINTS_FILE = "logic/solution/constraints.md"
RELATED_FILE = "logic/related_work.md"
ENV_FILE = "src/environment.md"
TRACE_FILE = "trace/exploration_tree.yaml"
EVIDENCE_DIR = "evidence"

REQUIRED_FILES = [
    PAPER_FILE,
    CLAIMS_FILE,
    TRACE_FILE,
]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<yaml>.*?)\n---\s*\n(?P<body>.*)$", re.DOTALL)


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into ``(frontmatter_dict, body)``."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group("yaml")) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, m.group("body")


def join_frontmatter(data: dict[str, Any], body: str) -> str:
    fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{fm}---\n{body}"


# --------------------------------------------------------------------------- #
# Artifact
# --------------------------------------------------------------------------- #
class Artifact:
    """An in-memory representation of an ARA directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifest = PaperManifest()
        self.claims: list[Claim] = []
        self.problem = ProblemSpec()
        self.experiments: list[Experiment] = []
        self.tree = ExplorationTree()
        self.evidence: list[EvidenceItem] = []
        # Raw markdown blobs for files we store verbatim (architecture, etc.).
        self._blobs: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # paths
    # ------------------------------------------------------------------ #
    def path(self, rel: str) -> Path:
        return self.root / rel

    # ------------------------------------------------------------------ #
    # load
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, root: str | Path) -> "Artifact":
        """Load an artifact directory.

        Missing optional files yield empty collections rather than errors; the
        :mod:`ara.validator` is responsible for reporting missing *required*
        files. This keeps loading composable with partial / in-progress
        artifacts written incrementally by the research-manager.
        """
        art = cls(root)
        r = art.root
        if not r.is_dir():
            raise FileNotFoundError(f"artifact directory not found: {r}")

        if (r / PAPER_FILE).exists():
            art._load_paper()
        if (r / CLAIMS_FILE).exists():
            art.claims = parse_claims(_read(r / CLAIMS_FILE))
        if (r / PROBLEM_FILE).exists():
            art.problem = ProblemSpec.from_markdown(_read(r / PROBLEM_FILE))
        if (r / EXPERIMENTS_FILE).exists():
            art.experiments = parse_experiments(_read(r / EXPERIMENTS_FILE))
        if (r / TRACE_FILE).exists():
            art.tree = ExplorationTree.from_yaml(_read(r / TRACE_FILE))
        art.evidence = _load_evidence(r / EVIDENCE_DIR)
        for rel in (ARCH_FILE, ALGO_FILE, CONSTRAINTS_FILE, RELATED_FILE, ENV_FILE):
            p = r / rel
            if p.exists():
                art._blobs[rel] = _read(p)
        return art

    def _load_paper(self) -> None:
        data, body = split_frontmatter(_read(self.path(PAPER_FILE)))
        m = self.manifest
        m.title = str(data.get("title", ""))
        m.authors = list(data.get("authors", []) or [])
        m.year = data.get("year")
        m.venue = str(data.get("venue", "") or "")
        m.doi = str(data.get("doi", "") or "")
        m.ara_version = str(data.get("ara_version", "1.0") or "1.0")
        m.domain = str(data.get("domain", "") or "")
        m.keywords = list(data.get("keywords", []) or [])
        m.claims_summary = list(data.get("claims_summary", []) or [])
        m.abstract = str(data.get("abstract", "") or "")
        # The body is regenerated from manifest + computed layer index, so we
        # only persist the free-form Overview prose (the part between the
        # "## Overview" and "## Layer Index" headings). Storing the whole body
        # would cause it to be re-wrapped and accumulate on every save.
        m.overview = _extract_overview(body)

    # ------------------------------------------------------------------ #
    # save
    # ------------------------------------------------------------------ #
    def save(self) -> None:
        """Write the full artifact to ``self.root`` (creating directories)."""
        r = self.root
        (r / "logic" / "solution").mkdir(parents=True, exist_ok=True)
        (r / "src" / "configs").mkdir(parents=True, exist_ok=True)
        (r / "trace").mkdir(parents=True, exist_ok=True)
        (r / EVIDENCE_DIR / "tables").mkdir(parents=True, exist_ok=True)
        (r / EVIDENCE_DIR / "figures").mkdir(parents=True, exist_ok=True)

        self._save_paper()
        _write(r / CLAIMS_FILE, render_claims(self.claims))
        _write(r / PROBLEM_FILE, self.problem.to_markdown())
        _write(r / EXPERIMENTS_FILE, render_experiments(self.experiments))
        _write(r / TRACE_FILE, self.tree.to_yaml())
        for rel, blob in self._blobs.items():
            _write(r / rel, blob)
        for ev in self.evidence:
            _save_evidence(r / EVIDENCE_DIR, ev)

    def _save_paper(self) -> None:
        m = self.manifest
        body = self._paper_body()
        _write(self.path(PAPER_FILE), join_frontmatter(m.to_dict(), body))

    def _paper_body(self) -> str:
        m = self.manifest
        lines: list[str] = []
        lines.append(f"# {m.title or 'Untitled Artifact'}")
        lines.append("")
        lines.append("## Overview")
        lines.append(m.overview or "Machine-executable research artifact (ARA).")
        lines.append("")
        lines.append("## Layer Index")
        lines.append("### Cognitive Layer (`/logic`)")
        lines.append("| File | Description |")
        lines.append("|------|-------------|")
        if self.claims:
            lines.append(f"| [claims.md](logic/claims.md) | {len(self.claims)} falsifiable claims |")
        if self.problem.observations or self.problem.gaps:
            lines.append("| [problem.md](logic/problem.md) | Observations, gaps, key insight |")
        if self.experiments:
            lines.append(f"| [experiments.md](logic/experiments.md) | {len(self.experiments)} experiment plans |")
        lines.append("### Exploration Graph (`/trace`)")
        lines.append("| File | Description |")
        lines.append("|------|-------------|")
        lines.append(
            f"| [exploration_tree.yaml](trace/exploration_tree.yaml) | "
            f"{len(self.tree)} nodes ({len(self.tree.dead_ends())} dead ends) |"
        )
        if self.evidence:
            lines.append("### Evidence (`/evidence`)")
            lines.append("| File | Description |")
            lines.append("|------|-------------|")
            lines.append(f"| tables/ & figures/ | {len(self.evidence)} evidence items |")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # mutation helpers (used by compiler / research-manager)
    # ------------------------------------------------------------------ #
    def set_blob(self, rel: str, content: str) -> None:
        self._blobs[rel] = content

    def get_blob(self, rel: str) -> str:
        return self._blobs.get(rel, "")

    def add_claim(self, claim: Claim) -> None:
        if any(c.id == claim.id for c in self.claims):
            raise ValueError(f"duplicate claim id {claim.id!r}")
        self.claims.append(claim)

    def add_experiment(self, experiment: Experiment) -> None:
        if any(e.id == experiment.id for e in self.experiments):
            raise ValueError(f"duplicate experiment id {experiment.id!r}")
        self.experiments.append(experiment)

    def add_evidence(self, item: EvidenceItem) -> None:
        if any(e.id == item.id for e in self.evidence):
            raise ValueError(f"duplicate evidence id {item.id!r}")
        self.evidence.append(item)

    # ------------------------------------------------------------------ #
    # scaffold
    # ------------------------------------------------------------------ #
    @classmethod
    def scaffold(
        cls,
        root: str | Path,
        title: str = "Untitled Artifact",
        domain: str = "",
    ) -> "Artifact":
        """Create a complete, structurally-valid skeleton artifact on disk.

        This is the mechanical half of the ``compiler`` skill: it produces the
        full directory layout with stub files so that an agent (or human) can
        fill in the content layer by layer and run the validator at any time.
        """
        art = cls(root)
        art.manifest = PaperManifest(
            title=title,
            domain=domain,
            ara_version="1.0",
            abstract="",
            overview="Scaffolded ARA artifact. Fill in each layer; the validator will report what remains.",
        )
        art.set_blob(
            ARCH_FILE,
            "# Architecture\n\nDescribe the system design and component graph here.\n",
        )
        art.set_blob(
            ALGO_FILE,
            "# Algorithm\n\nMath + pseudocode for the core method.\n",
        )
        art.set_blob(
            CONSTRAINTS_FILE,
            "# Constraints\n\nBoundary conditions and limitations.\n",
        )
        art.set_blob(
            RELATED_FILE,
            "# Related Work\n\nTyped dependency graph of prior work.\n",
        )
        art.set_blob(
            ENV_FILE,
            "# Environment\n\n- **Dependencies**: \n- **Hardware**: \n- **Seeds**: \n",
        )
        art.tree = ExplorationTree(
            roots=[
                __import__("ara").schema.TreeNode(
                    id="N01",
                    type="question",
                    title="Root research question",
                    description="What is the central question this artifact investigates?",
                )
            ]
        )
        art.save()
        return art


# --------------------------------------------------------------------------- #
# evidence on disk
# --------------------------------------------------------------------------- #
def _evidence_rel(item: EvidenceItem) -> str:
    sub = "figures" if item.kind == "figure" else "tables"
    name = item.path or f"{item.id}.md"
    return f"{EVIDENCE_DIR}/{sub}/{name}"


def _save_evidence(base: Path, item: EvidenceItem) -> None:
    rel = _evidence_rel(item)
    p = base.parent / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    _write(p, item.to_markdown())


def _load_evidence(base: Path) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if not base.is_dir():
        return items
    for md in sorted(base.rglob("*.md")):
        text = _read(md)
        # First H1 line is "EV01: title"
        title_line = ""
        body = text
        for line in text.splitlines():
            if line.startswith("# "):
                title_line = line[2:].strip()
                body = text.split(line, 1)[-1]
                break
        eid, _, etitle = title_line.partition(":")
        fields: dict[str, str] = {}
        for line in body.splitlines():
            mm = re.match(r"^-\s\*\*([^*]+):\*\*\s*(.*)$", line.strip())
            if mm:
                fields[mm.group(1).strip().lower()] = mm.group(2).strip()
        items.append(
            EvidenceItem(
                id=eid.strip(),
                kind=fields.get("kind", "table"),
                title=etitle.strip(),
                path=fields.get("path", md.name),
                description=fields.get("description", ""),
            )
        )
    return items


# --------------------------------------------------------------------------- #
# file helpers
# --------------------------------------------------------------------------- #
def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _extract_overview(body: str) -> str:
    """Extract the free-form Overview prose from a PAPER.md body.

    The body is regenerated on save from the manifest plus a computed layer
    index, so only the prose between ``## Overview`` and ``## Layer Index`` is
    preserved across round-trips. Anything before/after those headings (or the
    whole body when the headings are absent) is treated as overview prose.
    """
    import re

    m = re.search(r"##\s*Overview\s*\n(?P<ov>.*?)(?:\n##\s*Layer Index|\Z)", body, re.DOTALL)
    if m:
        return m.group("ov").strip()
    return body.strip()

