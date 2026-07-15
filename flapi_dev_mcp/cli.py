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
import re
import sys
from pathlib import Path

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

def _miss(label: str, value: object = None) -> None:
    # value is accepted (and ignored) so the `(_ok if x else _miss)(label, value)`
    # idiom works whether x is truthy or not.
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


def _fl_vers_cmd(supported_roots: list) -> str:
    """Build a copy-pasteable `sudo <path>/fl-vers` command from a BL7 root.

    On Linux `/usr/fl/.current/bin/fl-vers` is on PATH by default; on macOS it
    isn't. Pulling the path off the highest installed BL7 build works on both
    OSes, since BL7 always ships fl-vers under `<base>/bin/`.
    """
    if not supported_roots:
        return "sudo fl-vers"
    chosen = max(supported_roots, key=lambda b: b.version or "")
    base = disc.LAYOUT.resolve_base(chosen.path)
    return f"sudo {base}/bin/fl-vers" if base else "sudo fl-vers"


def _resolve_scripts_dir(dr: "disc.DataRoot", *, kind: str) -> None:
    """Print the chosen scripts dir, or inform the user how to create one.

    An absent scripts dir isn't a problem — it just means nothing of that kind
    is deployed yet. So when no candidate exists, we render the state in dim
    text (same idiom as "FLAPI Python: default") with a sudo `mkdir` hint that
    only matters if the user actually plans to deploy that kind of script.
    Parent dirs `/vol/.support` and `/usr/fl` are typically root-owned, so we
    don't try to create them; the hint tells the user how, when needed.
    """
    label = "UI scripts dir" if kind == "ui" else "server scripts dir"
    need_hint = ("Only needed if you plan to deploy UI scripts (menu items, dialogs)."
                 if kind == "ui" else
                 "Only needed if you plan to deploy server scripts (QM background tasks).")
    chosen: Path | None = getattr(dr, "ui_scripts_dir" if kind == "ui" else "server_scripts_dir")
    candidates: list[Path] = getattr(dr, "ui_scripts_candidates" if kind == "ui" else "server_scripts_candidates")

    if chosen:
        _ok(label, chosen)
        return

    # Pick the candidate whose parent exists, for a usable sudo-mkdir hint.
    target = next((c for c in candidates if c.parent.is_dir()), candidates[0] if candidates else None)
    print(f"  {_dim('·')} {label}: {_dim('not present (no scripts deployed yet)')}")
    print(_dim(f"      {need_hint}"))
    if target is not None:
        print(_dim(f"      When needed:  sudo mkdir {target}"))


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #

def _cmd_init(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty() and not args.yes

    print(_bold("FLAPI Developer MCP — setup"))
    _platform_label = "macOS" if sys.platform == "darwin" else "Linux" if sys.platform.startswith("linux") else sys.platform
    print(_dim(f"{_platform_label}, Python only (v1). Auto-discovering your environment…"))

    # Gate: uv must exist, match host arch, and be new enough. Fail closed —
    # otherwise we end up building venvs on a Rosetta-installed x86 uv on
    # Apple Silicon (Steve C's case), which silently pulls wrong-arch wheels.
    if not args.skip_arch_check:
        from flapi_dev_mcp import arch
        if not arch.run_gate(interactive=interactive):
            print()
            print(_yellow("Halting init until the uv setup is fixed. "
                          "Re-run `flapi-dev-mcp init` when done, or "
                          "`flapi-dev-mcp doctor` to re-check."))
            return 1
        print()

    d = disc.discover()
    dr = d.data_root

    _heading("Data root")
    if dr.exists:
        _ok("path", dr.root)
        # `flapi_python_path` is an override — its absence is the default state,
        # not a problem. Distinguish "override set" from "using install default".
        if dr.flapi_python_path:
            _ok("FLAPI Python (override)", dr.flapi_python_path)
        else:
            print(f"  {_dim('·')} FLAPI Python: {_dim('default (no override set in bluserprefs/blsiteprefs)')}")
        _ok("venvs", ", ".join(v.name for v in dr.venvs) or "(none)")
        _resolve_scripts_dir(dr, kind="ui")
        _resolve_scripts_dir(dr, kind="server")
    else:
        _miss(f"FilmLight data root ({disc.LAYOUT.data_root})")

    # Group discovery output by product (baselight, daylight). Same layout on
    # each side — the product label is what tells the user which is which.
    _heading(f"Release build roots ({len(d.release_roots)} found)")
    for br in d.release_roots:
        _ok(f"{br.product} {br.version}", br.app or br.path)
        print(_dim(f"      wheel: {br.wheel.name if br.wheel else '—'}  flapid: {'yes' if br.flapid else 'no'}  "
                   f"docs: {'yes' if br.docs_html else 'no'}  schema: {'yes' if br.schema else 'no'}  "
                   f"examples: {'yes' if br.examples else 'no'}"))
    if not d.release_roots:
        apps_dirs = ", ".join(str(p.apps_dir) for p in disc.LAYOUT.products)
        _miss(f"no release builds under {apps_dirs}")

    # BL7+ is required (the wheel-based FLAPI model arrived in 7.0.0.24232).
    # If only older builds are installed, refuse early with a clear message
    # rather than letting init write a config that downstream tools can't use.
    supported_roots = [br for br in d.release_roots if disc.is_supported_version(br.version)]
    if d.release_roots and not supported_roots:
        versions = ", ".join(f"{br.product} {br.version}" for br in d.release_roots if br.version)
        print()
        print(_yellow("flapi-dev-mcp requires Baselight/Daylight 7+ (none found)."))
        print(_dim(f"      Installed: {versions}"))
        print(_dim("      The wheel-based FLAPI distribution was introduced in 7.0.0.24232."))
        print(_dim("      Older Baselight/Daylight use a different FLAPI delivery model."))
        return 1

    # If a live flapid is running but it's BL5/BL6 (either Baselight or Daylight),
    # scripts the agent writes will hit a wheel-vs-server version mismatch the
    # moment they connect. Block init and tell the user to switch with `fl-vers`
    # first — once the live product is version 7+, init will sail through.
    running_pre = disc.detect_running_build()
    if running_pre and running_pre.version and not disc.is_supported_version(running_pre.version):
        avail = ", ".join(f"{br.product} {br.version}" for br in supported_roots) or "(none installed)"
        print()
        print(_yellow(f"The live {running_pre.product.capitalize()} (flapid on :1984) is "
                      f"{running_pre.version}, which isn't supported."))
        print(_dim("      Switch to a version 7+ build first, then re-run `flapi-dev-mcp init`."))
        print(_dim(f"      Use FilmLight's version switcher:  {_fl_vers_cmd(supported_roots)}"))
        print(_dim(f"      7+ builds available on this host:  {avail}"))
        return 1

    # Per-product current-symlink promotion notes. For each product whose
    # `<product>` symlink points at a v5/v6 build but where a v7+ build is
    # also installed, tell the user the config will default to the newer
    # build instead. Older builds don't appear in d.release_roots (no wheel),
    # so we resolve the symlink ourselves and parse the version off the
    # target dir name.
    for prod in disc.LAYOUT.products:
        current = prod.current_symlink
        try:
            target_name = current.resolve().name if current.exists() else ""
        except OSError:
            target_name = ""
        m = re.search(rf"{prod.name}-(.+)$", target_name)
        target_version = m.group(1) if m else None
        if target_version and not disc.is_supported_version(target_version):
            product_supported = [b for b in supported_roots if b.product == prod.name]
            if not product_supported:
                continue
            chosen = max(product_supported, key=lambda b: b.version or "")
            print()
            print(_yellow(f"Note: the {prod.name} symlink ({current}) points at {target_version} "
                          f"(v5/v6, no FLAPI wheel);"))
            print(_dim(f"      defaulting to {prod.name} {chosen.version} instead. To make this"))
            print(_dim(f"      permanent system-wide, switch with `{_fl_vers_cmd(supported_roots)}`"))
            print(_dim("      and re-run init."))

    # Clone (or update) the canonical enhancements repo as the primary source.
    _heading("Context repo")
    if args.no_repo:
        print(_dim("  skipped (--no-repo)"))
    else:
        from flapi_dev_mcp import repo
        res = repo.clone_or_update()
        if res["ok"]:
            _ok(f"{res['action']} {res['commit'] or ''}", res["path"])
        else:
            _miss("clone enhancements repo (offline?); will retry on `update`")
            print(_dim(f"      {res['message'].splitlines()[0] if res['message'] else ''}"))

    # Prompts: dev roots, flapid host, extra sources.
    dev_roots: list[tuple[str, str, str | None]] = list(args.dev_root or [])
    extra_sources: list[str] = list(args.source or [])
    flapid_host = args.host or "localhost"

    if interactive:
        # Dev build/checkout roots are only relevant to FilmLight engineers (a dev
        # box has no /Applications/Baselight). Hidden unless --dev, so it doesn't
        # confuse end users.
        if args.dev:
            _heading("Dev build roots")
            print(_dim("For FilmLight devs: register a dev-build .app or dev-source checkout."))
            for path in _ask_loop("dev-build .app or dev-source checkout path"):
                kind = _ask("  kind (dev-build/dev-source)", "dev-build")
                dev_roots.append((path, kind, None))

        _heading("flapid host")
        flapid_host = _ask("default flapid host", flapid_host)

        _heading("Extra context sources")
        print(_dim("Point at any extra FLAPI-rich folders (your own scripts, integrations…)."))
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

    # Does the build currently serving flapid match the target we just chose?
    running = disc.detect_running_build()
    if running and running.version:
        target_layout = disc.resolve_layout(Path(cfg["default_root"]), "release") if cfg["default_root"] else None
        target_v = target_layout.version if target_layout else None
        _heading("Running flapid")
        if target_v and running.version != target_v:
            print(f"  {_yellow('•')} mismatch: targeting {target_v}, but flapid is running build {running.version}")
            if target_layout is not None:
                base = disc.LAYOUT.resolve_base(target_layout.path)
                if base is not None:
                    print(_dim(f"      match the server to your target:  "
                               f"sudo {base}/bin/fl-service restart flapi"))
            print(_dim(f"      or switch target to the running build:  flapi-dev-mcp target-running"))
        else:
            _ok("running build matches target", running.version)
    if not cfg["baselight_roots"]:
        print(_yellow("  No build roots configured. Add one: "
                      "flapi-dev-mcp config add-baselight-root <path> --kind dev-build"))

    # If no FLAPI venv exists yet, offer to build it (not sudo-gated).
    if not cfg["baselight"].get("active_venv"):
        from flapi_dev_mcp import app_scripts
        fss = next((br.setup_scripts for br in d.release_roots if br.setup_scripts), None)
        _heading("Action needed — no FLAPI venv yet")
        print(f"  {_yellow('•')} The FLAPI virtual environment hasn't been created.")
        if interactive and fss:
            if _ask("Create it now? (runs fl-setup-flapi-scripts --create)", "Y").lower().startswith("y"):
                print(_dim("  creating venv (installs the filmlightapi wheel; may take a minute)…"))
                res = app_scripts.create_managed_venv()
                if res.get("ok"):
                    _ok("venv created", res.get("venv"))
                    print(_dim("  re-run `flapi-dev-mcp init` to refresh the config."))
                else:
                    print(_yellow(f"  create failed: {res.get('error') or 'see log'}"))
                return 0
        create_cmd = f'"{fss}" --create' if fss else "fl-setup-flapi-scripts --create"
        print(_dim(f"      Create it (headless, no GUI):  {create_cmd}"))
        print(_dim("      …or just launch Baselight once. Then re-run: flapi-dev-mcp init"))
        print(_dim("      (Optional: to pin a Python version, set it in Baselight"))
        print(_dim("       Preferences > Advanced > API Server before creating.)"))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Re-run the uv + Mac arch sanity gate on demand (no init side effects)."""
    from flapi_dev_mcp import arch
    interactive = sys.stdin.isatty() and not args.yes
    ok = arch.run_gate(interactive=interactive)
    return 0 if ok else 1


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


def _cmd_target_running(args: argparse.Namespace) -> int:
    cfg = cfgmod.load_config()
    if cfg is None:
        print("No config. Run `flapi-dev-mcp init` first.", file=sys.stderr)
        return 1
    br = disc.detect_running_build()
    # On macOS we want the .app bundle (br.app); on Linux there's no .app and
    # br.path IS the build root. Use br.app if present, else br.path.
    target = br.app if (br and br.app) else (br.path if br else None)
    if br is None or target is None:
        print("Could not detect a running Baselight/Daylight on :1984 (is it running?).", file=sys.stderr)
        return 1
    if not disc.is_supported_version(br.version):
        supported = [b for b in disc.discover_release_roots() if disc.is_supported_version(b.version)]
        print(f"Running {br.product.capitalize()} is {br.version}, which isn't supported "
              "(flapi-dev-mcp requires version 7+).", file=sys.stderr)
        print(f"Switch the live version with `{_fl_vers_cmd(supported)}` first, "
              "then re-run this command.", file=sys.stderr)
        return 1
    path = str(target)
    roots = cfg.setdefault("baselight_roots", [])
    if not any(r.get("path") == path for r in roots):
        roots.append({"kind": br.kind, "product": br.product, "path": path,
                      "version": br.version, "label": "running", "enabled": True})
    cfg["default_root"] = path
    dr = disc.discover_data_root()
    av = disc.resolve_venv(dr.python_dir, dr.python_minor, disc.baselight_major(br.version))
    cfg.setdefault("baselight", {})["active_venv"] = str(av) if av else None
    cfgmod.save_config(cfg)
    print(f"Now targeting the running {br.product} build {br.version}")
    print(f"  app:    {path}")
    print(f"  wheel:  {br.wheel}")
    print(f"  venv:   {av}")
    if not br.wheel:
        print(_yellow("  warning: no filmlightapi wheel found in this build"))
    print(_dim("  Re-run setup_standalone_env(reinstall_wheel=true) to install this build's wheel."))
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    from flapi_dev_mcp import repo
    res = repo.clone_or_update()
    if res["ok"]:
        print(f"{res['action']} ok @ {res['commit']}: {res['path']}")
        return 0
    print(f"update failed: {res['message']}", file=sys.stderr)
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
    p_init.add_argument("--dev", action="store_true",
                        help="FilmLight devs: also prompt for dev build/checkout roots")
    p_init.add_argument("--no-repo", action="store_true",
                        help="skip cloning the enhancements repo (e.g. offline)")
    p_init.add_argument("--skip-arch-check", action="store_true",
                        help="skip the uv / Mac arch sanity gate (not recommended)")

    p_doctor = sub.add_parser("doctor", help="check uv presence, architecture, and version")
    p_doctor.add_argument("--yes", "-y", action="store_true",
                          help="non-interactive (no installer prompts)")

    sub.add_parser("status", help="human-readable environment/config report")

    p_setvenv = sub.add_parser("set-venv", help="override the auto-derived venv (blank to clear)")
    p_setvenv.add_argument("path", nargs="?", default=None, help="venv path, or omit to clear the override")

    sub.add_parser("target-running", help="target the Baselight build currently running on :1984")

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
        "doctor": _cmd_doctor,
        "status": _cmd_status,
        "set-venv": _cmd_set_venv,
        "target-running": _cmd_target_running,
        "update": _cmd_update,
        "config": _cmd_config,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
