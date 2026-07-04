"""Command-line interface for the ARA protocol.

Maps the five upstream agent skills to concrete subcommands::

    ara init <dir>                       scaffold a new artifact          (compiler)
    ara compile <dir> --repo <path>      compile from a repository         (compiler)
    ara capture <dir> ...                record a claim / node / dead end  (research-manager)
    ara validate <dir>                   Seal Level 1 structural check     (rigor-reviewer)
    ara review <dir>                     Seal Level 2 semantic review      (rigor-reviewer)
    ara visualize <dir>                  render the process map            (research-visualizer)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ara.artifact import Artifact
from ara.compiler import compile_from_repo
from ara.exploration import ExplorationTree
from ara.provenance import Provenance
from ara.reviewer import Reviewer
from ara.schema import Claim, EvidenceItem, Experiment
from ara.validator import Severity, Validator
from ara.visualizer import render_summary


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    return handler(args)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ara", description="Agent-Native Research Artifact protocol tools.")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("init", help="scaffold a new, valid artifact skeleton")
    s.add_argument("dir")
    s.add_argument("--title", default="Untitled Artifact")
    s.add_argument("--domain", default="")

    s = sub.add_parser("compile", help="compile a repository into an ARA skeleton")
    s.add_argument("dir")
    s.add_argument("--repo", help="path to a code repository")

    s = sub.add_parser("capture", help="record a research event (research-manager)")
    s.add_argument("dir")
    s.add_argument("--claim", action="store_true", help="add a claim")
    s.add_argument("--experiment", action="store_true", help="add an experiment")
    s.add_argument("--evidence", action="store_true", help="add an evidence item")
    s.add_argument("--node", help="add a tree node (type: question|experiment|decision|dead_end|pivot)")
    s.add_argument("--parent", default="N01", help="parent node id for --node")
    s.add_argument("--id", required=True, help="entry id (e.g. C03, N05, EV02, E02)")
    s.add_argument("--title", default="")
    s.add_argument("--statement", default="")
    s.add_argument("--status", default="supported")
    s.add_argument("--proof", default="", help="comma-separated evidence ids")
    s.add_argument("--deps", default="", help="comma-separated claim ids")
    s.add_argument("--tags", default="")
    s.add_argument("--provenance", default="user")
    s.add_argument("--tried", default="", help="for dead_end: what was tried")
    s.add_argument("--failed", default="", help="for dead_end: why it failed")
    s.add_argument("--lesson", default="")

    s = sub.add_parser("validate", help="Seal Level 1 structural validation")
    s.add_argument("dir")
    s.add_argument("--json", action="store_true", help="emit JSON report")

    s = sub.add_parser("review", help="Seal Level 2 semantic review")
    s.add_argument("dir")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("visualize", help="render the exploration process map")
    s.add_argument("dir")

    return p


# --------------------------------------------------------------------------- #
# command handlers
# --------------------------------------------------------------------------- #
def _cmd_init(args: argparse.Namespace) -> int:
    art = Artifact.scaffold(args.dir, title=args.title, domain=args.domain)
    print(f"Initialized ARA artifact at {art.root}")
    print(f"  layers: logic/ src/ trace/ evidence/")
    print(f"  next: `ara validate {art.root}` to check structure")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    if not args.repo:
        print("error: --repo is required for compile", file=sys.stderr)
        return 2
    art = compile_from_repo(args.repo, args.dir)
    print(f"Compiled skeleton ARA from {args.repo} -> {art.root}")
    print("  note: semantic content (claims, dead ends) must be filled by an agent")
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    art = Artifact.load(args.dir)
    prov = Provenance.parse(args.provenance)

    if args.claim:
        art.add_claim(
            Claim(
                id=args.id,
                title=args.title or args.statement,
                statement=args.statement or args.title,
                status=args.status,
                proof=_split(args.proof),
                dependencies=_split(args.deps),
                tags=_split(args.tags),
                provenance=prov,
            )
        )
        art.save()
        print(f"Recorded claim {args.id} -> {art.root}/logic/claims.md")
    elif args.experiment:
        art.add_experiment(
            Experiment(
                id=args.id,
                name=args.title or args.id,
                objective=args.statement,
                evidence_refs=_split(args.proof),
            )
        )
        art.save()
        print(f"Recorded experiment {args.id} -> {art.root}/logic/experiments.md")
    elif args.evidence:
        art.add_evidence(
            EvidenceItem(id=args.id, title=args.title or args.id, description=args.statement)
        )
        art.save()
        print(f"Recorded evidence {args.id} -> {art.root}/evidence/")
    elif args.node:
        node_type = args.node
        if node_type == "dead_end":
            art.tree.add_dead_end(
                parent_id=args.parent,
                node_id=args.id,
                title=args.title or "Rejected approach",
                what_was_tried=args.tried,
                why_it_failed=args.failed,
                lesson=args.lesson,
                provenance=prov,
            )
        else:
            from ara.schema import TreeNode

            art.tree.add_child(
                args.parent,
                TreeNode(
                    id=args.id,
                    type=node_type,
                    title=args.title,
                    description=args.statement,
                    provenance=prov,
                ),
            )
        _write_tree(art)
        print(f"Recorded {node_type} node {args.id} -> {art.root}/trace/exploration_tree.yaml")
    else:
        print("error: specify --claim, --experiment, --evidence, or --node", file=sys.stderr)
        return 2
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    art = Artifact.load(args.dir)
    report = Validator(art).validate()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Seal Level 1 -- {'PASS' if report.valid else 'FAIL'}")
        print(f"  errors: {len(report.errors)}   warnings: {len(report.warnings)}")
        for f in report.findings:
            tag = f.severity.value.upper()
            loc = f" ({f.location})" if f.location else ""
            print(f"  [{tag}] {f.code}: {f.message}{loc}")
    return 0 if report.valid else 1


def _cmd_review(args: argparse.Namespace) -> int:
    art = Artifact.load(args.dir)
    report = Reviewer(art).review()
    out_path = art.root / "level2_report.json"
    out_path.write_text(report.to_json(), encoding="utf-8")
    if args.json:
        print(report.to_json())
    else:
        print(f"Seal Level 2 -- recommendation: {report.recommendation} (score {report.overall_score:.1f}/5)")
        for d in report.dimensions:
            print(f"  {d.name:22s} {d.score}/5")
        print(f"  report written to {out_path}")
    return 0


def _cmd_visualize(args: argparse.Namespace) -> int:
    print(render_summary(Artifact.load(args.dir)))
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "compile": _cmd_compile,
    "capture": _cmd_capture,
    "validate": _cmd_validate,
    "review": _cmd_review,
    "visualize": _cmd_visualize,
}


# --------------------------------------------------------------------------- #
def _split(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _write_tree(art: Artifact) -> None:
    (art.root / "trace").mkdir(parents=True, exist_ok=True)
    (art.root / "trace" / "exploration_tree.yaml").write_text(art.tree.to_yaml(), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
