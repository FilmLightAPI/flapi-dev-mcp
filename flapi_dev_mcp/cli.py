"""Command-line interface.

  python -m flapi_dev_mcp            # start the MCP server over stdio (default)
  python -m flapi_dev_mcp init       # guided onboarding: discover + write config
  python -m flapi_dev_mcp update     # git-pull context sources (later step; stub)
  python -m flapi_dev_mcp config ... # inspect/edit config.json (later step; stub)

`init` auto-discovers everything it can and only prompts for what's missing plus
optional extras (dev build roots, extra context sources). `--yes` accepts all
discovered defaults without prompting.
"""

from __future__ import annotations

import argparse
import sys

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc


# --------------------------------------------------------------------------- #
# Tiny prompt helpers (rich sequential prompts, no heavy TUI dependency)
# --------------------------------------------------------------------------- #

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def _bold(t: str) -> str: return _c(t, "1")
def _green(t: str) -> str: return _c(t, "32")
def _yellow(t: str) -> str: return _c(t, "33")
def _dim(t: str) -> str: return _c(t, "2")

def _heading(t: str) -> None:
    print("\n" + _bold(t))

def _ok(label: str, value: object) -> None:
    print(f"  {_green('✓')} {label}: {value}")

def _miss(label: str) -> None:
    print(f"  {_yellow('•')} {label}: {_yellow('not found')}")

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or default

def _ask_loop(prompt: str) -> list[str]:
    """Repeatedly prompt; blank line finishes."""
    out: list[str] = []
    while True:
        v = _ask(f"{prompt} (blank to finish)")
        if not v:
            break
        out.append(v)
    return out


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #

def _cmd_init(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty() and not args.yes

    print(_bold("FLAPI Developer MCP — setup"))
    print(_dim("macOS, Python only (v1). Auto-discovering your environment…"))

    d = disc.discover()
    dr = d.data_root

    _heading("Data root")
    if dr.exists:
        _ok("path", dr.root)
        (_ok if dr.flapi_python_path else _miss)("FLAPI Python", dr.flapi_python_path or "FLAPI Python")
        _ok("venvs", ", ".join(v.name for v in dr.venvs) or "(none)")
        (_ok if dr.ui_scripts_dir else _miss)("UI scripts dir", dr.ui_scripts_dir or "scripts/")
        (_ok if dr.server_scripts_dir else _miss)("server scripts dir", dr.server_scripts_dir or "server-scripts/")
    else:
        _miss("FilmLight data root (/Library/Application Support/FilmLight)")

    _heading(f"Release build roots ({len(d.release_roots)} found)")
    for br in d.release_roots:
        _ok(f"{br.version}", br.app)
        print(_dim(f"      wheel: {br.wheel.name if br.wheel else '—'}  flapid: {'yes' if br.flapid else 'no'}  "
                   f"docs: {'yes' if br.docs_html else 'no'}  schema: {'yes' if br.schema else 'no'}  "
                   f"examples: {'yes' if br.examples else 'no'}"))
    if not d.release_roots:
        _miss("no release builds under /Applications/Baselight")

    # Prompts: dev roots, flapid host, extra sources.
    dev_roots: list[tuple[str, str, str | None]] = list(args.dev_root or [])
    extra_sources: list[str] = list(args.source or [])
    flapid_host = args.host or "localhost"

    if interactive:
        _heading("Dev build roots")
        print(_dim("A FilmLight dev box has no /Applications/Baselight. Register dev builds/checkouts."))
        for path in _ask_loop("dev-build .app or dev-source checkout path"):
            kind = _ask("  kind (dev-build/dev-source)", "dev-build")
            dev_roots.append((path, kind, None))

        _heading("flapid host")
        flapid_host = _ask("default flapid host", flapid_host)

        _heading("Extra context sources")
        extra_sources += _ask_loop("extra FLAPI script/doc directory")

    cfg = cfgmod.build_config(
        d, flapid_host=flapid_host, dev_roots=dev_roots, extra_sources=extra_sources,
    )
    path = cfgmod.save_config(cfg)

    _heading("Wrote config")
    _ok("config.json", path)
    (_ok if cfg["baselight"]["active_venv"] else _miss)(
        "active venv (derived)", cfg["baselight"]["active_venv"] or "active venv")
    _ok("baselight_roots", len(cfg["baselight_roots"]))
    _ok("sources", len(cfg["sources"]))
    _ok("default_root", cfg["default_root"])
    if not cfg["baselight_roots"]:
        print(_yellow("  No build roots configured. Add one: "
                      "flapi-dev-mcp config add-baselight-root <path> --kind dev-build"))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from flapi_dev_mcp import report
    status = report.gather_status()
    print(report.render_text(status, color=sys.stdout.isatty()))
    return 0 if status.get("config_found") else 1


def _cmd_set_venv(args: argparse.Namespace) -> int:
    cfg = cfgmod.load_config()
    if cfg is None:
        print("No config found. Run `flapi-dev-mcp init` first.", file=sys.stderr)
        return 1
    cfg.setdefault("baselight", {})["venv_override"] = args.path or None
    cfgmod.save_config(cfg)
    if args.path:
        print(f"venv override set to: {args.path}")
    else:
        print("venv override cleared (will use the derived venv).")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    print("update: not implemented yet.", file=sys.stderr)
    return 1


def _cmd_config(args: argparse.Namespace) -> int:
    cfg = cfgmod.load_config()
    if cfg is None:
        print("No config found. Run `flapi-dev-mcp init` first.", file=sys.stderr)
        return 1
    print(__import__("json").dumps(cfg, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# parser / dispatch
# --------------------------------------------------------------------------- #

def _dev_root(value: str) -> tuple[str, str, str | None]:
    """Parse --dev-root 'PATH:KIND[:LABEL]'."""
    parts = value.split(":")
    path = parts[0]
    kind = parts[1] if len(parts) > 1 else "dev-build"
    label = parts[2] if len(parts) > 2 else None
    return (path, kind, label)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flapi-dev-mcp",
        description="Local MCP server for writing FLAPI scripts. "
        "With no subcommand, starts the MCP server over stdio.",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="discover Baselight, write config")
    p_init.add_argument("--yes", "-y", action="store_true", help="accept discovered defaults, no prompts")
    p_init.add_argument("--host", help="default flapid host (default: localhost)")
    p_init.add_argument("--dev-root", action="append", type=_dev_root, metavar="PATH:KIND[:LABEL]",
                        help="register a dev build root (repeatable)")
    p_init.add_argument("--source", action="append", metavar="PATH",
                        help="register an extra context source dir (repeatable)")

    sub.add_parser("status", help="human-readable environment/config report")

    p_setvenv = sub.add_parser("set-venv", help="override the auto-derived venv (blank to clear)")
    p_setvenv.add_argument("path", nargs="?", default=None, help="venv path, or omit to clear the override")

    sub.add_parser("update", help="git-pull context sources and re-index")
    sub.add_parser("config", help="print raw config.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        from flapi_dev_mcp.server import run
        run()
        return 0

    return {
        "init": _cmd_init,
        "status": _cmd_status,
        "set-venv": _cmd_set_venv,
        "update": _cmd_update,
        "config": _cmd_config,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
