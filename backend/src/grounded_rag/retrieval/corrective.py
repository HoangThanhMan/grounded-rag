"""Retrieval, including the one place the pipeline loops on it.

    search(question) ──── top score ≥ confident_score ────────────► done
          │ weaker
          ▼
    plan  (1 LLM call): still a legal question? rewritten / split queries
          │
    search(each new query) ─► merge: round-robin, dedupe, floor ──► done
          (at most max_rounds rounds, always inside the call budget)

A CRAG-style corrective loop, written by hand: two branches, a hard bound,
and its own row in the eval table. Why not an agent framework: the stop
condition and the budget are the whole design, and a framework would hide them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from grounded_rag.compute import run_model
from grounded_rag.config import RunConfig
from grounded_rag.generation.llm_client import MeteredLLM
from grounded_rag.generation.prompts import build_planner_prompt, planner_system_prompt
from grounded_rag.observability.tracing import trace
from grounded_rag.retrieval import cache
from grounded_rag.retrieval.hybrid import reciprocal_rank_fusion
from grounded_rag.retrieval.reranker import get_reranker
from grounded_rag.retrieval.store import Hits, get_store
from grounded_rag.types import Chunk

log = logging.getLogger("grounded_rag.corrective")


@dataclass
class Plan:
    in_domain: bool
    queries: list[str]


@dataclass
class Retrieval:
    hits: Hits                      # floor applied, at most rerank_to, context order
    out_of_domain: bool = False


def search(query: str, config: RunConfig, as_of: date | None) -> Hits:
    """One query through hybrid retrieval and the cross-encoder. The scores
    that come back are rerank scores - the scale the floor is defined on."""
    r = config.retrieval
    if cache.enabled() and (hits := cache.get(query, as_of, r)) is not None:
        return hits
    store = get_store(r.chunker)
    runs = [store.dense_search(query, r.top_k_dense, as_of)]
    if r.hybrid:
        runs.append(store.sparse_search(query, r.top_k_sparse, as_of))
    fused = reciprocal_rank_fusion(runs)[: r.rerank_candidates]
    hits = get_reranker().rerank(query, fused, r.rerank_to)
    # an empty result means an empty index, never a fact about the query
    if cache.enabled() and hits:
        cache.put(query, as_of, r, hits)
    return hits


async def retrieve(
    question: str, config: RunConfig, llm: MeteredLLM, as_of: date | None
) -> Retrieval:
    c, r = config.corrective, config.retrieval
    with trace("retrieve", query=question) as span:
        results = [await run_model(search, question, config, as_of)]
        span["top_score"] = round(_best(results), 4)
    tried = [question]

    for _ in range(c.max_rounds if c.enabled else 0):
        if _best(results) >= c.confident_score:
            break
        # One call stays in reserve: the answer itself still has to be written.
        if llm.left < 2:
            break
        with trace("plan") as span:
            before = llm.tokens
            plan = await plan_queries(question, tried, config, llm)
            span.update(in_domain=plan.in_domain, queries=plan.queries, tokens=llm.tokens - before)
        if not plan.in_domain:
            return Retrieval(hits=[], out_of_domain=True)
        # A planner that echoes the question back ("...?" vs "...") has
        # nothing new to offer - searching it again only costs time.
        seen = {_key(q) for q in tried}
        fresh = [q for q in dict.fromkeys(plan.queries) if _key(q) not in seen]
        if not fresh:
            break
        for q in fresh:
            with trace("retrieve", query=q) as span:
                results.append(await run_model(search, q, config, as_of))
                span["top_score"] = round(_best(results[-1:]), 4)
        tried.extend(fresh)

    return Retrieval(hits=merge(results, r.rerank_to, r.min_score))


async def plan_queries(
    question: str, tried: list[str], config: RunConfig, llm: MeteredLLM
) -> Plan:
    res = await llm.complete(
        planner_system_prompt(config.corrective.max_queries),
        build_planner_prompt(question, tried),
        temperature=0.0,
        # generous: a thinking model spends part of it before the JSON starts
        max_tokens=1024,
    )
    plan = parse_plan(res.text, config.corrective.max_queries)
    if not plan.queries:
        log.debug("planner gave no usable queries (truncated=%s): %r", res.truncated, res.text)
    return plan


def parse_plan(raw: str, max_queries: int) -> Plan:
    """Tolerant on purpose: a malformed plan degrades to "no new queries",
    never to an error - the first retrieval is still there to answer from."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw_queries = data.get("queries")
    queries = [
        q.strip() for q in (raw_queries if isinstance(raw_queries, list) else [])
        if isinstance(q, str) and q.strip()
    ]
    return Plan(in_domain=data.get("in_domain") is not False, queries=queries[:max_queries])


def merge(results: list[Hits], top_n: int, min_score: float) -> Hits:
    """Round-robin over the per-query lists, so every sub-question gets a seat
    in the context; de-duplicated, best score kept, floor applied. A single
    list passes through in its own order."""
    lists = [[(chunk, s) for chunk, s in hits if s >= min_score] for hits in results]
    best: dict[str, tuple[Chunk, float]] = {}
    order: list[str] = []
    for rank in range(max((len(hits) for hits in lists), default=0)):
        for hits in lists:
            if rank >= len(hits):
                continue
            chunk, score = hits[rank]
            if chunk.chunk_id in best:
                if score > best[chunk.chunk_id][1]:
                    best[chunk.chunk_id] = (chunk, score)
            elif len(order) < top_n:
                order.append(chunk.chunk_id)
                best[chunk.chunk_id] = (chunk, score)
    return [best[cid] for cid in order]


def _best(results: list[Hits]) -> float:
    return max((hits[0][1] for hits in results if hits), default=0.0)


def _key(query: str) -> str:
    return " ".join(re.findall(r"\w+", query.lower()))
