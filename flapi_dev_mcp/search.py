"""Keyword search across context sources (the enhancements repo, bundled
examples, and any extra dirs the user registered).

No vectorization: a small corpus, so plain keyword scoring over filenames and
file contents is fast, debuggable, and good enough. Backs search_examples().
"""

from __future__ import annotations

import os
from pathlib import Path

from flapi_dev_mcp import config as cfgmod

# Text files worth searching; everything else (images, archives, media) skipped.
TEXT_EXT = {
    ".py", ".md", ".txt", ".rst", ".glsl", ".xml", ".json", ".toml",
    ".sh", ".cfg", ".ini", ".yaml", ".yml", ".js", ".java",
}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".idea"}
MAX_BYTES = 1_000_000  # skip files larger than ~1MB


_BUNDLED = "/share/flapi/examples/python"


def _enabled_sources() -> list[dict]:
    """Configured sources, with the build-bundled examples swapped for the
    target build's own (so the agent never adapts another build's examples)."""
    cfg = cfgmod.load_config() or {}
    layout, _ = cfgmod.target_layout()
    sources = list(cfg.get("sources", []))
    if layout is not None and layout.examples is not None:
        sources = [s for s in sources if not str(s.get("path", "")).endswith(_BUNDLED)]
        sources.append({"type": "local", "path": str(layout.examples), "enabled": True})
    out = []
    for s in sources:
        if s.get("enabled", True):
            p = Path(os.path.expanduser(s.get("path", "")))
            if p.is_dir():
                out.append({"path": p, "type": s.get("type", "local")})
    return out


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if Path(name).suffix.lower() in TEXT_EXT or name.lower().startswith("readme"):
                yield Path(dirpath) / name


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(errors="replace")
    except OSError:
        return None


def _readme_summary(folder: Path) -> tuple[str | None, str | None]:
    """Return (title, one-line description) from a folder's README, if any."""
    for name in ("README.md", "readme.md", "Readme.md"):
        p = folder / name
        if not p.is_file():
            continue
        title = desc = None
        for line in (_read(p) or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if title is None:
                    title = line.lstrip("#").strip()
                continue
            if title is None:
                title = line  # README with no heading
            elif desc is None:
                desc = line
                break
        return title, desc
    return None, None


def build_catalog(sources: list[dict] | None = None) -> list[dict]:
    """List every enhancement (a folder with a README) + its one-line summary.

    A 'table of contents' for browsing when search comes up sparse. Falls back
    to listing .py files for sources that have no READMEs (e.g. bundle examples).
    """
    sources = sources if sources is not None else _enabled_sources()
    entries: list[dict] = []
    for src in sources:
        root = src["path"]
        readme_folders: set[Path] = set()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if any(f.lower() == "readme.md" for f in filenames):
                readme_folders.add(Path(dirpath))
        if readme_folders:
            for folder in readme_folders:
                rel = folder.relative_to(root)
                if str(rel) == ".":
                    continue  # skip the source's top-level README
                title, desc = _readme_summary(folder)
                entries.append({
                    "name": str(rel),
                    "title": title or str(rel),
                    "desc": desc or "",
                    "source": str(root),
                })
        else:
            for path in _iter_files(root):
                if path.suffix == ".py":
                    entries.append({
                        "name": str(path.relative_to(root)),
                        "title": path.stem, "desc": "", "source": str(root),
                    })
    entries.sort(key=lambda e: e["name"].lower())
    return entries


def search_examples(query: str, limit: int = 10, snippets_per_file: int = 3) -> dict:
    """Score files across sources by query-term hits in path + content."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return {"query": query, "results": [], "note": "empty query"}

    sources = _enabled_sources()
    if not sources:
        return {"query": query, "results": [],
                "note": "no enabled context sources found; run `flapi-dev-mcp init`"}

    results = []
    for src in sources:
        root = src["path"]
        for path in _iter_files(root):
            rel = path.relative_to(root)
            rel_l = str(rel).lower()
            text = _read(path)
            if text is None:
                continue
            text_l = text.lower()

            name_hits = sum(rel_l.count(t) for t in terms)
            content_hits = sum(text_l.count(t) for t in terms)
            if name_hits == 0 and content_hits == 0:
                continue

            # filename matches weigh much more than incidental content hits
            score = name_hits * 10 + min(content_hits, 20)

            snippets = []
            for i, line in enumerate(text.splitlines(), 1):
                ll = line.lower()
                if any(t in ll for t in terms):
                    snippets.append({"line": i, "text": line.strip()[:200]})
                    if len(snippets) >= snippets_per_file:
                        break

            results.append({
                "source": str(root),
                "path": str(path),
                "rel": str(rel),
                "score": score,
                "matched_in": ("filename" if name_hits else "content"),
                "snippets": snippets,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    out = {
        "query": query,
        "sources_searched": [str(s["path"]) for s in sources],
        "total_matches": len(results),
        "results": results[:limit],
    }
    # Sparse results → attach the full catalog so the agent can browse what
    # exists rather than guess search terms blindly.
    if len(results) < 3:
        out["catalog"] = build_catalog(sources)
        out["note"] = ("Few/no direct matches — `catalog` lists every available "
                       "example with a one-line description; adapt the closest one.")
    return out
