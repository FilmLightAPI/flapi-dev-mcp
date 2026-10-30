"""Fake FilmLight installs on disk, so provisioning logic is testable without Baselight.

`fl_env` builds, under tmp_path:

  Applications/Baselight/7.0.1.25379/Baselight-7.0.1.25379.app   release build
  Applications/Baselight/Current -> 7.0.1.25379                   release symlink
  data/python/3.11-v7-venv                                        shared release venv
  SSD/checkouts/slate/build/.../Daylight-7.0.4.unknown.app        dev build
     Contents/python/3.11-v7-venv                                 dev build's own venv
  Development -> SSD                                              symlinked checkout path

Each build's `fl-setup-flapi-scripts -e` prints that build's venv, like the real one.
macOS layout only (.app bundles), so these tests are skipped elsewhere.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app layout")


def _touch_exe(path: Path, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body or "#!/bin/sh\n")
    path.chmod(0o755)


def _make_venv(venv: Path) -> None:
    _touch_exe(venv / "bin" / "python")


def _make_app(app: Path, version: str, venv: Path) -> None:
    c = app / "Contents"
    _touch_exe(c / "bin" / "flapid")
    _touch_exe(c / "bin" / "fl-setup-flapi-scripts",
               f'#!/bin/sh\n[ "$1" = "-e" ] && echo "{venv}"\n')
    whl = c / "share" / "flapi" / "python" / f"filmlightapi-{version}-py3-none-any.whl"
    whl.parent.mkdir(parents=True, exist_ok=True)
    whl.write_text("")
    (c / "share" / "flapi" / "examples" / "python").mkdir(parents=True)
    schema = c / "share" / "flapi" / "schema" / "schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text('{"classes": {}}')
    (c / "doc" / "flapi").mkdir(parents=True)
    (c / "doc" / "flapi" / "python.html").write_text("<html></html>")


@pytest.fixture
def fl_env(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    data = tmp_path / "data"

    rel_venv = data / "python" / "3.11-v7-venv"
    _make_venv(rel_venv)
    rel_dir = apps / "Baselight" / "7.0.1.25379"
    rel_app = rel_dir / "Baselight-7.0.1.25379.app"
    _make_app(rel_app, "7.0.1.25379", rel_venv)
    current = apps / "Baselight" / "Current"
    current.symlink_to(rel_dir)

    dev_real = (tmp_path / "SSD" / "checkouts" / "slate" / "build" / "daylight-7.0.4"
                / "DarwinArm-clang-1700" / "debug" / "Daylight-7.0.4.unknown.app")
    dev_venv = dev_real / "Contents" / "python" / "3.11-v7-venv"
    _make_venv(dev_venv)
    _make_app(dev_real, "7.0.4.99999", dev_venv)
    (tmp_path / "Development").symlink_to(tmp_path / "SSD")
    dev_alias = Path(str(dev_real).replace(str(tmp_path / "SSD"), str(tmp_path / "Development")))

    layout = dataclasses.replace(
        disc.LAYOUT,
        data_root=data,
        products=(
            disc.ProductLayout("baselight", apps / "Baselight", "*", current),
            disc.ProductLayout("daylight", apps / "Daylight", "*", apps / "Daylight" / "Current"),
        ),
        python_dir=data / "python",
        ui_scripts_candidates=(data / "scripts",),
        server_scripts_candidates=(data / "server-scripts",),
        site_prefs_path=None,
        user_prefs_path=None,
    )
    monkeypatch.setattr(disc, "LAYOUT", layout)
    monkeypatch.setattr(cfgmod, "LAYOUT", layout)
    monkeypatch.setattr(cfgmod, "DATA_ROOT", data)
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "cfg" / "config.json")

    env = SimpleNamespace(
        tmp=tmp_path, rel_app=rel_app, rel_venv=rel_venv, current=current,
        dev_app=dev_real, dev_alias=dev_alias, dev_venv=dev_venv,
    )

    def run_as(app: Path | None, kind: str = "dev-build") -> None:
        """Pretend `app` is the build serving flapid on :1984 (None = nothing running)."""
        br = disc.resolve_layout(app, kind) if app else None
        monkeypatch.setattr(cfgmod, "detect_running_build", lambda: br)
        monkeypatch.setattr(disc, "detect_running_build", lambda: br)

    env.run_as = run_as
    run_as(None)
    return env
