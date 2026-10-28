"""Indexing: a file -> chunks -> vector store.

The API calls `ingest_file` for an upload; the CLI below indexes a whole
directory, which is how the evaluation builds its naive (recursive) index:

    python -m grounded_rag.ingest.pipeline --source data/corpus --chunker recursive
"""

from __future__ import annotations

import argparse
from pathlib import Path

from grounded_rag.ingest.chunkers import get_chunker
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.retrieval.store import get_store
from grounded_rag.types import DocMeta


def ingest_file(path: Path, doc_id: str, meta: DocMeta, chunker: str = "structural") -> int:
    """Index one document, replacing whatever was indexed under its id, and
    return the number of chunks. A document with no text - a scanned PDF -
    is an error, not an empty success."""
    doc = load_file(path)
    chunks = get_chunker(chunker)(doc.text, doc_id, meta=meta) if doc.text.strip() else []
    if not chunks:
        raise ValueError("no text extracted from the file")
    store = get_store(chunker)
    store.delete_document(doc_id)
    store.upsert(chunks)
    return len(chunks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="data/corpus", type=Path)
    ap.add_argument("--chunker", default="structural", choices=["structural", "recursive"])
    args = ap.parse_args()

    for path in iter_corpus(args.source):
        doc = load_file(path)
        n = ingest_file(path, doc.doc_id, doc.meta, args.chunker)
        print(f"{doc.doc_id}: {n} chunks")


if __name__ == "__main__":
    main()
