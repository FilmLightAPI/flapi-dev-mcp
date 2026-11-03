"""Guards for the eval harness's own scoring, so benchmarks only ever credit
official FLAPI (calls that exist in the target build's schema)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import run  # noqa: E402


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    monkeypatch.setattr(run, "_SCHEMA_METHODS", {
        "Scene": {"open_scene", "get_shot_ids"},
        "Application": {"get"},
        "QueueManager": {"create_local"},
        "Export": {"do_export_still"},
        "ThumbnailManager": {"get_poster_uri"},
    })


def test_official_calls_pass():
    src = """s = conn.Scene.open_scene(p, f); app = conn.Application.get()
qm = conn.QueueManager.create_local(); flapi.Export.do_export_still(qm, s, st)
c = flapi.Connection.get(); p = flapi.ScenePath({"Job": "j"})"""
    assert run.unofficial_calls(src) == []


@pytest.mark.parametrize("src,flagged", [
    ("conn.ThumbnailManager.render_frame(shot, {})", "ThumbnailManager.render_frame"),
    ("conn.FrameGrab.render_frames(s)", "FrameGrab.render_frames"),       # class not in build
    ("conn.Scene.set_layer_enabled(2, False)", "Scene.set_layer_enabled"),  # invented method
])
def test_unofficial_calls_flagged(src, flagged):
    assert run.unofficial_calls(src) == [flagged]


def test_unofficial_call_fails_the_run():
    case = {"id": "x", "expect": {"code_optional": True}}
    res = run.score(case, "", {"a.py": "conn.FrameGrab.render_frames(s)"})
    assert res["checks"]["official_api_only"] is False and res["passed"] is False
