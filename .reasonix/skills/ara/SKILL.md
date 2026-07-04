---
name: ara
description: Agent-Native Research Artifact (ARA) protocol - create, validate, and manage machine-executable research packages.
runAs: subagent
allowed-tools: bash,read,write_file,edit_file,glob,ls
model: deepseek-chat
max-iters: 32
---

# ARA (Agent-Native Research Artifact) Skill

Manage research artifacts using the ARA protocol. ARA provides a structured,
machine-executable format for recording research processes, claims, evidence,
and exploration trails.

## Overview

The ARA CLI (`ara`) is the entry point. Install it from the project root with:

```bash
pip install -e .
```

Verify installation:

```bash
ara --help
```

## Artifact Structure

An ARA artifact directory has this layout:

```
<artifact-dir>/
  PAPER.md                 # root manifest + layer index
  logic/                   # cognitive layer
    claims.md              # falsifiable claims
    problem.md             # observations, gaps, assumptions
    experiments.md         # experiment plans
    solution/
      architecture.md
      algorithm.md
      constraints.md
    related_work.md
  src/                     # physical layer
    configs/
    environment.md
  trace/
    exploration_tree.yaml  # exploration DAG
  evidence/
    tables/
    figures/
```

## Commands Reference

### 1. Initialize a new artifact

```bash
ara init <dir> [--title "Title"] [--domain "domain"]
```

Scaffolds a complete, structurally-valid skeleton. Use this to start a new
research artifact from scratch.

**Example:**
```bash
ara init ./my-research --title "Attention Optimization" --domain "ml"
```

### 2. Compile from a repository

```bash
ara compile <dir> --repo <repo-path>
```

Compiles an existing code repository into an ARA skeleton. Produces structural
scaffolding; semantic content (claims, dead ends) must be filled in after.

**Example:**
```bash
ara compile ./ara-artifact --repo ./source-code
```

### 3. Capture research events

Record incremental findings as research progresses.

#### Add a claim
```bash
ara capture <dir> --claim --id C01 --title "Title" \
  --statement "The claim statement." \
  --status supported \
  --proof "EV01,EV02" \
  --deps "C01" \
  --tags "tag1,tag2" \
  --provenance user
```

Status values: `supported`, `refuted`, `unsupported`, `staged`, `open`

#### Add an experiment
```bash
ara capture <dir> --experiment --id E01 --title "Exp Name" \
  --statement "Objective description" \
  --proof "EV01"
```

#### Add an evidence item
```bash
ara capture <dir> --evidence --id EV01 --title "Result table" \
  --statement "Description of the evidence"
```

#### Add a tree node (exploration graph)
```bash
ara capture <dir> --node question --id N02 --parent N01 \
  --title "Sub-question" \
  --statement "Detailed description"
```

Node types: `question`, `experiment`, `decision`, `dead_end`, `pivot`, `result`

#### Add a dead end (important: preserve failures!)
```bash
ara capture <dir> --node dead_end --id N03 --parent N01 \
  --title "Rejected approach" \
  --tried "What was attempted" \
  --failed "Why it failed" \
  --lesson "What was learned"
```

### 4. Validate structure (Seal Level 1)

```bash
ara validate <dir> [--json]
```

Checks structural integrity: required files exist, IDs are consistent,
references resolve. Returns non-zero exit code on failure.

Use `--json` for machine-readable output.

### 5. Semantic review (Seal Level 2)

```bash
ara review <dir> [--json]
```

Performs a deeper semantic review and scores the artifact across multiple
dimensions. Writes a detailed report to `level2_report.json`.

### 6. Visualize the exploration process

```bash
ara visualize <dir>
```

Renders a text summary of the exploration process map showing the research
trajectory, dead ends, and key pivot points.

## Typical Workflow

### Starting new research

1. **Initialize** the artifact:
   ```bash
   ara init ./research-foo --title "Foo Optimization" --domain "systems"
   ```

2. **Define the problem** by editing `logic/problem.md`:
   - Add observations (O01, O02, ...)
   - Add gaps (G01, G02, ...)
   - List assumptions (A01, A02, ...)
   - State the key insight

3. **Validate** early and often:
   ```bash
   ara validate ./research-foo
   ```

### During research (incremental capture)

As you make progress, capture events:

1. Add claims when you formulate them:
   ```bash
   ara capture ./research-foo --claim --id C01 --title "X improves Y" \
     --statement "Using X reduces Y by 30%." --status staged
   ```

2. Add experiments as you plan them:
   ```bash
   ara capture ./research-foo --experiment --id E01 --title "Ablation on X" \
     --statement "Measure Y with and without X."
   ```

3. Record dead ends — they are first-class citizens in ARA:
   ```bash
   ara capture ./research-foo --node dead_end --id N05 --parent N01 \
     --title "Naive approach" \
     --tried "Tried naive implementation" \
     --failed "Too slow, O(n^2)" \
     --lesson "Need indexing structure"
   ```

4. Add evidence when you have results:
   ```bash
   ara capture ./research-foo --evidence --id EV01 --title "Benchmark results" \
     --statement "Table showing 30% improvement"
   ```

### Before sharing / publishing

1. Run structural validation:
   ```bash
   ara validate ./research-foo
   ```

2. Run semantic review:
   ```bash
   ara review ./research-foo
   ```

3. Visualize to check the narrative flow:
   ```bash
   ara visualize ./research-foo
   ```

## ID Naming Conventions

| Prefix | Type | Location |
|--------|------|----------|
| `C01`..`CNN` | Claim | `logic/claims.md` |
| `O01` | Observation | `logic/problem.md` |
| `G01` | Gap | `logic/problem.md` |
| `A01` | Assumption | `logic/problem.md` |
| `E01`..`ENN` | Experiment | `logic/experiments.md` |
| `EV01`.. | Evidence | `evidence/` |
| `N01`.. | Tree node | `trace/exploration_tree.yaml` |

## Provenance Values

- `user` — explicitly created by a human
- `ai_suggested` — proposed by AI, not yet verified
- `ai_verified` — AI-generated and human-checked
- `automated` — produced by a script/tool

## Task Instructions

When the user asks you to work with ARA artifacts:

1. First check if the `ara` CLI is available. If not, install it from the
   project root with `pip install -e .`
2. Determine which command(s) are needed based on the user's request.
3. Execute the commands and report results clearly.
4. When editing artifact files directly, preserve the existing format and
   conventions (markdown structure, YAML frontmatter, ID patterns).
5. Always run `ara validate` after making structural changes.
6. If the user asks about a specific file, read it with the `read` tool and
   explain its contents in the context of the ARA protocol.
