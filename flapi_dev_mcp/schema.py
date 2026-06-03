"""Read the FLAPI JSON schema (share/flapi/schema/schema.json) — the authoritative,
structured API definition shipped in every build.

Far better than scraping python.html: it gives every class, its methods with typed
args + result + description, its signals, plus Constants (enums) and ValueTypes
(settings structs). This backs get_api_surface() and get_class_docs().
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc


def active_schema_path() -> Path | None:
    """Resolve the schema.json for the configured default build root (live)."""
    cfg = cfgmod.load_config()
    roots = (cfg or {}).get("baselight_roots") or []
    default = (cfg or {}).get("default_root")
    ordered = sorted(roots, key=lambda r: r.get("path") != default)  # default first
    for r in ordered:
        layout = disc.resolve_layout(Path(r["path"]), r.get("kind", "release"), r.get("label"))
        if layout.schema:
            return layout.schema
    # No config? fall back to a live release root.
    for br in disc.discover().release_roots:
        if br.schema:
            return br.schema
    return None


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict:
    return json.loads(Path(path_str).read_text())


def load_schema() -> dict | None:
    path = active_schema_path()
    if path is None:
        return None
    try:
        return _load(str(path))
    except (OSError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def _normalize_args(args: object) -> list[dict]:
    """Args appear as either a list of {Name,Type,...} or a dict {name: {Type:..}}."""
    out: list[dict] = []
    if isinstance(args, list):
        for a in args:
            out.append({
                "name": a.get("Name"),
                "type": a.get("Type"),
                "desc": a.get("Desc", ""),
                "nullable": bool(a.get("Nullable", 0)),
            })
    elif isinstance(args, dict):
        for name, a in args.items():
            a = a if isinstance(a, dict) else {}
            out.append({
                "name": name,
                "type": a.get("Type"),
                "desc": a.get("Desc", ""),
                "nullable": bool(a.get("Nullable", 0)),
            })
    return out


def _find_class(schema: dict, name: str) -> dict | None:
    for c in schema.get("Classes", []):
        if c.get("Name") == name:
            return c
    # case-insensitive fallback
    lname = name.lower()
    for c in schema.get("Classes", []):
        if c.get("Name", "").lower() == lname:
            return c
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def api_surface() -> dict:
    """Summary of all classes and their method names (+ constants/value types counts)."""
    schema = load_schema()
    if schema is None:
        return {"available": False, "reason": "schema.json not found; run init / check build root"}
    classes = []
    for c in schema.get("Classes", []):
        classes.append({
            "name": c.get("Name"),
            "methods": [m.get("Name") for m in c.get("Methods", [])],
            "signals": c.get("Signals", []),
        })
    return {
        "available": True,
        "schema_path": str(active_schema_path()),
        "class_count": len(classes),
        "classes": classes,
        "value_types": [v.get("Name") for v in schema.get("ValueTypes", [])],
        "constants": [c.get("Name") for c in schema.get("Constants", [])],
    }


def class_docs(class_name: str) -> dict:
    """Full docs for one class: every method with typed args, result, description."""
    schema = load_schema()
    if schema is None:
        return {"found": False, "reason": "schema.json not found"}
    c = _find_class(schema, class_name)
    if c is None:
        return {"found": False, "class": class_name,
                "reason": "no such class", "did_you_mean": _suggest(schema, class_name)}
    methods = []
    for m in c.get("Methods", []):
        result = m.get("Result", {}) or {}
        methods.append({
            "name": m.get("Name"),
            "static": bool(m.get("Static", 0)),
            "desc": m.get("Desc", ""),
            "args": _normalize_args(m.get("Args", [])),
            "returns": {"type": result.get("Type"), "desc": result.get("Desc", "")},
        })
    return {
        "found": True,
        "class": c.get("Name"),
        "signals": c.get("Signals", []),
        "methods": methods,
        "markdown": _format_class_md(c.get("Name"), c.get("Signals", []), methods),
    }


def _suggest(schema: dict, name: str, limit: int = 5) -> list[str]:
    lname = name.lower()
    hits = [c["Name"] for c in schema.get("Classes", []) if lname in c.get("Name", "").lower()]
    return hits[:limit]


def _sig(method: dict) -> str:
    parts = []
    for a in method["args"]:
        t = a["type"] or "any"
        s = f"{a['name']}: {t}"
        if a["nullable"]:
            s += "?"
        parts.append(s)
    ret = method["returns"]["type"] or "none"
    prefix = "static " if method["static"] else ""
    return f"{prefix}{method['name']}({', '.join(parts)}) -> {ret}"


def _format_class_md(name: str, signals: list[str], methods: list[dict]) -> str:
    lines = [f"# {name}", ""]
    if signals:
        lines += [f"**Signals:** {', '.join(signals)}", ""]
    lines.append(f"**{len(methods)} methods:**")
    lines.append("")
    for m in methods:
        lines.append(f"### `{_sig(m)}`")
        if m["desc"]:
            lines.append(m["desc"])
        for a in m["args"]:
            if a["desc"]:
                lines.append(f"- `{a['name']}` ({a['type']}): {a['desc']}")
        if m["returns"]["desc"]:
            lines.append(f"- → {m['returns']['desc']}")
        lines.append("")
    return "\n".join(lines)
