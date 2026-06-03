"""Human-facing environment/config report.

`gather_status()` builds one structured dict from the saved config (re-resolving
each build root's layout live, so docs/wheel/example paths are always current).
That dict feeds multiple renderers: `render_text()` now, an HTML renderer later,
and it is also handy for an MCP status tool. Single source of truth, many views.
"""

from __future__ import annotations

from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc


def effective_venv(cfg: dict) -> tuple[str | None, str]:
    """Return (venv_path, source) where source is 'override' or 'derived'."""
    bl = cfg.get("baselight", {})
    override = bl.get("venv_override")
    if override:
        return override, "override"
    return bl.get("active_venv"), "derived"


def gather_status(cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else cfgmod.load_config()
    if cfg is None:
        return {"config_found": False, "config_path": str(cfgmod.CONFIG_PATH)}

    venv, venv_source = effective_venv(cfg)
    bl = cfg.get("baselight", {})

    # Re-resolve the default root's layout live for current docs/wheel/examples.
    default_path = cfg.get("default_root")
    default_layout = None
    for r in cfg.get("baselight_roots", []):
        if r.get("path") == default_path:
            default_layout = disc.resolve_layout(Path(r["path"]), r.get("kind", "release"), r.get("label"))
            break

    dr = disc.discover_data_root()  # for the list of available venvs (override candidates)

    return {
        "config_found": True,
        "config_path": str(cfgmod.CONFIG_PATH),
        "platform": cfg.get("platform"),
        "language": cfg.get("language"),
        "flapid_host": cfg.get("flapid_host"),
        "default_root": default_path,
        "default_version": default_layout.version if default_layout else None,
        "venv": venv,
        "venv_source": venv_source,
        "venv_candidates": [str(v) for v in dr.venvs],
        "flapi_python_path": bl.get("flapi_python_path"),
        "ui_scripts_dir": bl.get("ui_scripts_dir"),
        "server_scripts_dir": bl.get("server_scripts_dir"),
        "wheel": str(default_layout.wheel) if default_layout and default_layout.wheel else None,
        "flapid": str(default_layout.flapid) if default_layout and default_layout.flapid else None,
        "docs_html": str(default_layout.docs_html) if default_layout and default_layout.docs_html else None,
        "schema": str(default_layout.schema) if default_layout and default_layout.schema else None,
        "bundled_examples": str(default_layout.examples) if default_layout and default_layout.examples else None,
        "baselight_roots": cfg.get("baselight_roots", []),
        "sources": cfg.get("sources", []),
    }


# --------------------------------------------------------------------------- #
# Text renderer
# --------------------------------------------------------------------------- #

def _c(t: str, code: str, color: bool) -> str:
    return f"\033[{code}m{t}\033[0m" if color else t


def render_text(status: dict, color: bool = True) -> str:
    if not status.get("config_found"):
        return (f"No config found at {status['config_path']}.\n"
                f"Run `flapi-dev-mcp init` first.")

    b = lambda t: _c(t, "1", color)
    g = lambda t: _c(t, "32", color)
    y = lambda t: _c(t, "33", color)
    dim = lambda t: _c(t, "2", color)

    def row(label: str, value: object, missing_ok: bool = False) -> str:
        if value in (None, "", []):
            return f"  {y('•')} {label}: {y('not set')}"
        return f"  {g('✓')} {label}: {value}"

    lines: list[str] = []
    lines.append(b("FLAPI Developer MCP — status"))
    lines.append(dim(f"  config: {status['config_path']}"))

    lines.append(b("\nTarget"))
    lines.append(row("Baselight version", status["default_version"]))
    lines.append(row("build root", status["default_root"]))
    lines.append(row("flapid host", status["flapid_host"]))

    lines.append(b("\nPython / venv"))
    venv_tag = f" {dim('(' + status['venv_source'] + ')')}" if status["venv"] else ""
    lines.append(row("venv", (status["venv"] or "") + venv_tag if status["venv"] else None))
    lines.append(row("FLAPI Python", status["flapi_python_path"]))
    if status["venv_candidates"]:
        lines.append(dim(f"      override with: flapi-dev-mcp set-venv <path>"))
        for v in status["venv_candidates"]:
            mark = g(" ← selected") if v == status["venv"] else ""
            lines.append(dim(f"        - {v}{mark}"))

    lines.append(b("\nFLAPI assets (from target build root)"))
    lines.append(row("wheel", status["wheel"]))
    lines.append(row("flapid binary", status["flapid"]))
    lines.append(row("docs (python.html)", status["docs_html"]))
    lines.append(row("JSON schema", status["schema"]))
    lines.append(row("bundled examples", status["bundled_examples"]))

    lines.append(b("\nScript directories (Camp B)"))
    lines.append(row("UI scripts", status["ui_scripts_dir"]))
    lines.append(row("server scripts", status["server_scripts_dir"]))

    lines.append(b(f"\nBuild roots ({len(status['baselight_roots'])})"))
    for r in status["baselight_roots"]:
        tag = " [default]" if r.get("path") == status["default_root"] else ""
        en = "" if r.get("enabled", True) else dim(" (disabled)")
        lines.append(f"  - {r.get('kind')}: {r.get('path')}{tag}{en}")

    lines.append(b(f"\nContext sources ({len(status['sources'])})"))
    for s in status["sources"]:
        en = "" if s.get("enabled", True) else dim(" (disabled)")
        lines.append(f"  - {s.get('type')}: {s.get('path')}{en}")

    return "\n".join(lines)
