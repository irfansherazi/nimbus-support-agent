"""Heading-aware markdown chunker for the policy corpus.

Policy sections are self-contained rules, so one H2/H3 section is one retrieval unit. A section is split further
only when it exceeds `max_tokens`, at paragraph boundaries, with a small overlap inside that section only. Each
chunk's embedding text is prefixed with its breadcrumb ("Refund Policy > Pro plan") because a bare rule like
"up to $200 within 30 days" means nothing without its heading.
"""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast

import tiktoken
import yaml

from app.models import ChunkTier, Tier

DocType = Literal["policy", "troubleshooting"]

_HEADING = re.compile(r"^(#{2,3})\s+(.*?)\s*(?:\{tier=(all|free|pro|enterprise)\})?\s*$")
_REFUND_LIMIT = re.compile(r"Refunds of up to \$([\d,]+) are available within (\d+) days")
_NOT_ELIGIBLE = re.compile(r"not eligible for refunds", re.IGNORECASE)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    section_path: str
    tier: ChunkTier
    doc_type: DocType
    content: str
    embed_text: str
    content_hash: str


@lru_cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def _tail_tokens(text: str, n: int) -> str:
    tokens = _encoding().encode(text)
    return _encoding().decode(tokens[-n:]).strip()


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        raise ValueError("document must start with YAML front-matter")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm) or {}
    for key in ("title", "doc_type", "tier"):
        if key not in meta:
            raise ValueError(f"front-matter missing '{key}'")
    return meta, body


def _word_windows(paragraph: str, budget: int) -> list[str]:
    """Split one oversize paragraph into word windows that each fit the token budget."""
    words, out, cur = paragraph.split(), [], []  # type: ignore[var-annotated]
    for w in words:
        if cur and count_tokens(" ".join([*cur, w])) > budget:
            out.append(" ".join(cur))
            cur = []
        cur.append(w)
    if cur:
        out.append(" ".join(cur))
    return out


def _split_section(content: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    if count_tokens(content) <= max_tokens:
        return [content]
    budget = max_tokens - overlap_tokens - 2  # room for the overlap prefix and its separator
    paragraphs: list[str] = []
    for p in (p.strip() for p in content.split("\n\n")):
        if p:
            paragraphs.extend(_word_windows(p, budget) if count_tokens(p) > budget else [p])
    pieces: list[str] = []
    cur: list[str] = []
    for p in paragraphs:
        if cur and count_tokens("\n\n".join([*cur, p])) > budget:
            pieces.append("\n\n".join(cur))
            cur = []
        cur.append(p)
    if cur:
        pieces.append("\n\n".join(cur))
    return [pieces[0]] + [
        f"{_tail_tokens(pieces[i - 1], overlap_tokens)}\n\n{pieces[i]}" for i in range(1, len(pieces))
    ]


def chunk_markdown(doc_id: str, text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[Chunk]:
    meta, body = _split_front_matter(text)
    title = str(meta["title"])
    doc_type = cast(DocType, meta["doc_type"])
    default_tier = cast(ChunkTier, meta["tier"])

    # Collect sections: (path parts, tier, lines)
    sections: list[tuple[list[str], ChunkTier, list[str]]] = [([], default_tier, [])]
    h2_title: str | None = None
    h2_tier: ChunkTier = default_tier
    for line in body.splitlines():
        m = _HEADING.match(line)
        if not m:
            sections[-1][2].append(line)
            continue
        level, heading, tag = m.group(1), m.group(2), m.group(3)
        if level == "##":
            h2_title = heading
            h2_tier = cast(ChunkTier, tag) if tag else default_tier
            sections.append(([heading], h2_tier, []))
        else:
            parts = [h2_title, heading] if h2_title else [heading]
            sections.append((parts, cast(ChunkTier, tag) if tag else h2_tier, []))

    chunks: list[Chunk] = []
    for parts, tier, lines in sections:
        content = "\n".join(lines).strip()
        if not content:
            continue
        section_path = " > ".join([title, *parts])
        for piece in _split_section(content, max_tokens, overlap_tokens):
            embed_text = f"{section_path}\n\n{piece}"
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    section_path=section_path,
                    tier=tier,
                    doc_type=doc_type,
                    content=piece,
                    embed_text=embed_text,
                    content_hash=hashlib.sha256(embed_text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks


def extract_refund_limits(chunks: list[Chunk]) -> dict[Tier, tuple[int, int]]:
    """Read the machine-checkable refund sentences out of tier-tagged chunks: tier -> (max_cents, window_days)."""
    limits: dict[Tier, tuple[int, int]] = {}
    for c in chunks:
        if c.tier == "all":
            continue
        tier = cast(Tier, c.tier)
        if m := _REFUND_LIMIT.search(c.content):
            limits[tier] = (int(m.group(1).replace(",", "")) * 100, int(m.group(2)))
        elif _NOT_ELIGIBLE.search(c.content) and c.doc_id == "refunds":
            limits[tier] = (0, 0)
    return limits
