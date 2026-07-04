"""End-to-end tests for the CLI."""

import json
from pathlib import Path

from ara.cli import main


def test_init_and_validate(tmp_path: Path, capsys):
    rc = main(["init", str(tmp_path / "ara"), "--title", "My Paper", "--domain", "ML"])
    assert rc == 0
    rc = main(["validate", str(tmp_path / "ara")])
    assert rc == 0  # scaffold is structurally valid


def test_capture_and_review(tmp_path: Path):
    d = tmp_path / "ara"
    main(["init", str(d), "--title", "Capture Demo"])
    # record a claim grounded in evidence
    main(["capture", str(d), "--evidence", "--id", "EV01", "--title", "Result table"])
    main(
        [
            "capture",
            str(d),
            "--claim",
            "--id",
            "C01",
            "--title",
            "Works",
            "--statement",
            "The method works.",
            "--status",
            "supported",
            "--proof",
            "EV01",
            "--provenance",
            "user",
        ]
    )
    main(["capture", str(d), "--node", "dead_end", "--id", "N02", "--parent", "N01", "--title", "Bad idea", "--tried", "X", "--failed", "Y"])
    # validate should still pass
    assert main(["validate", str(d)]) == 0
    # review should produce a report file
    assert main(["review", str(d)]) == 0
    report = json.loads((d / "level2_report.json").read_text())
    assert report["seal"] == "level2"


def test_validate_json_output(tmp_path: Path, capsys):
    d = tmp_path / "ara"
    main(["init", str(d)])
    capsys.readouterr()  # discard init output
    rc = main(["validate", str(d), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["seal"] == "level1"
    assert data["valid"] is True


def test_visualize(tmp_path: Path, capsys):
    d = tmp_path / "ara"
    main(["init", str(d), "--title", "Viz Demo"])
    rc = main(["visualize", str(d)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Process Map" in out
    assert "N01" in out


def test_compile_from_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# My Cool Repo\n\nDoes cool stuff.\n")
    (repo / "config.yaml").write_text("lr: 0.1\n")
    out = tmp_path / "ara"
    rc = main(["compile", str(out), "--repo", str(repo)])
    assert rc == 0
    assert (out / "PAPER.md").exists()
    assert "My Cool Repo" in (out / "PAPER.md").read_text()


def test_validate_failure_exit_code(tmp_path: Path):
    (tmp_path / "PAPER.md").write_text("---\ntitle: X\n---\nbody")
    rc = main(["validate", str(tmp_path)])
    assert rc == 1
