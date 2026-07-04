"""Agent-Native Research Artifact (ARA) protocol implementation.

A research artifact is a machine-executable knowledge package structured around
four interlocking layers:

  * ``logic/``   -- cognitive layer (what & why): claims, problem, solution.
  * ``src/``     -- physical layer (how): configs, environment, code.
  * ``trace/``   -- exploration graph (the journey, including dead ends).
  * ``evidence/``-- raw proof: tables, figures, extracted data points.

All layers are bound together through cross-layer references so that every claim
resolves to an experiment, every experiment resolves to evidence, and every
evidence item is grounded in raw output. Dead ends are first-class nodes in the
exploration graph rather than discarded noise.

This package implements the mechanical core of the protocol described in
"The Last Human-Written Paper: Agent-Native Research Artifacts" (arXiv:2604.24658):

  * data models for every layer (:mod:`ara.schema`),
  * exploration-graph management with preserved dead ends (:mod:`ara.exploration`),
  * artifact I/O matching the on-disk format (:mod:`ara.artifact`),
  * Seal Level 1 structural validation (:mod:`ara.validator`),
  * Seal Level 2 semantic review framework (:mod:`ara.reviewer`),
  * a compiler that scaffolds an ARA from legacy input (:mod:`ara.compiler`),
  * an interactive process-map renderer (:mod:`ara.visualizer`),
  * a command-line interface (:mod:`ara.cli`).
"""

from ara.provenance import Provenance
from ara.schema import (
    Assumption,
    Claim,
    EvidenceItem,
    Experiment,
    Gap,
    Insight,
    Observation,
    PaperManifest,
    TreeNode,
)
from ara.exploration import ExplorationTree
from ara.artifact import Artifact
from ara.validator import Validator, ValidationReport
from ara.reviewer import Reviewer, ReviewReport

__version__ = "0.1.0"

__all__ = [
    "Provenance",
    "Claim",
    "Observation",
    "Gap",
    "Insight",
    "Assumption",
    "Experiment",
    "EvidenceItem",
    "TreeNode",
    "PaperManifest",
    "ExplorationTree",
    "Artifact",
    "Validator",
    "ValidationReport",
    "Reviewer",
    "ReviewReport",
    "__version__",
]
