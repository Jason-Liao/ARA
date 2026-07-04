"""Seal Level 2: semantic epistemic review.

Level 2 evaluates whether the *content* of an ARA is epistemically sound: does
the evidence actually support the claims, is the argument coherent, is the
research process honestly documented? True Level 2 review is a semantic task
performed by an agent with reading comprehension.

This module provides the **review framework**: it runs a battery of structural
heuristics that approximate each of the six review dimensions, producing a
scored report (``level2_report.json``) with per-dimension strengths, weaknesses
and suggestions. An agent implementing the ``rigor-reviewer`` skill is expected
to override :meth:`Reviewer.score_dimension` with genuine semantic reasoning;
the heuristic scores here are a defensible baseline and a fallback.

The six dimensions:

  1. **Claim Grounding** -- every supported claim has resolving evidence.
  2. **Falsifiability** -- claims carry explicit falsification criteria.
  3. **Coherence** -- claim dependencies form a coherent argument chain.
  4. **Reproducibility** -- experiments specify configs and evidence.
  5. **Process Honesty** -- dead ends and pivots are documented.
  6. **Provenance Integrity** -- entries are tagged with trustworthy provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ara.artifact import Artifact
from ara.provenance import Provenance
from ara.validator import Severity, Validator


@dataclass
class DimensionScore:
    name: str
    score: int  # 1-5
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
        }


@dataclass
class ReviewReport:
    seal: str = "level2"
    overall_score: float = 0.0
    recommendation: str = "Weak Reject"
    dimensions: list[DimensionScore] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seal": self.seal,
            "overall_score": round(self.overall_score, 2),
            "recommendation": self.recommendation,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "findings": self.findings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


_RECOMMENDATION_BANDS = [
    (4.5, "Strong Accept"),
    (3.5, "Accept"),
    (2.5, "Weak Accept"),
    (1.5, "Weak Reject"),
    (0.0, "Reject"),
]


def _band(score: float) -> str:
    for threshold, label in _RECOMMENDATION_BANDS:
        if score >= threshold:
            return label
    return "Reject"


class Reviewer:
    """Runs the six-dimension Level 2 review against an :class:`Artifact`."""

    def __init__(self, artifact: Artifact) -> None:
        self.artifact = artifact

    def review(self) -> ReviewReport:
        report = ReviewReport()
        # Level 2 assumes Level 1 has passed; record Level 1 errors as findings.
        l1 = Validator(self.artifact).validate()
        for f in l1.findings:
            report.findings.append(
                {"severity": f.severity.value, "code": f.code, "message": f.message, "location": f.location}
            )

        for scorer in (
            self._dim_claim_grounding,
            self._dim_falsifiability,
            self._dim_coherence,
            self._dim_reproducibility,
            self._dim_process_honesty,
            self._dim_provenance,
        ):
            report.dimensions.append(scorer())

        scores = [d.score for d in report.dimensions]
        report.overall_score = sum(scores) / len(scores) if scores else 0.0
        report.recommendation = _band(report.overall_score)
        return report

    def write_report(self, path: str | Path | None = None) -> Path:
        """Write ``level2_report.json`` at the artifact root."""
        report = self.review()
        out = Path(path) if path else self.artifact.root / "level2_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_json(), encoding="utf-8")
        return out

    # ------------------------------------------------------------------ #
    # dimension scorers (heuristic baselines)
    # ------------------------------------------------------------------ #
    def _dim_claim_grounding(self) -> DimensionScore:
        d = DimensionScore(name="Claim Grounding", score=1)
        art = self.artifact
        supported = [c for c in art.claims if c.status == "supported"]
        evidence_ids = {e.id for e in art.evidence}
        grounded = 0
        for c in supported:
            if c.proof and any(p in evidence_ids for p in c.proof if p):
                grounded += 1
            else:
                d.weaknesses.append(f"supported claim {c.id} has no resolving evidence")
        if supported:
            ratio = grounded / len(supported)
            d.score = max(1, round(1 + 4 * ratio))
            if ratio == 1.0:
                d.strengths.append("all supported claims are grounded in evidence")
        else:
            d.score = 2
            d.weaknesses.append("no supported claims to evaluate")
        if d.score < 5:
            d.suggestions.append("wire every supported claim's Proof to a formal evidence id (EV##)")
        return d

    def _dim_falsifiability(self) -> DimensionScore:
        d = DimensionScore(name="Falsifiability", score=1)
        art = self.artifact
        if not art.claims:
            d.score = 1
            d.weaknesses.append("no claims present")
            return d
        falsifiable = sum(1 for c in art.claims if c.falsification_criteria)
        ratio = falsifiable / len(art.claims)
        d.score = max(1, round(1 + 4 * ratio))
        if ratio == 1.0:
            d.strengths.append("every claim carries explicit falsification criteria")
        else:
            d.weaknesses.append(f"{len(art.claims) - falsifiable} claims lack falsification criteria")
            d.suggestions.append("add a 'Falsification criteria' field to every claim")
        return d

    def _dim_coherence(self) -> DimensionScore:
        d = DimensionScore(name="Coherence", score=1)
        art = self.artifact
        claim_ids = {c.id for c in art.claims}
        broken = 0
        for c in art.claims:
            for dep in c.dependencies:
                if dep and dep not in claim_ids:
                    broken += 1
                    d.weaknesses.append(f"claim {c.id} depends on missing claim {dep}")
        if not art.claims:
            d.score = 1
            return d
        if broken == 0:
            d.score = 5
            d.strengths.append("all claim dependencies resolve")
        else:
            d.score = max(1, 5 - broken)
        # Bonus signal: problem -> insight -> claim chain exists.
        if art.problem.insight.insight and art.claims:
            d.strengths.append("problem specification and key insight are present")
            d.score = min(5, d.score + 1)
        return d

    def _dim_reproducibility(self) -> DimensionScore:
        d = DimensionScore(name="Reproducibility", score=1)
        art = self.artifact
        if not art.experiments:
            d.score = 2
            d.weaknesses.append("no experiment plans documented")
            d.suggestions.append("add experiment plans to logic/experiments.md")
            return d
        with_config = sum(1 for e in art.experiments if e.config_refs)
        with_evidence = sum(1 for e in art.experiments if e.evidence_refs)
        n = len(art.experiments)
        d.score = max(1, round(1 + 4 * ((with_config + with_evidence) / (2 * n))))
        if with_config == n:
            d.strengths.append("every experiment references a config")
        else:
            d.weaknesses.append(f"{n - with_config} experiments lack config references")
        env_blob = art.get_blob("src/environment.md")
        if "dependencies" in env_blob.lower() or "hardware" in env_blob.lower():
            d.strengths.append("environment.md records dependencies/hardware")
            d.score = min(5, d.score + 1)
        else:
            d.weaknesses.append("environment.md is sparse")
        return d

    def _dim_process_honesty(self) -> DimensionScore:
        d = DimensionScore(name="Process Honesty", score=1)
        art = self.artifact
        dead_ends = art.tree.dead_ends()
        n = len(art.tree)
        if n == 0:
            d.score = 1
            d.weaknesses.append("exploration tree is empty")
            return d
        if dead_ends:
            d.strengths.append(f"{len(dead_ends)} dead-end nodes preserve failure traces")
            d.score = 4
        else:
            d.weaknesses.append("no dead ends recorded; failure knowledge is likely lost")
            d.score = 2
            d.suggestions.append("record rejected approaches as dead_end nodes")
        # Refuted claims are another honesty signal.
        if any(c.status == "refuted" for c in art.claims):
            d.strengths.append("at least one claim is honestly marked refuted")
            d.score = min(5, d.score + 1)
        return d

    def _dim_provenance(self) -> DimensionScore:
        d = DimensionScore(name="Provenance Integrity", score=1)
        art = self.artifact
        # Claims provenance is tracked explicitly; tree nodes default to ai-suggested.
        user_tagged = sum(
            1 for c in art.claims if c.provenance in (Provenance.USER, Provenance.USER_REVISED)
        )
        if not art.claims:
            d.score = 2
            return d
        ratio = user_tagged / len(art.claims)
        d.score = max(1, round(1 + 4 * ratio))
        if ratio >= 0.5:
            d.strengths.append(f"{user_tagged}/{len(art.claims)} claims are human-confirmed")
        else:
            d.weaknesses.append("most claims are ai-suggested and not yet human-confirmed")
            d.suggestions.append("flip claim Provenance to user/user-revised once confirmed")
        return d


def review_directory(path: str | Path) -> ReviewReport:
    return Reviewer(Artifact.load(path)).review()
