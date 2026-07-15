"""Load policy markdown into clause-level chunks for retrieval.

A chunk is one **clause** — a single bullet, with any wrapped continuation lines
joined back onto it — tagged with its section heading. Retrieval then returns the
specific clause that governs an action, which becomes the citation on the
approval request.

Two things this deliberately does *not* do:

* It does not split a wrapped bullet across lines. A clause like "Refunds are only
  permitted within 30 days ... outside this window require manager approval" spans
  two source lines; chunking per-line would strand the second half as a fragment
  with no subject.
* It does not index prose outside a bullet (e.g. a document preamble). That text is
  context for human readers, not a citable clause — and indexing it lets meta-text
  outrank real policy, since it inherits the section heading's keywords.
"""

from __future__ import annotations

from pathlib import Path


def chunk_markdown(text: str, source: str) -> list[dict]:
    section = ""
    chunks: list[dict] = []
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append({"text": " ".join(current).strip(), "section": section, "source": source})
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip()
            continue
        if line.startswith(("- ", "* ")):
            flush()
            current = [line[2:].strip()]
            continue
        if current is not None:
            current.append(line)  # a wrapped continuation of the current bullet
        # else: prose outside any bullet -> not a clause, skipped

    flush()
    return chunks


def load_policy_dir(path: str | Path) -> list[dict]:
    path = Path(path)
    chunks: list[dict] = []
    for f in sorted(path.glob("*.md")):
        chunks.extend(chunk_markdown(f.read_text(encoding="utf-8"), source=f.name))
    return chunks
