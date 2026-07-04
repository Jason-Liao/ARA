"""ARA Compiler: lift legacy research input into an ARA artifact.

The ``compiler`` skill in the upstream repo is a *specification for an agent*:
there is no standalone binary that can semantically understand an arbitrary PDF
or repository. True compilation -- extracting claims from prose, recovering dead
ends from git history, digitising figures -- requires LLM reasoning.

This module provides the **mechanical scaffold** that such an agent would drive.
It offers two entry points:

  * :func:`compile_from_text` -- take a structured dict (title, abstract, claims,
    dead ends, ...) and produce a complete, valid artifact on disk. This is what
    an agent calls after it has understood the input.
  * :func:`compile_from_repo` -- scan a code repository for the cheapest
    structural signals (README, configs, git log) and produce a best-effort
    skeleton that an agent then refines.

The goal is to make the "Engineering Tax" (the gap between reviewer-sufficient
prose and agent-sufficient specification) cheap to pay: the compiler fills in as
much structure as it can mechanically, leaving only the genuinely semantic work
for an agent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ara.artifact import Artifact
from ara.exploration import ExplorationTree
from ara.provenance import Provenance
from ara.schema import (
    Claim,
    EvidenceItem,
    Experiment,
    Insight,
    Observation,
    PaperManifest,
    ProblemSpec,
    TreeNode,
)


def compile_from_text(
    output_dir: str | Path,
    *,
    title: str,
    abstract: str = "",
    domain: str = "",
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str = "",
    doi: str = "",
    claims: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    dead_ends: list[dict[str, Any]] | None = None,
    experiments: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> Artifact:
    """Build a complete artifact from semantically-extracted fields.

    Each ``claims`` item: ``{id, title, statement, status, falsification, proof, deps, tags, provenance}``.
    Each ``dead_ends`` item: ``{id, parent, title, tried, failed, lesson}``.
    Each ``evidence`` item: ``{id, kind, title, description, data}``.
    """
    art = Artifact(output_dir)
    art.manifest = PaperManifest(
        title=title,
        abstract=abstract,
        domain=domain,
        authors=list(authors or []),
        year=year,
        venue=venue,
        doi=doi,
        overview=abstract or f"ARA artifact compiled for: {title}",
        claims_summary=[c.get("title", c.get("id", "")) for c in (claims or [])],
    )

    for c in claims or []:
        art.add_claim(
            Claim(
                id=c["id"],
                title=c.get("title", ""),
                statement=c.get("statement", c.get("title", "")),
                status=c.get("status", "supported"),
                falsification_criteria=c.get("falsification", c.get("falsification_criteria", "")),
                proof=list(c.get("proof", []) or []),
                dependencies=list(c.get("deps", c.get("dependencies", [])) or []),
                tags=list(c.get("tags", []) or []),
                provenance=Provenance.parse(c.get("provenance", "user")),
            )
        )

    spec = ProblemSpec()
    for o in observations or []:
        spec.observations.append(
            Observation(
                id=o["id"],
                statement=o.get("statement", ""),
                evidence=o.get("evidence", ""),
                implication=o.get("implication", ""),
            )
        )
    if observations:
        spec.insight = Insight(
            insight=f"Derived from {len(spec.observations)} observations",
            derived_from=[o["id"] for o in observations],
        )
    art.problem = spec

    for e in experiments or []:
        art.add_experiment(
            Experiment(
                id=e["id"],
                name=e.get("name", ""),
                objective=e.get("objective", ""),
                config_refs=list(e.get("config_refs", []) or []),
                evidence_refs=list(e.get("evidence_refs", []) or []),
                status=e.get("status", "completed"),
            )
        )

    for ev in evidence or []:
        art.add_evidence(
            EvidenceItem(
                id=ev["id"],
                kind=ev.get("kind", "table"),
                title=ev.get("title", ""),
                description=ev.get("description", ""),
                data=ev.get("data"),
            )
        )

    # Exploration tree: one root question, with dead ends attached.
    roots = [
        TreeNode(
            id="N01",
            type="question",
            title=f"Can we {title.lower().rstrip('.')}?",
            description="Root research question compiled from input.",
            provenance=Provenance.USER,
        )
    ]
    tree = ExplorationTree(roots=roots)
    for de in dead_ends or []:
        tree.add_dead_end(
            parent_id=de.get("parent", "N01"),
            node_id=de["id"],
            title=de.get("title", "Rejected approach"),
            what_was_tried=de.get("tried", de.get("what_was_tried", "")),
            why_it_failed=de.get("failed", de.get("why_it_failed", "")),
            lesson=de.get("lesson", ""),
            provenance=Provenance.parse(de.get("provenance", "ai-executed")),
        )
    art.tree = tree

    # Solution stubs.
    art.set_blob(
        "logic/solution/architecture.md",
        "# Architecture\n\nSystem design and component graph -- fill from input.\n",
    )
    art.set_blob(
        "logic/solution/algorithm.md",
        "# Algorithm\n\nMath + pseudocode for the core method -- fill from input.\n",
    )
    art.set_blob(
        "logic/solution/constraints.md",
        "# Constraints\n\nBoundary conditions and limitations.\n",
    )
    art.set_blob(
        "logic/related_work.md",
        "# Related Work\n\nTyped dependency graph of prior work.\n",
    )
    art.set_blob(
        "src/environment.md",
        "# Environment\n\n- **Dependencies**: \n- **Hardware**: \n- **Seeds**: \n",
    )
    art.save()
    return art


def compile_from_repo(repo_dir: str | Path, output_dir: str | Path) -> Artifact:
    """Best-effort skeleton from a code repository.

    Mechanically extracts a title (from README H1), a domain guess (from
    keywords), and a list of config files. Semantic content (claims, dead ends)
    is left empty for an agent to fill -- this is the explicit boundary between
    mechanical compilation and semantic understanding.
    """
    repo = Path(repo_dir)
    title = repo.name
    readme = _find_readme(repo)
    if readme:
        text = readme.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            title = m.group(1).strip()

    art = Artifact(output_dir)
    art.manifest = PaperManifest(
        title=title,
        domain="",
        overview=f"ARA skeleton compiled from repository: {repo}",
        claims_summary=[],
    )
    art.set_blob(
        "logic/solution/architecture.md",
        f"# Architecture\n\nCompiled from {repo.name}. An agent should describe the component graph.\n",
    )
    art.set_blob("logic/solution/algorithm.md", "# Algorithm\n\nFill from source.\n")
    art.set_blob("logic/solution/constraints.md", "# Constraints\n\nFill from source.\n")
    art.set_blob("logic/related_work.md", "# Related Work\n\nFill from citations / README.\n")

    env_lines = ["# Environment", ""]
    configs = _find_configs(repo)
    if configs:
        env_lines.append("- **Configs**:")
        for c in configs[:20]:
            env_lines.append(f"  - {c}")
    env_lines += ["- **Dependencies**: see requirements / package files", "- **Hardware**: ", "- **Seeds**: "]
    art.set_blob("src/environment.md", "\n".join(env_lines) + "\n")

    art.tree = ExplorationTree(
        roots=[
            TreeNode(
                id="N01",
                type="question",
                title=f"What does {repo.name} investigate?",
                description="Root question compiled from repository skeleton.",
                provenance=Provenance.USER,
            )
        ]
    )
    art.save()
    return art


def _find_readme(repo: Path) -> Path | None:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = repo / name
        if p.exists():
            return p
    return None


def _find_configs(repo: Path) -> list[str]:
    patterns = ("*.yaml", "*.yml", "*.toml", "*.json", "*.cfg", "*.ini")
    configs: list[str] = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(p.match(pat) for pat in patterns) and "node_modules" not in str(p):
            try:
                configs.append(str(p.relative_to(repo)))
            except ValueError:
                pass
        if len(configs) >= 50:
            break
    return configs
