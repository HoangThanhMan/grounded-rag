# Evaluation

One question: **compared with a naive RAG, does the app cite the right clause,
and does it refuse when the law says nothing?**

- **Questions:** 100 from the `test` split of [`questions.jsonl`](questions.jsonl),
  drawn with a fixed seed: 60 with an answer in the corpus, 40 without (13 out of
  scope, 13 resting on a false premise, 14 near misses that ask for a detail the
  law does not state). How they were written and labelled:
  [`LABELING.md`](LABELING.md).
- **Systems:** the same pipeline, prompt and LLM twice. *Naive RAG* reads
  fixed-size chunks with dense search only and no floor. *The app* reads
  clause-level chunks with hybrid search, a reranker and a retrieval floor.
- **Columns:**
  - *Gold clause retrieved*: a gold clause is among the five sources.
  - *Correct answer*: the answer cites a source holding the gold clause and
    states every number in the gold answer.
  - *Refuses when the law is silent*: on the 40 unanswerable questions.
  - *Refuses an answerable question*: on the 60 answerable ones.
- **Scoring is automatic.** No LLM judge, so a rerun costs only the answers.

```bash
docker compose up -d qdrant
make ingest                  # both indexes: clause chunks and fixed-size chunks
make eval                    # needs an LLM key in .env; resumable
```

Each answer, its sources and its scores are in `results/<system>.jsonl`;
`python -m eval.report` rebuilds the table in `results/summary.md`.

Limits: "correct" is a proxy (right clause and right numbers, not a lawyer's
reading); 100 questions means one question moves a rate by 0.01–0.025; one
generator.
