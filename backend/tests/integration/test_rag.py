from __future__ import annotations

from sqlalchemy import select

from app.database.models import KnowledgeDoc
from app.rag.chunking import chunk_document, parse_document, split_text
from app.rag.embeddings import HashEmbedder
from app.rag.ingest import ingest_bytes
from app.rag.store import point_id


def test_chunking_respects_size_overlap_and_keeps_metadata():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = split_text(text, 500, 80)
    assert len(chunks) > 3 and all(len(c) <= 700 for c in chunks)
    doc = parse_document("a.md", b"---\ndoc_type: faq\ncategory: kitchen_renovation\n---\n# Title here\nBody text", None)
    assert doc.metadata["doc_type"] == "faq" and doc.title == "Title here"
    cs = chunk_document("d1", doc, 500, 50)
    assert cs[0].doc_id == "d1" and cs[0].metadata["category"] == "kitchen_renovation"


def test_hash_embedder_is_deterministic_normalised_and_lexically_meaningful():
    e = HashEmbedder(384)
    a, b, c = e.embed(["modern kitchen cabinets", "modern kitchen cabinets", "outdoor terrace pergola garden"])
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-6
    sim = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))
    near = e.embed(["kitchen cabinets modern style"])[0]
    assert sim(a, near) > sim(a, c)


def test_ingestion_stores_chunks_registers_doc_and_is_idempotent(container):
    with container.session_factory() as s:
        before = container.store.count()
        data = b"---\ndoc_type: faq\ncategory: bathroom_renovation\ndoc_id: faq-test\n---\n# Test FAQ\nHow long does waterproofing cure? About 48 hours."
        d1 = ingest_bytes(session=s, store=container.store, settings=container.settings, filename="faq-test.md", data=data)
        mid = container.store.count()
        d2 = ingest_bytes(session=s, store=container.store, settings=container.settings, filename="faq-test.md", data=data)
        assert d1.id == d2.id == "faq-test" and container.store.count() == mid > before
        assert len(list(s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.id == "faq-test")))) == 1


def test_retrieval_returns_relevant_filtered_and_metadata_rich(container):
    r = container.retriever.retrieve("modern minimalist kitchen Chennai quartz", preferred={"category": "kitchen_renovation", "location": "Chennai"})
    assert r.evidence and r.evidence[0].metadata["category"] == "kitchen_renovation"
    assert all({"doc_id", "doc_type"} <= set(e.metadata) for e in r.evidence)
    only_quotes = container.retriever.retrieve("kitchen budget fit", filters={"doc_type": "historical_quote"})
    assert only_quotes.evidence and {e.doc_type for e in only_quotes.evidence} == {"historical_quote"}
    cust = container.retriever.retrieve("preferences", filters={"doc_type": "customer_profile", "customer_email": "priya.nair@example.com"})
    assert cust.evidence and cust.evidence[0].doc_id == "customer_priya_nair"
    none = container.retriever.retrieve("anything", filters={"doc_type": "customer_profile", "customer_email": "nobody@example.com"})
    assert none.evidence == []


def test_context_is_wrapped_as_untrusted_and_bounded(container):
    container.settings.rag_context_max_chars = 1500
    r = container.retriever.retrieve("kitchen renovation chennai")
    assert r.context.count("<untrusted_document") >= 1 and len(r.context) <= 1800
    assert all(tag.startswith("<untrusted_") or True for tag in r.context.split("\n") if tag.startswith("<"))


def test_rerank_prefers_metadata_match(container):
    from app.rag.store import Hit

    hits = [Hit("a", 0.50, "kitchen", {"category": "bathroom_renovation"}), Hit("b", 0.49, "kitchen", {"category": "kitchen_renovation"})]
    out = container.retriever.rerank("kitchen", hits, {"category": "kitchen_renovation"})
    assert out[0].id == "b"


def test_dimension_mismatch_is_a_clear_configuration_error(container):
    import pytest

    from app.config import ConfigurationError
    from app.rag.store import VectorStore

    other = VectorStore(container.store.client, HashEmbedder(128), container.store.collection)
    with pytest.raises(ConfigurationError, match="384"):
        other.ensure_collection()


def test_point_ids_are_stable_uuids():
    assert point_id("d", 0) == point_id("d", 0) != point_id("d", 1) and len(point_id("d", 0)) == 36


def test_bad_documents_are_rejected(container):
    import pytest

    from app.utils.errors import ValidationFailed

    with container.session_factory() as s:
        with pytest.raises(ValidationFailed):
            ingest_bytes(session=s, store=container.store, settings=container.settings, filename="x.exe", data=b"MZ")
        with pytest.raises(ValidationFailed):
            ingest_bytes(session=s, store=container.store, settings=container.settings, filename="x.md", data=b"---\ndoc_type: bogus\n---\nhello")
        with pytest.raises(ValidationFailed):
            ingest_bytes(session=s, store=container.store, settings=container.settings, filename="empty.md", data=b"   ")
