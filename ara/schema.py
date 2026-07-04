"""Data models for every ARA layer.

The models are the single source of truth for the on-disk format. Each model
knows how to serialise to and parse from the markdown / YAML representation used
by artifacts on disk, so that :mod:`ara.artifact` can round-trip an entire
artifact without loss.

Reference convention
--------------------
Cross-layer binding is expressed with bracketed identifiers:

  * ``C01`` .. ``CNN`` -- a claim in ``logic/claims.md``
  * ``O01`` / ``G01`` / ``A01`` -- observation / gap / assumption in ``problem.md``
  * ``E01`` .. ``ENN`` -- an experiment plan in ``logic/experiments.md``
  * ``EV01`` .. -- an evidence item (table/figure) under ``evidence/``

These identifiers are what the Level 1 validator threads together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import yaml

from ara.provenance import Provenance

# Valid status values for a claim.
CLAIM_STATUSES = ("supported", "refuted", "unsupported", "staged", "open")

# Valid node types in the exploration graph. ``dead_end`` and ``pivot`` are
# first-class: the whole point of the protocol is that they are preserved rather
# than discarded.
NODE_TYPES = ("question", "experiment", "decision", "dead_end", "pivot", "result")


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _parse_id_list(raw: Any) -> list[str]:
    """Parse a bracketed / comma / list reference field into a list of ids.

    Accepts ``[E01, E02]``, ``[C01]``, ``[]``, ``["Table 2"]`` or an actual list.
    Free-form quoted strings are kept verbatim so evidence can name things like
    ``"Table 2"`` that are not formal ids.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip().strip('"').strip("'") for x in raw if str(x).strip()]
    text = str(raw).strip()
    if not text or text == "[]":
        return []
    text = text.strip("[]")
    parts = [p.strip().strip('"').strip("'").strip() for p in text.split(",")]
    return [p for p in parts if p]


def _format_id_list(ids: Iterable[str]) -> str:
    items = list(ids)
    if not items:
        return "[]"
    inner = ", ".join(ids)
    return f"[{inner}]"


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _split_markdown_sections(text: str, heading_prefix: str) -> list[tuple[str, str]]:
    """Split markdown into ``(title, body)`` pairs at ``heading_prefix`` lines.

    ``heading_prefix`` is e.g. ``"## "``. The first chunk before any heading is
    dropped (it is usually a bare ``# Claims`` title).
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_body: list[str] = []
    for line in lines:
        if line.startswith(heading_prefix):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).strip()))
            current_title = line[len(heading_prefix):].strip()
            current_body = []
        elif current_title is not None:
            current_body.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_body).strip()))
    return sections


# Markdown bullet fields look like:  - **Key**: value
# (the closing ** comes BEFORE the colon). Match accordingly.
_FIELD_RE = re.compile(r"^-\s\*\*(?P<key>[^*]+)\*\*:\s*(?P<val>.*)$")


def _parse_fields(body: str) -> dict[str, str]:
    """Parse ``- **Key:** value`` bullet fields into a dict (last wins)."""
    fields: dict[str, str] = {}
    for line in body.splitlines():
        m = _FIELD_RE.match(line.strip())
        if m:
            fields[m.group("key").strip().lower()] = m.group("val").strip()
    return fields


# --------------------------------------------------------------------------- #
# Cognitive layer: claims
# --------------------------------------------------------------------------- #
@dataclass
class Claim:
    """A falsifiable assertion with proof references.

    The protocol demands that every claim be *falsifiable*: it carries explicit
    falsification criteria and a proof pointer into the evidence layer. A claim
    without a falsification criterion or without grounding evidence is flagged by
    the reviewer as epistemically unsound.
    """

    id: str
    title: str
    statement: str
    status: str = "open"
    falsification_criteria: str = ""
    proof: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    provenance: Provenance = Provenance.AI_SUGGESTED

    def __post_init__(self) -> None:
        self.provenance = Provenance.parse(self.provenance)
        if self.status not in CLAIM_STATUSES:
            # Normalise rather than raise: load should be forgiving.
            self.status = "open"

    # -- serialisation -----------------------------------------------------
    def to_markdown(self) -> str:
        lines = [
            f"## {self.id}: {self.title}",
            f"- **Statement**: {self.statement}",
            f"- **Status**: {self.status}",
            f"- **Falsification criteria**: {self.falsification_criteria}",
            f"- **Proof**: {_format_id_list(self.proof)}",
            f"- **Dependencies**: {_format_id_list(self.dependencies)}",
            f"- **Tags**: {_format_id_list(self.tags)}",
            f"- **Provenance**: {self.provenance.value}",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_section(cls, title: str, body: str) -> "Claim":
        # title looks like "C01: Attention-only architecture achieves SOTA"
        cid, _, ctitle = title.partition(":")
        fields = _parse_fields(body)
        return cls(
            id=cid.strip(),
            title=ctitle.strip(),
            statement=fields.get("statement", ""),
            status=fields.get("status", "open"),
            falsification_criteria=fields.get("falsification criteria", ""),
            proof=_parse_id_list(fields.get("proof", "")),
            dependencies=_parse_id_list(fields.get("dependencies", "")),
            tags=_parse_id_list(fields.get("tags", "")),
            provenance=Provenance.parse(fields.get("provenance")),
        )


def parse_claims(text: str) -> list[Claim]:
    """Parse the full ``logic/claims.md`` document into Claim objects."""
    return [
        Claim.from_section(title, body)
        for title, body in _split_markdown_sections(text, "## ")
    ]


def render_claims(claims: Iterable[Claim]) -> str:
    out = ["# Claims", ""]
    for c in claims:
        out.append(c.to_markdown())
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Cognitive layer: problem specification
# --------------------------------------------------------------------------- #
@dataclass
class Observation:
    id: str
    statement: str
    evidence: str = ""
    implication: str = ""

    def to_markdown(self) -> str:
        return (
            f"### {self.id}: {_after_colon(self.id, '')}\n"
            f"- **Statement**: {self.statement}\n"
            f"- **Evidence**: {self.evidence}\n"
            f"- **Implication**: {self.implication}\n"
        )


@dataclass
class Gap:
    id: str
    statement: str
    caused_by: list[str] = field(default_factory=list)
    existing_attempts: str = ""
    why_they_fail: str = ""

    def to_markdown(self) -> str:
        return (
            f"### {self.id}\n"
            f"- **Statement**: {self.statement}\n"
            f"- **Caused by**: {_format_id_list(self.caused_by)}\n"
            f"- **Existing attempts**: {self.existing_attempts}\n"
            f"- **Why they fail**: {self.why_they_fail}\n"
        )


@dataclass
class Insight:
    insight: str
    derived_from: list[str] = field(default_factory=list)
    enables: str = ""

    def to_markdown(self) -> str:
        return (
            f"- **Insight**: {self.insight}\n"
            f"- **Derived from**: {_format_id_list(self.derived_from)}\n"
            f"- **Enables**: {self.enables}\n"
        )


@dataclass
class Assumption:
    id: str
    statement: str

    def to_markdown(self) -> str:
        return f"- {self.id}: {self.statement}\n"


@dataclass
class ProblemSpec:
    """The contents of ``logic/problem.md``."""

    observations: list[Observation] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    insight: Insight = field(default_factory=lambda: Insight(""))
    assumptions: list[Assumption] = field(default_factory=list)

    def to_markdown(self) -> str:
        parts = ["# Problem Specification", ""]
        parts.append("## Observations")
        for o in self.observations:
            parts.append(o.to_markdown())
        parts.append("## Gaps")
        for g in self.gaps:
            parts.append(g.to_markdown())
        parts.append("## Key Insight")
        parts.append(self.insight.to_markdown())
        parts.append("## Assumptions")
        for a in self.assumptions:
            parts.append(a.to_markdown())
        return "\n".join(parts).rstrip() + "\n"

    @classmethod
    def from_markdown(cls, text: str) -> "ProblemSpec":
        spec = cls()
        # Split into H2 sections.
        h2 = _split_markdown_sections(text, "## ")
        section_map = {title.lower(): body for title, body in h2}
        for title, body in h2:
            tl = title.lower()
            if tl.startswith("observation"):
                for stitle, sbody in _split_markdown_sections(body, "### "):
                    f = _parse_fields(sbody)
                    spec.observations.append(
                        Observation(
                            id=stitle.split(":")[0].strip(),
                            statement=f.get("statement", ""),
                            evidence=f.get("evidence", ""),
                            implication=f.get("implication", ""),
                        )
                    )
            elif tl.startswith("gap"):
                for stitle, sbody in _split_markdown_sections(body, "### "):
                    f = _parse_fields(sbody)
                    spec.gaps.append(
                        Gap(
                            id=stitle.split(":")[0].strip(),
                            statement=f.get("statement", ""),
                            caused_by=_parse_id_list(f.get("caused by", "")),
                            existing_attempts=f.get("existing attempts", ""),
                            why_they_fail=f.get("why they fail", ""),
                        )
                    )
            elif tl.startswith("key insight"):
                f = _parse_fields(body)
                spec.insight = Insight(
                    insight=f.get("insight", ""),
                    derived_from=_parse_id_list(f.get("derived from", "")),
                    enables=f.get("enables", ""),
                )
            elif tl.startswith("assumption"):
                for line in body.splitlines():
                    line = line.strip()
                    if not line.startswith("-"):
                        continue
                    content = line[1:].strip()
                    aid, _, astmt = content.partition(":")
                    spec.assumptions.append(
                        Assumption(id=aid.strip(), statement=astmt.strip())
                    )
        return spec


def _after_colon(value: str, default: str) -> str:
    return value.split(":", 1)[1].strip() if ":" in value else default


# --------------------------------------------------------------------------- #
# Cognitive layer: experiment plans
# --------------------------------------------------------------------------- #
@dataclass
class Experiment:
    """A declarative experiment plan in ``logic/experiments.md``."""

    id: str
    name: str
    objective: str = ""
    config_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "planned"  # planned | running | completed | abandoned

    def to_markdown(self) -> str:
        return (
            f"## {self.id}: {self.name}\n"
            f"- **Objective**: {self.objective}\n"
            f"- **Config refs**: {_format_id_list(self.config_refs)}\n"
            f"- **Evidence refs**: {_format_id_list(self.evidence_refs)}\n"
            f"- **Status**: {self.status}\n"
        )

    @classmethod
    def from_section(cls, title: str, body: str) -> "Experiment":
        eid, _, name = title.partition(":")
        f = _parse_fields(body)
        return cls(
            id=eid.strip(),
            name=name.strip(),
            objective=f.get("objective", ""),
            config_refs=_parse_id_list(f.get("config refs", "")),
            evidence_refs=_parse_id_list(f.get("evidence refs", "")),
            status=f.get("status", "planned"),
        )


def parse_experiments(text: str) -> list[Experiment]:
    return [
        Experiment.from_section(title, body)
        for title, body in _split_markdown_sections(text, "## ")
    ]


def render_experiments(experiments: Iterable[Experiment]) -> str:
    out = ["# Experiments", ""]
    for e in experiments:
        out.append(e.to_markdown())
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Evidence layer
# --------------------------------------------------------------------------- #
@dataclass
class EvidenceItem:
    """A raw proof item: an exact result table or extracted figure data."""

    id: str
    kind: str = "table"  # table | figure | log | metric
    title: str = ""
    path: str = ""
    description: str = ""
    data: Any = None  # free-form: rows, points, etc.

    def to_markdown(self) -> str:
        lines = [
            f"# {self.id}: {self.title}",
            "",
            f"- **Kind**: {self.kind}",
            f"- **Path**: {self.path}",
            f"- **Description**: {self.description}",
        ]
        if self.data is not None:
            lines.append("")
            lines.append("```yaml")
            lines.append(yaml.safe_dump(self.data, sort_keys=False).strip())
            lines.append("```")
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Exploration graph: tree nodes
# --------------------------------------------------------------------------- #
@dataclass
class TreeNode:
    """A node in the exploration DAG.

    ``dead_end`` nodes are the protocol's mechanism for preserving the failures
    that a narrative paper would discard: they record what was tried, why it
    failed, and what was learned, so no downstream agent re-walks the same path.
    """

    id: str
    type: str = "question"
    title: str = ""
    description: str = ""
    result: str = ""
    choice: str = ""
    alternatives: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    children: list["TreeNode"] = field(default_factory=list)
    provenance: Provenance = Provenance.AI_SUGGESTED

    def __post_init__(self) -> None:
        self.provenance = Provenance.parse(self.provenance)
        if self.type not in NODE_TYPES:
            self.type = "question"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "type": self.type, "title": self.title}
        if self.description:
            d["description"] = self.description
        if self.result:
            d["result"] = self.result
        if self.choice:
            d["choice"] = self.choice
        if self.alternatives:
            d["alternatives"] = list(self.alternatives)
        if self.evidence:
            d["evidence"] = list(self.evidence)
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        if self.provenance != Provenance.AI_SUGGESTED:
            d["provenance"] = self.provenance.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TreeNode":
        children = [cls.from_dict(c) for c in d.get("children", []) or []]
        return cls(
            id=str(d.get("id", "")),
            type=str(d.get("type", "question")),
            title=str(d.get("title", "")),
            description=str(d.get("description", "") or "").strip(),
            result=str(d.get("result", "") or "").strip(),
            choice=str(d.get("choice", "") or ""),
            alternatives=list(d.get("alternatives", []) or []),
            evidence=list(d.get("evidence", []) or []),
            children=children,
            provenance=Provenance.parse(d.get("provenance")),
        )


# --------------------------------------------------------------------------- #
# Root manifest: PAPER.md frontmatter
# --------------------------------------------------------------------------- #
@dataclass
class PaperManifest:
    """The YAML frontmatter + layer index of ``PAPER.md``."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    ara_version: str = "1.0"
    domain: str = ""
    keywords: list[str] = field(default_factory=list)
    claims_summary: list[str] = field(default_factory=list)
    abstract: str = ""
    overview: str = ""
    layer_index: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "ara_version": self.ara_version,
            "domain": self.domain,
            "keywords": list(self.keywords),
            "claims_summary": list(self.claims_summary),
            "abstract": self.abstract,
        }
