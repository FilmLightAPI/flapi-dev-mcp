"""init-project: idempotent AGENTS.md block between markers, never touching the
user's own text, and an @AGENTS.md import added once when CLAUDE.md exists."""

from __future__ import annotations

from flapi_dev_mcp import project
from flapi_dev_mcp.instructions import INSTRUCTIONS


def test_creates_agents_md(tmp_path):
    project.init_project(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith(project.START) and project.END in text and INSTRUCTIONS.strip() in text
    assert not (tmp_path / "CLAUDE.md").exists()        # never creates CLAUDE.md


def test_appends_to_existing_and_keeps_user_text(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My project\n\nRun tests with make test.\n")
    project.init_project(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# My project\n\nRun tests with make test.\n")
    assert text.count(project.START) == 1


def test_rerun_updates_in_place_without_duplicating(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"intro\n\n{project.START}\nold stale block\n{project.END}\n\noutro\n")
    project.init_project(tmp_path)
    project.init_project(tmp_path)
    text = agents.read_text()
    assert text.count(project.START) == 1 and "old stale block" not in text
    assert text.startswith("intro\n") and text.rstrip().endswith("outro")


def test_rerun_reports_already_current(tmp_path):
    project.init_project(tmp_path)
    assert any("already current" in line for line in project.init_project(tmp_path))


def test_claude_md_gets_import_once(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Notes\n")
    project.init_project(tmp_path)
    project.init_project(tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text().count("@AGENTS.md") == 1


def test_import_in_code_span_does_not_count(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Mention `@AGENTS.md` without importing it.\n")
    project.init_project(tmp_path)
    assert (tmp_path / "CLAUDE.md").read_text().rstrip().endswith("@AGENTS.md")
