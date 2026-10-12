#!/usr/bin/env python3
"""Keep docs/CAPABILITIES.md in sync with examples/capabilities.py.

* Every ``<!-- snippet: NAME -->`` marker in the document is followed by a
  ```python block; the block is replaced with the exact source of function
  NAME in examples/capabilities.py (``imports`` is the block between
  ``# snippet: imports`` and ``# end snippet``).
* The table between ``<!-- summary:start -->`` and ``<!-- summary:end -->`` is
  recomputed from the item tables of the numbered sections: a row counts as
  wrapped or raw by the first word of its "Python" column.
* Every function in examples/capabilities.py must appear in the document, except
  ``main`` and names starting with ``_`` (the command-line runner).

Usage: python scripts/update_capabilities_doc.py [--check]
With --check nothing is written; the exit status is 1 if the document is stale.
Standard library only.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "CAPABILITIES.md"
EXAMPLES = REPO / "examples" / "capabilities.py"

# The body ends at the first line that is exactly ``` (an empty block has no body at all).
SNIPPET_RE = re.compile(r"(<!-- snippet: (?P<name>[A-Za-z0-9_]+) -->\n```python\n)(?P<body>.*?)(^```$)", re.S | re.M)
SECTION_RE = re.compile(r"^## (?P<num>\d+)\. (?P<title>.+)$", re.M)
SUMMARY_RE = re.compile(r"(<!-- summary:start -->\n)(?P<body>.*?)(<!-- summary:end -->)", re.S)


def example_sources(path: Path = EXAMPLES) -> Dict[str, str]:
    """Function name -> exact source text, plus the ``imports`` block.

    ``main`` and private helpers (``_name``) belong to the command-line runner and are skipped.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sources: Dict[str, str] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name != "main" and not node.name.startswith("_"):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            sources[node.name] = "\n".join(lines[start - 1 : node.end_lineno])
    begin = lines.index("# snippet: imports") + 1
    end = lines.index("# end snippet")
    sources["imports"] = "\n".join(lines[begin:end])
    return sources


def section_counts(doc: str) -> List[Tuple[str, int, int]]:
    """``(section title, wrapped, raw)`` for every numbered section, in order."""
    matches = list(SECTION_RE.finditer(doc))
    out = []
    for i, m in enumerate(matches):
        body = doc[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(doc)]
        wrapped = raw = 0
        header = None
        for line in body.splitlines():
            if not line.startswith("|"):
                header = None  # any non-table line ends the current table
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if header is None:
                header = cells
                continue
            if set(line.replace("|", "").strip()) <= {"-", ":", " "} or "Python" not in header:
                continue
            status = cells[header.index("Python")].split(":")[0].split()[0].lower() if cells else ""
            wrapped += status == "wrapped"
            raw += status == "raw"
        out.append(("%s. %s" % (m.group("num"), m.group("title")), wrapped, raw))
    return out


def render_summary(counts: List[Tuple[str, int, int]]) -> str:
    rows = ["| Section | Items | Wrapped | Raw |", "|---|---:|---:|---:|"]
    for title, wrapped, raw in counts:
        anchor = re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")
        rows.append("| [%s](#%s) | %d | %d | %d |" % (title, anchor, wrapped + raw, wrapped, raw))
    tw = sum(c[1] for c in counts)
    tr = sum(c[2] for c in counts)
    rows.append("| **Total** | **%d** | **%d** | **%d** |" % (tw + tr, tw, tr))
    return "\n".join(rows) + "\n"


def updated_document(doc: str, sources: Dict[str, str]) -> Tuple[str, List[str]]:
    """Return the regenerated document and a list of problems (unknown or missing snippets)."""
    problems: List[str] = []
    used = set()

    def replace(m: "re.Match[str]") -> str:
        name = m.group("name")
        if name not in sources:
            problems.append("snippet %r has no function in examples/capabilities.py" % name)
            return m.group(0)
        used.add(name)
        return m.group(1) + sources[name] + "\n" + m.group(4)

    new = SNIPPET_RE.sub(replace, doc)
    for name in sources:
        if name not in used:
            problems.append("function %r is not shown in docs/CAPABILITIES.md" % name)
    summary = render_summary(section_counts(new))
    new, n = SUMMARY_RE.subn(lambda m: m.group(1) + summary + m.group(3), new)
    if n != 1:
        problems.append("summary markers missing or duplicated")
    return new, problems


def main(argv: List[str]) -> int:
    check = "--check" in argv
    doc = DOC.read_text(encoding="utf-8")
    new, problems = updated_document(doc, example_sources())
    for p in problems:
        print("error: %s" % p, file=sys.stderr)
    if problems:
        return 1
    if new == doc:
        print("docs/CAPABILITIES.md is up to date")
        return 0
    if check:
        print("docs/CAPABILITIES.md is stale; run: python scripts/update_capabilities_doc.py", file=sys.stderr)
        return 1
    DOC.write_text(new, encoding="utf-8")
    print("docs/CAPABILITIES.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
