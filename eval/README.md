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
  - *Gold clause retrieved*: a gold clause is among the five sources. A source
    holds a clause if it contains all of it or an unbroken 30-word run of it,
    the same rule for both systems - so a fixed-size window that cuts a long
    clause is judged like the clause chunk's own piece of it.
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

## Hard questions

Fifteen more, in their own `hard` split so the 100-question sample never
changes, asked with `python -m eval.run --system <s> --set hard` (`make eval`
runs them too). Each kind fails in its own way, so the report breaks them out:

- **`multi_part`** (8): the answer needs two or three clauses, often of two
  laws - leave from the Labour Code, pay from the Social Insurance Law - and
  sometimes a sum (two children, eleven years of service).
- **`scheme_trap`** (4): an employee's question, where a clause of the
  *voluntary* scheme reads like the answer: Điều 95 pays 2,000,000 đồng per
  child, but not to employees. `trap_chunks` lists those clauses.
- **`compare_versions`** (3): the 2014 law against the 2024 one. The app
  reads the law in force on one day, so it cannot answer these yet; they
  measure that limit.

Two more columns: *every gold clause retrieved* and *complete* (cites every
gold clause and states every number), and *cites the wrong scheme*. Matching
is on text, so a trap clause must not share a 30-word run with its gold
clause; two candidate questions failed that check and were dropped.

*Cites the wrong scheme* counts citations, not misreadings: "under the
voluntary scheme it is 2,000,000 đồng [C1]" cites the trap and says it right.
Read the answers in `results/*_hard.jsonl` before reading much into it.

Limits: "correct" is a proxy (right clause and right numbers, not a lawyer's
reading); 100 questions means one question moves a rate by 0.01–0.025; one
generator.
