"""Tests for the exploration tree (DAG) management."""

import pytest

from ara.exploration import ExplorationTree
from ara.provenance import Provenance
from ara.schema import TreeNode


def _make_tree() -> ExplorationTree:
    tree = ExplorationTree(
        roots=[TreeNode(id="N01", type="question", title="Root question")]
    )
    tree.add_child("N01", TreeNode(id="N02", type="experiment", title="First experiment"))
    return tree


def test_add_child_and_find():
    tree = _make_tree()
    assert tree.find("N02") is not None
    assert tree.find("N99") is None
    assert tree.parent_of("N02").id == "N01"


def test_duplicate_id_rejected():
    tree = _make_tree()
    with pytest.raises(ValueError, match="duplicate"):
        tree.add_child("N01", TreeNode(id="N02", type="experiment", title="dup"))


def test_unknown_parent_rejected():
    tree = _make_tree()
    with pytest.raises(KeyError):
        tree.add_child("N99", TreeNode(id="N03", type="experiment", title="orphan"))


def test_dead_end_preserved():
    tree = _make_tree()
    tree.add_dead_end(
        parent_id="N02",
        node_id="N03",
        title="Tried deeper plain network",
        what_was_tried="Scaled plain net to 34 layers",
        why_it_failed="Higher training error; degradation problem",
        lesson="Deeper is not better without residual connections",
    )
    ends = tree.dead_ends()
    assert len(ends) == 1
    assert ends[0].id == "N03"
    assert ends[0].provenance == Provenance.AI_EXECUTED
    assert "degradation problem" in ends[0].description


def test_yaml_round_trip():
    tree = _make_tree()
    tree.add_dead_end("N02", "N03", "dead", "tried X", "failed Y", "lesson Z")
    text = tree.to_yaml()
    again = ExplorationTree.from_yaml(text)
    assert {n.id for n in again.iter_all()} == {"N01", "N02", "N03"}
    assert again.dead_ends()[0].title == "dead"


def test_parent_of_and_tree_structure():
    tree = _make_tree()
    tree.add_dead_end("N02", "N03", "dead", "tried X", "failed Y", "lesson Z")
    # each node has exactly one parent (tree semantics)
    assert tree.parent_of("N03").id == "N02"
    assert tree.parent_of("N01") is None  # root has no parent
    # reusing an existing id is rejected, which is what keeps the tree acyclic
    with pytest.raises(ValueError, match="duplicate"):
        tree.add_child("N02", TreeNode(id="N01", type="experiment", title="reuse"))


def test_count():
    tree = _make_tree()
    assert len(tree) == 2
