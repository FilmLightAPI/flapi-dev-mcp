"""The server pulls new examples in the background when it starts.

Uses real git against a local "upstream" repo (no network): a script added
upstream must reach search_examples after the startup pull. Also guards that
the pull never blocks startup, never raises, never writes to stdout (the MCP's
channel), never clones, and can be turned off.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import repo, search, server


def _git(*args, cwd=None):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "init.defaultBranch=main", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    """A bare 'GitHub' repo with one example, a clone of it registered as the
    MCP's git source (like init does), and a second working copy to push from."""
    monkeypatch.delenv(repo.NO_PULL_ENV, raising=False)
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(cfgmod, "target_layout", lambda: (None, "config"))

    bare = tmp_path / "enhancements.git"
    _git("init", "--bare", str(bare))
    author = tmp_path / "author"
    _git("clone", str(bare), str(author))
    (author / "FLAPI Tools").mkdir()
    (author / "FLAPI Tools" / "list_jobs.py").write_text("# list every job\nimport flapi\n")
    _git("add", "-A", cwd=author)
    _git("commit", "-m", "first example", cwd=author)
    _git("push", "origin", "HEAD:main", cwd=author)

    checkout = tmp_path / "repo"
    _git("clone", str(bare), str(checkout))
    cfgmod.save_config({"sources": [{"type": "git", "path": str(checkout), "enabled": True}]})
    return author, checkout


def _publish(author: Path, name: str, body: str) -> None:
    (author / "FLAPI Tools" / name).write_text(body)
    _git("add", "-A", cwd=author)
    _git("commit", "-m", f"add {name}", cwd=author)
    _git("push", "origin", "HEAD:main", cwd=author)


def test_new_upstream_example_is_searchable_after_startup_pull(upstream):
    author, checkout = upstream
    _publish(author, "zebra_marker_export.py", "# export zebra markers\nimport flapi\n")
    assert search.search_examples("zebra")["results"] == []       # not here yet

    t = repo.pull_sources_in_background()
    t.join(30)
    assert (checkout / "FLAPI Tools" / "zebra_marker_export.py").is_file()
    hits = search.search_examples("zebra")["results"]
    assert any("zebra_marker_export.py" in str(h) for h in hits)


def test_server_start_does_not_wait_for_the_pull(upstream, monkeypatch):
    started = {}
    monkeypatch.setattr(repo, "clone_or_update", lambda **kw: time.sleep(3))
    monkeypatch.setattr(server.mcp, "run", lambda: started.setdefault("at", time.time()))
    t0 = time.time()
    server.run()
    assert started["at"] - t0 < 0.5


def test_offline_or_broken_remote_never_raises_or_prints(upstream, capfd):
    _, checkout = upstream
    _git("remote", "set-url", "origin", "/nonexistent/enhancements.git", cwd=checkout)
    t = repo.pull_sources_in_background()
    t.join(30)
    assert not t.is_alive()
    out, _ = capfd.readouterr()
    assert out == ""                       # stdout is the MCP's channel: must stay clean


def test_does_not_clone_a_missing_source(upstream, tmp_path):
    cfgmod.save_config({"sources": [{"type": "git", "path": str(tmp_path / "never-cloned"),
                                     "enabled": True}]})
    assert repo.pull_sources_in_background() is None
    assert not (tmp_path / "never-cloned").exists()


def test_can_be_turned_off(upstream, monkeypatch):
    monkeypatch.setenv(repo.NO_PULL_ENV, "1")
    assert repo.pull_sources_in_background() is None


def test_missing_git_never_raises(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(repo.subprocess, "run", boom)
    (tmp_path / ".git").mkdir()
    r = repo.clone_or_update(dest=tmp_path)
    assert r["ok"] is False and "git" in r["message"]
