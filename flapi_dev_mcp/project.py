"""`flapi-dev-mcp init-project`: put the agent instructions in a project's AGENTS.md.

For agents that don't read MCP server instructions (Codex, Cursor, others):
AGENTS.md is the cross-agent standard they read every session. The block sits
between markers, so re-running updates it in place and never touches the
user's own text. If the project has a CLAUDE.md, it gets an `@AGENTS.md` import,
because Claude Code skips AGENTS.md when a CLAUDE.md exists.
"""

from __future__ import annotations

import re
from pathlib import Path

from flapi_dev_mcp.instructions import INSTRUCTIONS

START = "<!-- flapi-mcp:start -->"
END = "<!-- flapi-mcp:end -->"
IMPORT = "@AGENTS.md"


def block() -> str:
    return f"{START}\n## FLAPI (flapi-dev MCP)\n\n{INSTRUCTIONS.rstrip()}\n{END}\n"


def _has_import(text: str) -> bool:
    """True if CLAUDE.md already imports AGENTS.md (outside code spans/blocks)."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    return re.search(r"(^|\s)@(\./)?AGENTS\.md\b", text) is not None


def init_project(project_dir: str | Path = ".") -> list[str]:
    """Write or update the block; return what was done, one line per file."""
    root = Path(project_dir).expanduser().resolve()
    done = []

    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text(block())
        done.append(f"created {agents}")
    else:
        text = agents.read_text()
        if START in text and END in text:
            new = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", block(),
                         text, count=1, flags=re.DOTALL)
            done.append(f"{'updated' if new != text else 'already current'}: {agents}")
        else:
            new = text.rstrip("\n") + "\n\n" + block()
            done.append(f"added the FLAPI block to {agents}")
        if new != text:
            agents.write_text(new)

    claude = root / "CLAUDE.md"
    if claude.exists():
        text = claude.read_text()
        if _has_import(text):
            done.append(f"{claude} already imports AGENTS.md")
        else:
            claude.write_text(text.rstrip("\n") + f"\n\n{IMPORT}\n")
            done.append(f"added {IMPORT} to {claude}")
    return done
