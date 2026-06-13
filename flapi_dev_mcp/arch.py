"""uv + Mac architecture sanity gate.

Steve Chapman hit this: an old x86_64 uv from Homebrew at /usr/local/bin/uv ran
under Rosetta on an Apple Silicon Mac, so uv pulled x86_64 wheels into a venv
mismatched to the host. The MCP installed "fine" but everything downstream was
wrong. This module detects that situation (and the symmetric Intel case),
checks uv version, and prints actionable remediation. The gate fails closed:
on mismatch, `init` halts so the user can fix uv first rather than building
state on top of a broken toolchain.

Automatable: the official uv installer (no sudo, installs to ~/.local/bin).
Not automatable: removing /usr/local/bin/uv (sudo), restarting the shell,
reinstalling the MCP itself under the new uv (we are running on the wrong uv
right now). Those steps are printed for the user.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Min uv version. 0.5.0 is conservative; `uv tool install` from a git URL has
# been stable since 0.4 but we want a recent-enough self-update path too.
MIN_UV_VERSION = (0, 5, 0)


# --------------------------------------------------------------------------- #
# Tiny color helpers (mirror cli.py so this module stays standalone).
# --------------------------------------------------------------------------- #

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def _bold(t: str) -> str: return _c(t, "1")
def _green(t: str) -> str: return _c(t, "32")
def _yellow(t: str) -> str: return _c(t, "33")
def _red(t: str) -> str: return _c(t, "31")
def _dim(t: str) -> str: return _c(t, "2")


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #

def _sysctl(key: str) -> str | None:
    """Return sysctl value as string, or None on failure."""
    try:
        r = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def host_is_apple_silicon() -> bool:
    """True if the hardware is Apple Silicon (regardless of what arch we're
    running under). On Intel Macs hw.optional.arm64 is 0 or missing."""
    return _sysctl("hw.optional.arm64") == "1"


def running_under_rosetta() -> bool:
    """True if the current process is being translated by Rosetta. Means the
    Python (and the uv that installed us) is x86_64 on Apple Silicon HW."""
    return _sysctl("sysctl.proc_translated") == "1"


def host_arch() -> str:
    """Return the true hardware arch: 'arm64' or 'x86_64'."""
    return "arm64" if host_is_apple_silicon() else "x86_64"


def uv_path() -> Path | None:
    p = shutil.which("uv")
    return Path(p) if p else None


def uv_paths_all() -> list[Path]:
    """All `uv` instances on PATH, in lookup order. Used to detect the case
    where a wrong-arch uv still wins after the user installed a correct one."""
    try:
        r = subprocess.run(["which", "-a", "uv"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            return [Path(line.strip()) for line in r.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def _file_arch(path: Path) -> str | None:
    """Inspect a Mach-O binary's architecture via `file`. Returns one of
    'arm64', 'x86_64', 'universal', or None."""
    try:
        r = subprocess.run(["file", "-b", str(path)], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.lower()
    # `file` reports e.g. "Mach-O 64-bit executable arm64" or, for fat,
    # "Mach-O universal binary with 2 architectures: [x86_64...] [arm64...]".
    if "universal" in out:
        return "universal"
    if "arm64" in out:
        return "arm64"
    if "x86_64" in out:
        return "x86_64"
    return None


def uv_arch(path: Path) -> str | None:
    return _file_arch(path)


def uv_version(path: Path) -> tuple[int, int, int] | None:
    """Parse `uv --version` output. Returns a (major, minor, patch) tuple,
    or None if unreadable."""
    try:
        r = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    # e.g. "uv 0.5.4 (abcdef1234 2024-12-01)"
    m = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", r.stdout)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# --------------------------------------------------------------------------- #
# Aggregator
# --------------------------------------------------------------------------- #

@dataclass
class GateResult:
    ok: bool
    host_arch: str               # 'arm64' or 'x86_64'
    is_apple_silicon: bool
    under_rosetta: bool
    uv: Path | None
    uv_arch: str | None          # 'arm64' / 'x86_64' / 'universal' / None
    uv_version: tuple[int, int, int] | None
    uv_others: list[Path]        # additional uvs on PATH (for PATH-ordering warning)
    problems: list[str]          # human-readable problem statements


def check() -> GateResult:
    """Run all probes and aggregate. Returns ok=True if init should proceed."""
    is_mac = platform.system() == "Darwin"
    arch = host_arch() if is_mac else platform.machine()
    is_arm = host_is_apple_silicon() if is_mac else False
    rosetta = running_under_rosetta() if is_mac else False

    uv = uv_path()
    others = uv_paths_all()
    extras = [p for p in others if p != uv]  # other uv binaries that may shadow

    if uv is None:
        return GateResult(
            ok=False, host_arch=arch, is_apple_silicon=is_arm, under_rosetta=rosetta,
            uv=None, uv_arch=None, uv_version=None, uv_others=extras,
            problems=["uv is not installed (not found on PATH)."],
        )

    u_arch = uv_arch(uv)
    u_ver = uv_version(uv)
    problems: list[str] = []

    if is_mac and u_arch and u_arch != "universal" and u_arch != arch:
        problems.append(
            f"uv at {uv} is {u_arch}, but this Mac is {arch}. "
            f"That's why installs end up under Rosetta with wrong-arch wheels."
        )
    if u_ver is None:
        problems.append(f"could not read uv version from {uv} (--version failed).")
    elif u_ver < MIN_UV_VERSION:
        problems.append(
            f"uv version {'.'.join(map(str, u_ver))} is older than the minimum "
            f"({'.'.join(map(str, MIN_UV_VERSION))})."
        )

    return GateResult(
        ok=not problems,
        host_arch=arch, is_apple_silicon=is_arm, under_rosetta=rosetta,
        uv=uv, uv_arch=u_arch, uv_version=u_ver, uv_others=extras,
        problems=problems,
    )


# --------------------------------------------------------------------------- #
# Report + remediation
# --------------------------------------------------------------------------- #

INSTALLER_CMD = "curl -LsSf https://astral.sh/uv/install.sh | sh"


def _print_status(r: GateResult) -> None:
    print(_bold("uv / architecture check"))
    print(f"  host hardware: {r.host_arch}" + (_dim("  (Apple Silicon)") if r.is_apple_silicon else _dim("  (Intel)")))
    if r.under_rosetta:
        print(_yellow("  ⚠ this Python process is running under Rosetta — the upstream uv is x86_64"))
    if r.uv:
        v = ".".join(map(str, r.uv_version)) if r.uv_version else "?"
        a = r.uv_arch or "?"
        arch_ok = (not r.is_apple_silicon and a == "x86_64") or (r.is_apple_silicon and a in ("arm64", "universal"))
        ver_ok = r.uv_version is not None and r.uv_version >= MIN_UV_VERSION
        mark = _green("✓") if (arch_ok and ver_ok) else _red("✗")
        print(f"  {mark} uv: {r.uv} ({a}, v{v})")
        for extra in r.uv_others:
            print(_dim(f"      also on PATH: {extra}"))
    else:
        print(f"  {_red('✗')} uv: not found on PATH")


def _print_remediation_missing() -> None:
    print()
    print(_bold("How to fix"))
    print(f"  Install uv:  {INSTALLER_CMD}")
    print(_dim("  Then open a new terminal and re-run: flapi-dev-mcp init"))


def _print_remediation_mismatch(r: GateResult, ran_installer: bool) -> None:
    print()
    print(_bold("Finish the fix yourself"))
    step = 1
    if r.uv and "/usr/local/bin" in str(r.uv):
        print(f"  {step}. Remove the wrong uv:")
        print(_dim(f"       brew uninstall uv          # if installed via Homebrew (Intel)"))
        print(_dim(f"       sudo rm {r.uv}             # otherwise"))
        step += 1
    elif r.uv:
        print(f"  {step}. Remove the wrong uv:")
        print(_dim(f"       rm {r.uv}                  # may need sudo depending on location"))
        step += 1
    if not ran_installer:
        print(f"  {step}. Install a correct uv:")
        print(_dim(f"       {INSTALLER_CMD}"))
        step += 1
    print(f"  {step}. Open a new terminal so PATH picks up ~/.local/bin/uv.")
    step += 1
    print(f"     Verify with:  which uv     (should print ~/.local/bin/uv)")
    print(f"  {step}. Reinstall the MCP itself under the new uv:")
    print(_dim(f"       uv tool install --reinstall git+https://github.com/JasonMakes801/flapi-dev-mcp"))
    step += 1
    print(f"  {step}. Re-run:  flapi-dev-mcp init")


def _print_remediation_old(r: GateResult) -> None:
    print()
    print(_bold("How to fix"))
    print(f"  Update uv:  uv self update")
    print(_dim(f"  (Or reinstall via the official installer: {INSTALLER_CMD})"))
    print(_dim("  Then re-run: flapi-dev-mcp init"))


def _confirm(prompt: str, default: str = "N") -> bool:
    suffix = " [y/N]" if default.upper() == "N" else " [Y/n]"
    try:
        ans = input(f"{prompt}{suffix} ").strip().lower()
    except EOFError:
        ans = ""
    if not ans:
        ans = default.lower()
    return ans.startswith("y")


def _run_installer() -> bool:
    """Run the official uv installer. Returns True on success."""
    print(_dim(f"  running: {INSTALLER_CMD}"))
    try:
        # Pipe curl into sh in one shell invocation; same as the documented command.
        r = subprocess.run(INSTALLER_CMD, shell=True, check=False)
        return r.returncode == 0
    except OSError as e:
        print(_red(f"  installer failed: {e}"))
        return False


def run_gate(interactive: bool = True) -> bool:
    """Run the gate. Print status and, on failure, offer to run the installer
    and print the remaining manual steps. Returns True if init should proceed,
    False to halt."""
    r = check()
    _print_status(r)

    if r.ok:
        return True

    print()
    for p in r.problems:
        print(f"  {_red('✗')} {p}")

    # Decide which remediation flow applies.
    missing = r.uv is None
    too_old = r.uv is not None and r.uv_version is not None and r.uv_version < MIN_UV_VERSION
    mismatch = (
        r.uv is not None
        and r.uv_arch
        and r.uv_arch != "universal"
        and r.uv_arch != r.host_arch
    )

    if missing:
        _print_remediation_missing()
        if interactive and _confirm("Install uv now via the official installer?"):
            ok = _run_installer()
            if ok:
                print(_green("\n  ✓ uv installed. Open a NEW terminal, then re-run: flapi-dev-mcp init"))
            else:
                print(_red("\n  installer failed — install manually and re-run init."))
        return False

    if mismatch:
        ran = False
        if interactive and _confirm(
            f"Install a correct {r.host_arch} uv to ~/.local/bin now? "
            f"(I won't touch your existing {r.uv})"
        ):
            ran = _run_installer()
            if ran:
                print(_green("  ✓ correct-arch uv installed to ~/.local/bin"))
            else:
                print(_red("  installer failed — install manually before continuing."))
        _print_remediation_mismatch(r, ran_installer=ran)
        return False

    if too_old:
        _print_remediation_old(r)
        return False

    # Unknown problem: just print and bail.
    return False
