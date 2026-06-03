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


def _enabled_sources() -> list[dict]:
    cfg = cfgmod.load_config() or {}
    out = []
    for s in cfg.get("sources", []):
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
    return {
        "query": query,
        "sources_searched": [str(s["path"]) for s in sources],
        "total_matches": len(results),
        "results": results[:limit],
    }
