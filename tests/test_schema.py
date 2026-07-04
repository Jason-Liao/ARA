"""Tests for the ARA schema: parsing & serialisation round-trips."""

import textwrap

from ara.schema import (
    Claim,
    Experiment,
    Observation,
    ProblemSpec,
    parse_claims,
    parse_experiments,
    render_claims,
    render_experiments,
)


CLAIMS_MD = textwrap.dedent(
    """\
    # Claims

    ## C01: Attention-only architecture achieves SOTA
    - **Statement**: A model based entirely on self-attention achieves SOTA BLEU.
    - **Status**: supported
    - **Falsification criteria**: A recurrent model trained identically scores higher BLEU.
    - **Proof**: [EV01]
    - **Dependencies**: []
    - **Tags**: [architecture, translation]
    - **Provenance**: user

    ## C02: Transformers train faster
    - **Statement**: The Transformer requires less training time than RNNs.
    - **Status**: supported
    - **Falsification criteria**: An RNN matches quality with equal compute.
    - **Proof**: [EV02]
    - **Dependencies**: [C01]
    - **Tags**: [efficiency]
    - **Provenance**: user-revised
    """
)


def test_parse_claims():
    claims = parse_claims(CLAIMS_MD)
    assert len(claims) == 2
    c1, c2 = claims
    assert c1.id == "C01"
    assert c1.title == "Attention-only architecture achieves SOTA"
    assert c1.status == "supported"
    assert c1.proof == ["EV01"]
    assert c1.tags == ["architecture", "translation"]
    assert c2.dependencies == ["C01"]


def test_claim_round_trip():
    claims = parse_claims(CLAIMS_MD)
    rendered = render_claims(claims)
    reparsed = parse_claims(rendered)
    assert [c.id for c in reparsed] == ["C01", "C02"]
    assert reparsed[0].statement == claims[0].statement
    assert reparsed[1].dependencies == ["C01"]


def test_problem_round_trip():
    md = textwrap.dedent(
        """\
        # Problem Specification

        ## Observations
        ### O1: Sequential computation bottleneck
        - **Statement**: RNNs process tokens sequentially.
        - **Evidence**: Section 1
        - **Implication**: Training time scales with sequence length.

        ## Gaps
        ### G1
        - **Statement**: No fully parallel sequence model.
        - **Caused by**: [O1]
        - **Existing attempts**: Convolutional models
        - **Why they fail**: Still require O(log n) operations.

        ## Key Insight
        - **Insight**: Self-attention computes all pairwise interactions in O(1) ops.
        - **Derived from**: [O1]
        - **Enables**: A fully attention-based architecture.

        ## Assumptions
        - A1: Sufficient GPU memory for the attention matrix.
        """
    )
    spec = ProblemSpec.from_markdown(md)
    assert len(spec.observations) == 1
    assert spec.observations[0].id == "O1"
    assert len(spec.gaps) == 1
    assert spec.gaps[0].caused_by == ["O1"]
    assert "Self-attention" in spec.insight.insight
    assert len(spec.assumptions) == 1
    # round-trip back
    again = ProblemSpec.from_markdown(spec.to_markdown())
    assert again.observations[0].statement == spec.observations[0].statement


def test_experiment_round_trip():
    md = textwrap.dedent(
        """\
        # Experiments

        ## E01: Train Transformer on WMT 2014
        - **Objective**: Measure BLEU on EN-DE.
        - **Config refs**: [configs/base.yaml]
        - **Evidence refs**: [EV01]
        - **Status**: completed
        """
    )
    exps = parse_experiments(md)
    assert len(exps) == 1
    assert exps[0].id == "E01"
    assert exps[0].evidence_refs == ["EV01"]
    again = parse_experiments(render_experiments(exps))
    assert again[0].objective == exps[0].objective
