from pathlib import Path

from app.rag.chunker import chunk_markdown, count_tokens, extract_refund_limits

CORPUS = Path(__file__).resolve().parents[3] / "data" / "policies"

DOC = """---
title: Refund Policy
doc_type: policy
tier: all
---
## Overview
General text.
## Pro tier {tier=pro}
Refunds of up to $200 are available within 30 days of the invoice date.
### Annual plans
Annual text.
"""


def test_splits_on_headings_with_breadcrumb_and_tier():
    chunks = chunk_markdown("refunds", DOC)
    assert [c.section_path for c in chunks] == [
        "Refund Policy > Overview",
        "Refund Policy > Pro tier",
        "Refund Policy > Pro tier > Annual plans",
    ]
    assert [c.tier for c in chunks] == ["all", "pro", "pro"]
    assert all(c.doc_type == "policy" and c.doc_id == "refunds" for c in chunks)
    assert chunks[1].embed_text.startswith("Refund Policy > Pro tier\n\n")
    assert "{tier=" not in chunks[1].embed_text


def test_tagged_h2_resets_for_next_untagged_h2():
    doc = DOC + "## Contact\nEmail us.\n"
    assert chunk_markdown("refunds", doc)[-1].tier == "all"


def test_long_section_split_with_overlap_only_inside_section():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(8))
    chunks = chunk_markdown("d", f"---\ntitle: T\ndoc_type: policy\ntier: all\n---\n## Big\n{body}\n## Small\nshort")
    big = [c for c in chunks if c.section_path == "T > Big"]
    assert len(big) > 1 and all(count_tokens(c.content) <= 500 for c in big)
    # consecutive pieces share overlapping text
    assert big[0].content.split()[-1] in big[1].content
    assert chunks[-1].content.strip() == "short"


def test_empty_sections_are_skipped():
    doc = "---\ntitle: T\ndoc_type: policy\ntier: all\n---\n## Empty\n\n## Full\ntext\n"
    assert [c.section_path for c in chunk_markdown("d", doc)] == ["T > Full"]


def test_hash_stable_and_unique_per_section():
    a, b = chunk_markdown("refunds", DOC), chunk_markdown("refunds", DOC)
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
    assert len({c.content_hash for c in a}) == len(a)


def test_extract_refund_limits_handles_commas_and_free():
    doc = """---
title: R
doc_type: policy
tier: all
---
## Free plan {tier=free}
Free plan charges are not eligible for refunds.
## Enterprise plan {tier=enterprise}
Refunds of up to $1,000 are available within 60 days of the invoice date.
"""
    assert extract_refund_limits(chunk_markdown("refunds", doc)) == {"free": (0, 0), "enterprise": (100000, 60)}


def test_corpus_refund_limits_match_policy_limits():
    chunks = [c for p in sorted(CORPUS.glob("*.md")) for c in chunk_markdown(p.stem, p.read_text(encoding="utf-8"))]
    assert len(chunks) > 20
    assert extract_refund_limits(chunks) == {"free": (0, 0), "pro": (20000, 30), "enterprise": (100000, 60)}


def test_hash_changes_when_only_the_tier_tag_changes():
    retagged = DOC.replace("## Pro tier {tier=pro}", "## Pro tier {tier=enterprise}")
    assert chunk_markdown("refunds", DOC)[1].content_hash != chunk_markdown("refunds", retagged)[1].content_hash
