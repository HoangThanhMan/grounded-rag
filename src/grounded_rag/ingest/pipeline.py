"""Offline indexing: corpus directory -> chunks -> vector store.

Idempotent by construction (content-hashed chunk ids), so running it twice
is a no-op rather than a duplicate index. Each chunker has its own index;
`--recreate` drops that index first, which is what you want after changing
the chunker itself (old chunks would otherwise linger next to the new ones).

    python -m grounded_rag.ingest.pipeline --source data/corpus --config configs/full.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

from grounded_rag.config import RunConfig
from grounded_rag.ingest.chunkers import get_chunker
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.retrieval.store import get_store
from grounded_rag.types import Chunk


def ingest(source: Path, config: RunConfig, *, recreate: bool = False) -> dict[str, int]:
    chunker = get_chunker(config.retrieval.chunker)
    store = get_store(config.retrieval.chunker)
    if recreate:
        store.reset()

    all_chunks: list[Chunk] = []
    files = 0
    for path in iter_corpus(source):
        doc = load_file(path)
        all_chunks.extend(chunker(doc.text, doc.doc_id, meta=doc.meta))
        files += 1

    written = store.upsert(all_chunks)
    return {"files": files, "chunks": len(all_chunks), "written": written}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="data/corpus", type=Path)
    ap.add_argument("--config", default="configs/full.yaml")
    ap.add_argument("--recreate", action="store_true", help="drop this chunker's index first")
    args = ap.parse_args()

    stats = ingest(args.source, RunConfig.from_yaml(args.config), recreate=args.recreate)
    print(f"files={stats['files']} chunks={stats['chunks']} newly_written={stats['written']}")


if __name__ == "__main__":
    main()
