# Reports

Every number in the top-level README comes from a file in this folder. The
folder root is scratch space: `make eval`, `make eval-all` and CI write there,
and git ignores it. What is kept lives in four subfolders.

## `runs/` — benchmark runs

One folder per run, one JSON per configuration. Each case carries the answer,
its claims and verdicts, the sources and per-step timings, so any table can be
recomputed without calling an LLM (`python -m eval.report`, `python -m eval.rejudge`).

| Run | What it is |
|---|---|
| [`2026-10-12-gemini/`](runs/2026-10-12-gemini/) | The README Results table: four configurations, `gemini-3.1-flash-lite`, 80 `test` questions |
| [`2026-09-15-ollama/`](runs/2026-09-15-ollama/) | Earlier `full` run on an open model through Ollama 0.34.0 |
| [`2026-09-11-smoke/`](runs/2026-09-11-smoke/) | The first end-to-end run, seven questions, kept as the starting point |

## `ablations/` — what a component buys

| File | Question | Made by |
|---|---|---|
| [`closed-book.json`](ablations/closed-book.json) | Does retrieval help at all? Same questions, no documents | `make closed-book` |
| [`floor-sweep.json`](ablations/floor-sweep.json) | Where should the retrieval floor sit? | `scripts/sweep_floor.py` |

## `calibration/` — the guard threshold

| File | Contents | Made by |
|---|---|---|
| [`tau-dev-claims.json`](calibration/tau-dev-claims.json) | Claims from the `dev` split, labelled by hand as grounded or not | `scripts/calibrate_tau.py collect`, then labelling |
| [`tau-sweep.json`](calibration/tau-sweep.json) | Catch rate and false-block rate as τ moves; drawn as `assets/tau-curve.svg` | `scripts/calibrate_tau.py sweep` |

## `grading/` — the check on the NLI instrument

| File | Contents |
|---|---|
| [`hand-graded.json`](grading/hand-graded.json) | 41 answers from the 2026-10-12 run: 30 drawn at random, plus every other answer the instrument flagged. Each has a grade (`correct` · `partly` · `wrong`) and a note |
| [`hand-graded.summary.json`](grading/hand-graded.summary.json) | Grades by configuration, and grades against the instrument's verdict |
