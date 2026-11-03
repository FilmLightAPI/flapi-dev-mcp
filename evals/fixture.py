"""Eval fixture: the harness makes its own media, job and scenes, then removes them.

- media: 3 short ProRes clips with distinct test patterns and source timecode,
  generated with ffmpeg into evals/media/ (cached, gitignored)
- job `flapi_eval` on localhost, one fresh scene per eval run so parallel runs
  never share state and scripts may modify their scene freely
- FLAPI calls go through evals/fl_fixture.py under the target build's venv,
  so the fixture uses the same build the MCP is configured for
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from flapi_dev_mcp import app_scripts
from flapi_dev_mcp import config as cfgmod

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media"
JOB = "flapi_eval"
CLIPS = [  # (name, ffmpeg lavfi source, start timecode)
    ("shot_a", "testsrc2=size=1920x1080:rate=24", "01:00:00:00"),
    ("shot_b", "smptebars=size=1920x1080:rate=24", "01:00:10:00"),
    ("shot_c", "mandelbrot=size=1920x1080:rate=24", "01:00:20:00"),
]
SECONDS = 2


def make_media() -> list[str]:
    MEDIA.mkdir(exist_ok=True)
    paths = []
    for name, src, tc in CLIPS:
        out = MEDIA / f"{name}.mov"
        if not out.exists():
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", src, "-t", str(SECONDS), "-c:v", "prores_ks",
                            "-profile:v", "1", "-pix_fmt", "yuv422p10le",
                            "-timecode", tc, str(out)], check=True)
        paths.append(str(out))
    return paths


def app_python() -> str:
    return _python()


def _python() -> str:
    venv = app_scripts.managed_venv()
    if venv is None or not (venv / "bin" / "python").exists():
        raise RuntimeError("no FLAPI venv for the target build; run `flapi-dev-mcp init`")
    return str(venv / "bin" / "python")


def _call(cmd: str, **args) -> dict:
    r = subprocess.run([_python(), str(HERE / "fl_fixture.py"), cmd, json.dumps(args)],
                       capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "error": (r.stderr or r.stdout).strip()[-800:]}


def setup(scenes: list[str]) -> dict:
    return _call("setup", job=JOB, scenes=scenes, media=make_media())


def marks(scene: str) -> dict:
    return _call("marks", job=JOB, scene=scene)


def teardown() -> dict:
    return _call("teardown", job=JOB)


def scene_path(scene: str) -> str:
    return f"localhost:{JOB}:{scene}"


def clean_media() -> None:
    shutil.rmtree(MEDIA, ignore_errors=True)


# --------------------------------------------------------------------------- #
# App Scripts: deploy dirs, live reload, load verification
# --------------------------------------------------------------------------- #

def deploy_dirs() -> list[str]:
    """Where an App Script may be written: the configured UI/server dirs plus
    the per-user scripts dir the app also scans."""
    bl = (cfgmod.load_config() or {}).get("baselight", {})
    dirs = [bl.get("ui_scripts_dir"), bl.get("server_scripts_dir"),
            str(Path.home() / "Library/Application Support/FilmLight/scripts")]
    return [d for d in dict.fromkeys(dirs) if d and Path(d).is_dir()]


def deployed() -> set[str]:
    return {str(p) for d in deploy_dirs() for p in Path(d).iterdir() if p.suffix == ".py"}


def undeploy(paths: list[str]) -> None:
    for p in paths:
        Path(p).unlink(missing_ok=True)
    if paths:
        app_scripts.reload_app_scripts("ui")


def _plugins_log() -> Path | None:
    pid = app_scripts._gui_baselight_pid()
    td = app_scripts._fltmpdir(pid) if pid else None
    return Path(td) / "plugins.log" if td else None


def verify_app_scripts(paths: list[str]) -> dict:
    """Reload the running app and check each deployed script loaded cleanly,
    from the plugins.log lines written after the reload. Builds that don't
    write that log (a session whose log folder went missing, e.g. after a crash
    restart) can't be checked automatically: the reload is still confirmed, and
    the result is marked for a manual check."""
    if not paths:
        return {"loaded": [], "missing": [], "errors": [], "note": "nothing deployed"}
    log = _plugins_log()
    if log is None:
        return {"loaded": [], "missing": paths, "errors": [], "note": "no running app GUI"}
    if not log.parent.is_dir():
        r = app_scripts.reload_app_scripts("ui")
        return {"loaded": [], "missing": [], "errors": [], "manual": True,
                "reloaded": bool(r.get("restarted")),
                "note": "app session has no log folder; load needs a manual check"}
    start = log.stat().st_size if log.exists() else 0
    reloaded = bool(app_scripts.reload_app_scripts("ui").get("restarted"))
    time.sleep(3)
    text = log.read_text(errors="replace")[start:] if log.exists() else ""
    resolved = {p: str(Path(p).resolve()) for p in paths}
    loaded = [p for p, r in resolved.items()
              if f"Loading script: {p}" in text or f"Loading script: {r}" in text]
    names = [Path(p).name for p in paths]
    errors = [ln for ln in text.splitlines()
              if re.search(r"Traceback|Error|Exception", ln) and
              (any(n in ln for n in names) or "Traceback" in ln)]
    return {"reloaded": reloaded, "loaded": loaded,
            "missing": [p for p in paths if p not in loaded], "errors": errors[:20],
            "log_tail": text[-3000:]}
