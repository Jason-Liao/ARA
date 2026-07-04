"""Research visualizer: render the exploration graph as a process map.

This is the mechanical half of the ``research-visualizer`` skill: it turns the
``trace/exploration_tree.yaml`` DAG into a readable ASCII / markdown process map
so a human can maintain high-level oversight of an agent's trajectory without
reading terminal logs.

Dead ends are rendered with an explicit ``[x]`` marker so the failure knowledge
is visible at a glance -- the whole point of preserving it.
"""

from __future__ import annotations

from typing import Iterable

from ara.artifact import Artifact
from ara.exploration import ExplorationTree
from ara.schema import TreeNode

_TYPE_ICON = {
    "question": "?",
    "experiment": "E",
    "decision": "D",
    "dead_end": "x",
    "pivot": "~",
    "result": "=",
}


def render_tree(tree: ExplorationTree) -> str:
    """Render an exploration tree as an indented ASCII process map."""
    if not tree.roots:
        return "(empty exploration tree)\n"
    lines: list[str] = ["# Exploration Process Map", ""]
    for root in tree.roots:
        _render_node(root, prefix="", is_last=True, lines=lines)
    return "\n".join(lines) + "\n"


def _render_node(node: TreeNode, prefix: str, is_last: bool, lines: list[str]) -> None:
    icon = _TYPE_ICON.get(node.type, "*")
    connector = "└─ " if is_last else "├─ "
    marker = " [x]" if node.type == "dead_end" else ""
    lines.append(f"{prefix}{connector}[{icon}] {node.id}: {node.title}{marker}")
    child_prefix = prefix + ("   " if is_last else "│  ")
    children = node.children
    for i, child in enumerate(children):
        _render_node(child, child_prefix, is_last=(i == len(children) - 1), lines=lines)
    if node.type == "dead_end" and node.description:
        # show the failure reason indented under the dead end
        for line in node.description.splitlines():
            lines.append(f"{child_prefix}   {line}")


def render_summary(art: Artifact) -> str:
    """Render a one-screen summary of the whole artifact."""
    m = art.manifest
    lines = [
        f"# {m.title or 'Untitled'}",
        "",
        f"Domain: {m.domain or '-'}   Year: {m.year or '-'}   ARA: v{m.ara_version}",
        "",
        "## Inventory",
        f"- Claims: {len(art.claims)} ({_count(art.claims, 'supported')} supported, "
        f"{_count(art.claims, 'refuted')} refuted)",
        f"- Experiments: {len(art.experiments)}",
        f"- Evidence items: {len(art.evidence)}",
        f"- Exploration nodes: {len(art.tree)} ({len(art.tree.dead_ends())} dead ends)",
        "",
        "## Process Map",
    ]
    lines.append(render_tree(art.tree).rstrip())
    return "\n".join(lines) + "\n"


def _count(claims: Iterable, status: str) -> int:
    return sum(1 for c in claims if c.status == status)


def visualize_directory(path: str) -> str:
    return render_summary(Artifact.load(path))
