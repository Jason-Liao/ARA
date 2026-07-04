"""Exploration graph management.

The exploration tree is the protocol's answer to the *Storytelling Tax*: instead
of compressing the branching research process into a linear narrative, ARA keeps
the full DAG, including every dead end, pivot, and abandoned alternative.

This module provides :class:`ExplorationTree`, which loads/writes
``trace/exploration_tree.yaml`` and supports incremental construction during a
research session (the mechanical half of the ``research-manager`` skill): adding
questions, experiments, decisions, dead ends and pivots, while guaranteeing the
invariants the validator relies on (unique ids, valid types, acyclicity).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

import yaml

from ara.provenance import Provenance
from ara.schema import NODE_TYPES, TreeNode

_HEADER = (
    "# Exploration Tree\n"
    "# Nodes preserve the full research trajectory. dead_end / pivot nodes are\n"
    "# first-class: they record what was tried and why it failed so no agent\n"
    "# re-walks the same path.\n"
)


class ExplorationTree:
    """An ordered forest of research-trajectory nodes."""

    def __init__(self, roots: list[TreeNode] | None = None) -> None:
        self.roots: list[TreeNode] = list(roots or [])

    # -- construction ------------------------------------------------------
    def add_root(self, node: TreeNode) -> None:
        self._check_id(node.id)
        self.roots.append(node)

    def add_child(self, parent_id: str, node: TreeNode) -> TreeNode:
        """Attach ``node`` as a child of the node with ``parent_id``.

        Raises ``KeyError`` if the parent is missing and ``ValueError`` if the
        new id already exists or the node type is unknown.

        The on-disk format is a tree (each node has exactly one parent), and
        unique ids are enforced, so cycles are structurally impossible -- there
        is no need for a separate cycle check.
        """
        parent = self.find(parent_id)
        if parent is None:
            raise KeyError(f"parent node {parent_id!r} not found")
        self._check_id(node.id)
        if node.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {node.type!r}")
        parent.children.append(node)
        return node

    def add_dead_end(
        self,
        parent_id: str,
        node_id: str,
        title: str,
        what_was_tried: str,
        why_it_failed: str,
        lesson: str = "",
        provenance: Provenance = Provenance.AI_EXECUTED,
    ) -> TreeNode:
        """Record a failed approach as a first-class dead-end node.

        Preserving dead ends is the central mechanical difference between an ARA
        and a narrative paper: the failure trace is what accelerates downstream
        agents (and, per the paper, can also constrain them).
        """
        description = f"Tried: {what_was_tried}"
        if why_it_failed:
            description += f"\nFailed because: {why_it_failed}"
        if lesson:
            description += f"\nLesson: {lesson}"
        node = TreeNode(
            id=node_id,
            type="dead_end",
            title=title,
            description=description.strip(),
            result=why_it_failed,
            provenance=provenance,
        )
        return self.add_child(parent_id, node)

    # -- query -------------------------------------------------------------
    def find(self, node_id: str) -> TreeNode | None:
        for node in self.iter_all():
            if node.id == node_id:
                return node
        return None

    def iter_all(self) -> Iterable[TreeNode]:
        """Depth-first iteration over every node in the forest."""
        stack: list[TreeNode] = list(self.roots)
        while stack:
            node = stack.pop()
            yield node
            # push children reversed so left-to-right order is preserved
            for child in reversed(node.children):
                stack.append(child)

    def parent_of(self, node_id: str) -> TreeNode | None:
        for node in self.iter_all():
            for child in node.children:
                if child.id == node_id:
                    return node
        return None

    def all_ids(self) -> set[str]:
        return {n.id for n in self.iter_all()}

    def dead_ends(self) -> list[TreeNode]:
        return [n for n in self.iter_all() if n.type == "dead_end"]

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"tree": [r.to_dict() for r in self.roots]}

    def to_yaml(self) -> str:
        return _HEADER + yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExplorationTree":
        roots = [TreeNode.from_dict(r) for r in (data.get("tree") or [])]
        return cls(roots=roots)

    @classmethod
    def from_yaml(cls, text: str) -> "ExplorationTree":
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("exploration tree must be a YAML mapping with a 'tree' key")
        return cls.from_dict(data)

    # -- internals ---------------------------------------------------------
    def _check_id(self, node_id: str) -> None:
        if not node_id:
            raise ValueError("node id must be non-empty")
        if node_id in self.all_ids():
            raise ValueError(f"duplicate node id {node_id!r}")

    def __len__(self) -> int:
        return sum(1 for _ in self.iter_all())

    def __deepcopy__(self, memo: dict[int, Any]) -> "ExplorationTree":
        return ExplorationTree(roots=[deepcopy(r) for r in self.roots])
