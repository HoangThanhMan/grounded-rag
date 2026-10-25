# grounded-rag

[![ci](https://github.com/HoangThanhMan/grounded-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/HoangThanhMan/grounded-rag/actions/workflows/ci.yml)

**A RAG API that verifies every claim it generates against the passage it cites — and refuses to answer when the documents do not support it.**

Most RAG demos retrieve, generate, and stop there. This one adds the part that
decides whether the answer can be trusted: each sentence is checked against its
cited source by a self-hosted NLI model, unsupported sentences never reach the
user, and the whole thing is measured on a benchmark where **40% of the
questions have no answer in the corpus at all**.

Corpus: Vietnamese labour law. Domain where a plausible-sounding invented clause
is worse than no answer.

---

## Results

Generator `gemini-3.1-flash-lite` (free tier, temperature 0), law read as of
2026-10-12, scored on the 80 `test` questions (50 answerable, 30 unanswerable)
by the guard's NLI model at τ 0.5. Every answer, citation and per-step timing
is in [`reports/2026-10-12-gemini/`](reports/2026-10-12-gemini/); the tables
come from `python -m eval.report` over those files.

| Configuration | Halluc. ↓ | Correct abst. ↑ | False abst. ↓ | Cite prec. ↑ | Retr. recall ↑ | LLM calls/q | p95 |
|---|---|---|---|---|---|---|---|
| `baseline` — plain RAG | 0.088 (7/80) | 0.93 (28/30) | 0.02 (1/50) | 0.87 | 0.97 | 1.00 | 40 s |
| `threshold` — retrieval floor | 0.075 (6/80) | 0.97 (29/30) | 0.06 (3/50) | 0.83 | 0.89 | 0.76 | 34 s |
| `full` — NLI guard | 0.000 (0/80)\* | 0.93 (28/30) | 0.08 (4/50) | 0.86 | 0.93 | 0.86 | 69 s |
| `agentic` — full + corrective retrieval | 0.000 (0/80)\* | 0.93 (28/30) | 0.08 (4/50) | 0.86 | 0.95 | 1.26 | 71 s |

Which layer of defence caught the unanswerable questions (share of all 30):

| Configuration | retrieval floor | out of domain | model refusal | guard |
|---|---|---|---|---|
| `baseline` | – | – | 0.93 | – |
| `threshold` | 0.57 | 0 | 0.40 | – |
| `full` | 0.53 | 0 | 0.40 | 0 |
| `agentic` | 0.37 | 0 | 0.53 | 0.03 |

How to read it:

- **\* The guard's zero is not an independent measurement.** The judge is the
  guard's own model at the guard's own τ, so whatever the judge would flag the
  guard has already removed. What the table can show is what that removal
  cost. Of the six answers `threshold` lets through that the judge flags,
  under `full` two came out clean on the first attempt (different chunks, a
  different answer), two were regenerated and trimmed to the claims the guard
  accepts, and two were refused after the regeneration — two answerable
  questions lost. Whether those six were wrong in the first place is for the
  30-answer hand-graded sample to say, and that is not done yet (see
  [Limitations](#limitations)).
- **The retrieval floor is the cheap win.** It turns away 17 of the 30
  unanswerable questions before any LLM call, which is why `threshold` makes
  fewer calls than there are questions. The price is two answerable questions
  whose retrieval falls under the floor (false abstention 1 → 3 of 50); an
  answer that never retrieves anything also scores zero retrieval recall,
  hence 0.97 → 0.89.
- **`full` changes two things at once:** the guard, and the chunker
  (`recursive` → `structural`, split on Điều / Khoản). The recall and citation
  columns move with the chunker as much as with the guard.
- **Corrective retrieval did not pay for itself on this run.** It made 24
  rewrite calls; 21 went to questions with no answer to find. It lifted
  retrieval recall on colloquial questions from 0.89 to 1.00, but recovered no
  answer: the one colloquial question it pulled over the floor (`a004`) was
  then refused by the guard. Net, 0.4 more LLM calls per question for the same
  abstention rates.
- **Latency is this machine, not the design.** Everything but the generator
  runs on a laptop CPU: retrieval and reranking take ~8–11 s per question and
  each free-tier Gemini call ~12 s, so p50 is ~24 s in every configuration.
  The guard's p95 comes from the questions it catches — verification, a
  regeneration and a second verification, all on CPU; the slowest took 142 s.
- 30 unanswerable and 50 answerable questions are small samples. One question
  moves a rate by 0.02 or 0.03, and none of the differences above is more than
  a few questions.

Benchmark: 100 hand-labelled questions — 63 answerable, 37 unanswerable across
three adversarial types, in [`eval/dataset/questions.jsonl`](eval/dataset/questions.jsonl).
Twenty of them are a `dev` split used only to calibrate the guard threshold; the
numbers above are scored on the 80 `test` questions τ was never fitted on.
Labelling protocol and the decisions taken while building it:
[`eval/dataset/LABELING.md`](eval/dataset/LABELING.md).

`make check-dataset` resolves every gold reference through the same clause
index the metrics score with, checks each number in a gold answer against the
clause it cites, and searches the corpus for anything labelled unanswerable —
a gold reference that no longer resolves would silently zero retrieval recall,
so it runs in CI.

Every configuration is scored by **the same instrument after the fact**, so a
configuration without a guard is not flattered by being judged differently.
Because that instrument is the guard's own NLI model, two independent checks sit
next to it: RAGAS with an LLM judge (`make ragas`) and 30 answers scored by hand.

## How it works

```
question ─► hybrid retrieval (bge-m3 + BM25) ─► rerank ─┬─ weak? ─► [agentic] rewrite / split, retrieve again
                                                         ▼
                                                  retrieval floor ──► no_context
                                                         │
                                           LLM (citations required) ──► its own refusal ─► abstained
                                                         │
                                         split into claims ─► NLI verify
                                                         │
                              ┌──────────────────────────┤
                              ▼                          ▼
                     all supported → answer     some unsupported →
                                                regenerate once, then
                                                drop the claim or abstain
```

Four layers of defence, cheapest first:

1. **Retrieval floor** — nothing retrieves above threshold, the LLM is never called
2. **Model refusal** — the prompt gives the model one exact sentence for "not in the documents"; it is counted as an abstention, never verified or regenerated
3. **Citation validation** — a citation to a label that was never supplied is caught without running a model
4. **NLI guard** — `P(entailment)` between each claim and its cited passage

The law is read **as of a date**: each document carries its effective and expiry
dates, and a clause that is not in force on `as_of` is never retrieved.

### Corrective retrieval — bounded, and measured

The `agentic` configuration adds one hand-written, CRAG-style loop. When the best
rerank score is weak, a single LLM call rewrites colloquial wording into legal
terms or splits a multi-part question, and retrieval runs again. The loop has a
hard budget (`max_rounds`, `max_llm_calls`) and its own row in the table, so
what it buys (false abstentions recovered) and what it costs (LLM calls, p95)
sit side by side. Why no agent framework: [ADR-0005](docs/adr/0005-corrective-retrieval-loop.md).

## Quick start

No API key and no model weights needed — the `mock` provider runs the whole
pipeline end to end:

```bash
make install && make test
LLM_PROVIDER=mock ADMIN_API_KEY=dev make run   # API and demo UI on http://localhost:8000
ADMIN_API_KEY=dev make seed                    # in another shell: index the sample corpus
```

The mock provider keeps its index inside the process, so `make seed` has to run
against the server that is already up, and again after every restart. `POST
/ingest` is an admin call: off until the server has an `ADMIN_API_KEY`, and it
reads only directories under `data/`. Without
it every question answers `no_context`, correctly — there is nothing indexed to
answer from.

Every `make` target runs through `.venv/bin/python` when that directory exists,
so there is nothing to activate first; `make python` prints the interpreter it
picked.

The real thing:

```bash
make up-qdrant           # Qdrant. The API itself runs natively, not in a container
cp .env.example .env     # LLM_PROVIDER = gemini | ollama | vllm | openai | anthropic
make dev-install
make ingest              # once; skip it if Qdrant already holds the collections
make run                 # then open http://localhost:8000
```

The first question takes 5–15 seconds: the cross-encoder reranker runs on CPU.

Open models, no GPU: `make up-ollama` serves one on CPU, and a benchmark run
then costs no API quota. What that trades away is measured in
[docs/09](docs/09-runbook.md#chạy-bằng-model-mở-ollama) — a 3B model dropped the
citation format on a question `gemini-3.1-flash-lite` answered from the same
prompt. With a GPU, `make up-gpu` serves Qwen2.5-7B-Instruct (AWQ) through vLLM;
set `LLM_PROVIDER=vllm`.

## API

```bash
curl -X POST localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"question": "Nghỉ việc phải báo trước bao nhiêu ngày?", "config": "full"}'
```

```json
{
  "answer": "Người lao động phải báo trước ít nhất 45 ngày [C1].",
  "status": "answered",
  "claims": [{"text": "...", "citations": ["C1"], "entailment": 0.94, "verdict": "supported"}],
  "sources": [{"label": "C1", "score": 0.87,
               "chunk": {"ref": "bo_luat_lao_dong_2019:Điều 35:1", "article": "Điều 35", "clause": "Khoản 1"}}],
  "meta": {"llm_calls": 1, "tokens": 612, "latency_ms": 1840, "abstain_reason": null,
           "steps": [{"name": "retrieve", "ms": 210}, {"name": "generate", "ms": 1350}, {"name": "verify", "ms": 260}]}
}
```

`GET /configs` lists every file in `configs/` with the defences it turns on,
which is how the demo UI knows where to draw the guard threshold.

`status` is one of `answered` · `partial` · `abstained` · `no_context`.
Refusing to answer is a 200, not an error; an unreachable LLM provider is a 503.
`GET /metrics` serves Prometheus metrics: per-step latency, answers by status and
abstain reason, LLM calls and tokens.

## Demo UI

`make run` serves a single-page UI from the API itself at
[`localhost:8000`](http://localhost:8000) — no build step, no second process,
no CORS. It is built around the one thing a RAG demo usually hides: each
sentence of the answer sits next to the passage it was checked against, with
its entailment score drawn against the guard threshold, so a claim that only
just cleared the bar looks different from one that sailed over it. That scale is
the page's only colour, and it is shown full width above the question with the τ
of the selected configuration marked on it, so every gauge below has a legend.
Dropped claims stay on screen, struck through, with the score that killed them.
When the answer is a refusal, the four layers of defence are listed and the one
that fired is marked.

![The demo UI answering a question, with the claim checked against the clause it cites](docs/img/ui.png)

The run above is real: `qwen2.5:3b` on CPU through Ollama, one LLM call, the
claim scored 0.99 against Điều 35 Khoản 1.

`?q=...&config=...` asks straight away, so a demo run is a shareable link.

## Stack

FastAPI · Qdrant (dense + BM25 sparse) · bge-m3 · bge-reranker-v2-m3 ·
mDeBERTa-v3 XNLI · vLLM / Ollama / Gemini · RAGAS · Prometheus · Langfuse ·
Docker Compose · GitHub Actions

No orchestration framework. The pipeline is a handful of steps, its only loop has
two branches, and the interesting part is hand-written; a framework would hide it.

## Documentation

Design docs live in [`docs/`](docs/) — requirements, architecture, data and API
design, the guard design, the evaluation plan, and ADRs recording the decisions
that had a real alternative:

- [Why NLI instead of an LLM judge](docs/adr/0001-nli-over-llm-judge.md)
- [Why Qdrant](docs/adr/0002-qdrant-as-vector-store.md)
- [Why verification happens before streaming](docs/adr/0003-verify-before-stream.md)
- [Why chunking follows the legal structure](docs/adr/0004-structural-chunking.md)
- [Why a hand-written corrective loop and not LangGraph](docs/adr/0005-corrective-retrieval-loop.md)
- [Why BM25 for the sparse half of hybrid search](docs/adr/0006-bm25-sparse-retrieval.md)
- [Why the generator is not fine-tuned](docs/adr/0007-no-generator-fine-tuning.md)

## Limitations

Written up honestly in [docs/06](docs/06-guard-design.md#guard-sai-ở-đâu). The
first one is the finding this project did not want:

- **On the dev split, the NLI model caught none of the errors the generator
  actually made.** Calibrating τ over 23 hand-labelled claims found no threshold
  that separates grounded from ungrounded: all six ungrounded claims score ≥ 0.70,
  and blocking two thirds of them would block nearly half the correct sentences.

  ![Guard on the dev split as τ moves: the catch rate stays at zero while the false-block rate climbs](docs/img/tau-curve.svg)

  What does protect the answer is the cheaper machinery around the NLI model —
  the number rule, uncited claims, and citations to labels that were never
  supplied — and two of those three never run a model at all.
- A 24-pair probe ([`scripts/nli_probe.py`](scripts/nli_probe.py)) says the same
  thing more precisely: the model lets through claims that keep the wording but
  swap the subject, drop a condition, or take the number from the neighbouring
  item — the exact shape of the `near_miss` questions. Doubling the model size
  (`xlm-roberta-large-xnli`) made that group worse, not better.
- Measuring hallucination with the same NLI model that powers the guard is
  circular, and the point above means the circularity is not harmless. The
  hand-graded sample is the check that matters; a second opinion from an LLM
  judge is not in yet, because the only local model available is the one that
  wrote the answers and the hosted free tier allows 20 requests a day.
- The corrective loop spends one extra LLM call on every weak retrieval,
  including the out-of-scope questions it cannot rescue.
- 23 dev claims and 24 probe pairs are small samples. The direction is
  consistent across both and matches the per-question reading, but no percentage
  here should be quoted on its own.
