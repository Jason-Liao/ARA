"""Tests for artifact I/O and the Level 1 / Level 2 seals."""

import json
from pathlib import Path

import pytest

from ara.artifact import Artifact
from ara.compiler import compile_from_text
from ara.provenance import Provenance
from ara.reviewer import Reviewer
from ara.schema import Claim, EvidenceItem, Experiment, TreeNode
from ara.validator import Severity, Validator


@pytest.fixture
def good_artifact(tmp_path: Path) -> Path:
    """A complete, structurally-valid artifact built via the compiler."""
    compile_from_text(
        tmp_path / "ara",
        title="Residual Learning for Image Recognition",
        abstract="Deep residual nets are easier to train and gain accuracy from depth.",
        domain="Computer Vision",
        authors=["He", "Zhang", "Ren", "Sun"],
        year=2016,
        venue="CVPR",
        doi="arXiv:1512.03385",
        claims=[
            {
                "id": "C01",
                "title": "Residual learning enables very deep nets",
                "statement": "Optimising residual mappings lets nets of 50+ layers converge.",
                "status": "supported",
                "falsification": "A plain net of equal depth converges with lower training error.",
                "proof": ["EV01"],
                "deps": [],
                "tags": ["depth", "residual"],
                "provenance": "user",
            },
        ],
        observations=[
            {"id": "O1", "statement": "Deeper plain nets have higher training error.", "implication": "Degradation problem."}
        ],
        experiments=[
            {"id": "E01", "name": "Train ResNet-34 on ImageNet", "evidence_refs": ["EV01"], "status": "completed"}
        ],
        evidence=[
            {"id": "EV01", "kind": "table", "title": "Plain vs residual on ImageNet", "description": "Table 2."}
        ],
        dead_ends=[
            {"id": "N02", "parent": "N01", "title": "Deeper plain network", "tried": "Scaled plain net to 34 layers", "failed": "Degradation problem", "lesson": "Use residual mappings."}
        ],
    )
    return tmp_path / "ara"


# --------------------------------------------------------------------------- #
# Level 1 validator
# --------------------------------------------------------------------------- #
def test_valid_artifact_passes_level1(good_artifact: Path):
    report = Validator(Artifact.load(good_artifact)).validate()
    assert report.valid, [f.message for f in report.findings if f.severity == Severity.ERROR]


def test_missing_required_file_fails(tmp_path: Path):
    (tmp_path / "PAPER.md").write_text("---\ntitle: X\n---\nbody")
    report = Validator(Artifact.load(tmp_path)).validate()
    assert not report.valid
    codes = [f.code for f in report.findings]
    assert "MISSING_FILE" in codes


def test_dangling_proof_reference(good_artifact: Path):
    art = Artifact.load(good_artifact)
    art.claims[0].proof = ["EV99"]  # does not exist
    report = Validator(art).validate()
    assert any(f.code == "DANGLING_PROOF" for f in report.findings)


def test_orphan_evidence_warning(good_artifact: Path):
    art = Artifact.load(good_artifact)
    art.add_evidence(EvidenceItem(id="EV99", title="uncited"))
    report = Validator(art).validate()
    assert any(f.code == "ORPHAN_EVIDENCE" and f.severity == Severity.WARNING for f in report.findings)


def test_non_falsifiable_claim_warns(good_artifact: Path):
    art = Artifact.load(good_artifact)
    art.claims[0].falsification_criteria = ""
    report = Validator(art).validate()
    assert any(f.code == "CLAIM_NOT_FALSIFIABLE" for f in report.findings)


# --------------------------------------------------------------------------- #
# Artifact round-trip
# --------------------------------------------------------------------------- #
def test_artifact_round_trip(good_artifact: Path):
    art = Artifact.load(good_artifact)
    assert art.manifest.title.startswith("Residual Learning")
    assert len(art.claims) == 1
    assert len(art.evidence) == 1
    assert len(art.tree) == 2  # N01 root + N02 dead end
    # save again and reload
    art.save()
    again = Artifact.load(good_artifact)
    assert again.claims[0].id == "C01"
    assert again.tree.dead_ends()[0].id == "N02"


def test_scaffold_creates_valid_structure(tmp_path: Path):
    art = Artifact.scaffold(tmp_path / "new", title="Test", domain="ML")
    assert (art.root / "PAPER.md").exists()
    assert (art.root / "logic" / "claims.md").exists()
    assert (art.root / "trace" / "exploration_tree.yaml").exists()
    report = Validator(Artifact.load(art.root)).validate()
    assert report.valid


# --------------------------------------------------------------------------- #
# Level 2 reviewer
# --------------------------------------------------------------------------- #
def test_level2_report(good_artifact: Path):
    art = Artifact.load(good_artifact)
    report = Reviewer(art).review()
    assert 1 <= report.overall_score <= 5
    assert len(report.dimensions) == 6
    names = [d.name for d in report.dimensions]
    assert "Claim Grounding" in names
    assert "Process Honesty" in names
    # dead end present should boost honesty
    honesty = next(d for d in report.dimensions if d.name == "Process Honesty")
    assert honesty.score >= 4


def test_level2_writes_json(good_artifact: Path):
    art = Artifact.load(good_artifact)
    out = Reviewer(art).write_report()
    assert out.name == "level2_report.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["seal"] == "level2"
    assert "recommendation" in data


# --------------------------------------------------------------------------- #
# Capture mutation
# --------------------------------------------------------------------------- #
def test_capture_claim(good_artifact: Path):
    art = Artifact.load(good_artifact)
    art.add_claim(
        Claim(
            id="C02",
            title="Second claim",
            statement="A second claim.",
            status="staged",
            provenance=Provenance.AI_SUGGESTED,
        )
    )
    art.save()
    assert len(Artifact.load(good_artifact).claims) == 2


def test_duplicate_claim_rejected(good_artifact: Path):
    art = Artifact.load(good_artifact)
    with pytest.raises(ValueError, match="duplicate"):
        art.add_claim(Claim(id="C01", title="dup", statement="x"))


def test_paper_md_is_idempotent(good_artifact: Path):
    """Saving and reloading must not accumulate/duplicate the PAPER.md body."""
    first = (good_artifact / "PAPER.md").read_text()
    Artifact.load(good_artifact).save()
    Artifact.load(good_artifact).save()  # save twice to surface accumulation
    twice = (good_artifact / "PAPER.md").read_text()
    assert first == twice
    # overview must not bleed into the regenerated body multiple times
    assert twice.count("## Overview") == 1
    assert twice.count("## Layer Index") == 1
