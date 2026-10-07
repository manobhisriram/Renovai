"""Document parsing + chunking (markdown/text/JSON/PDF)."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.utils import yaml_lite as yl


@dataclass
class ParsedDocument:
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    doc_id: str
    index: int
    text: str
    metadata: dict[str, Any]


def parse_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse a simple `---` key: value front-matter block."""
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return yl.load_simple(raw[3:end]), raw[end + 4:].lstrip("\n")
    return {}, raw


def parse_document(filename: str, data: bytes, base_metadata: dict[str, Any] | None = None) -> ParsedDocument:
    name = filename.lower()
    meta = dict(base_metadata or {})
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        title = meta.get("title") or filename
    elif name.endswith(".json"):
        obj = json.loads(data.decode("utf-8"))
        text = json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, dict) or "text" not in obj else str(obj["text"])
        if isinstance(obj, dict):
            meta = {**{k: v for k, v in obj.items() if k != "text" and isinstance(v, (str, int, float, bool))}, **meta}
        title = meta.get("title") or filename
    else:
        raw = data.decode("utf-8", errors="replace")
        fm, text = parse_front_matter(raw)
        meta = {**fm, **meta}
        title = meta.get("title") or _first_heading(text) or filename
    return ParsedDocument(title=str(title), text=text.strip(), metadata=meta)


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Paragraph-aware splitter; falls back to sentence/character windows for long paragraphs."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            step = max(1, max_chars - overlap)
            for i in range(0, len(para), step):
                chunks.append(para[i:i + max_chars])
            continue
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + "\n\n" + para).strip() if tail else para
        else:
            buf = f"{buf}\n\n{para}".strip() if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def chunk_document(doc_id: str, doc: ParsedDocument, max_chars: int, overlap: int) -> list[Chunk]:
    pieces = split_text(doc.text, max_chars, overlap) or ([doc.title] if doc.title else [])
    return [Chunk(doc_id=doc_id, index=i, text=f"{doc.title}\n{p}", metadata=doc.metadata) for i, p in enumerate(pieces)]


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
