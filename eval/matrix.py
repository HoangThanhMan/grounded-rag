"""Run the benchmark matrix: generator × configuration × seed, then judge, then tabulate.

    python -m eval.matrix eval/matrix.yaml               # everything not done yet
    python -m eval.matrix eval/matrix.yaml --dry-run     # what would run
    python -m eval.matrix eval/matrix.yaml --only-config full --no-judge
    python -m eval.matrix eval/matrix.yaml --only-config full --only-seed 2   # one cell

Each cell is one `python -m eval.run --resume` in its own process - the NLI
cache would otherwise flatter whichever configuration runs second - with the
generator set through the environment. A cell is done when its report exists
with no errored case; anything else is resumed from its checkpoint, so a quota
that runs out halfway costs a rerun of this command, nothing more. Cells run
seed by seed, so the first full comparison is ready before the repeats are.

After the runs every report is judged by an LLM from another model family
(eval/judge.py), and eval/report.py writes summary.md and risk-coverage.svg
next to the reports. Reindex first (`make ingest`) whenever the corpus changed:
the matrix never ingests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def cells(spec: dict) -> list[dict]:
    out = []
    for seed in spec["seeds"]:
        for gen in spec["generators"]:
            for config in spec["configs"]:
                path = Path(spec["out"]) / gen["name"] / f"{config}.s{seed}.json"
                out.append({"seed": seed, "generator": gen, "config": config, "path": path})
    return out


def done(path: Path) -> bool:
    if not path.exists():
        return False
    return not json.loads(path.read_text(encoding="utf-8")).get("errored")


def env_for(gen: dict, spec: dict) -> dict:
    env = dict(os.environ)
    key = os.environ.get(gen.get("api_key_env", ""), "")
    env.update({
        "LLM_PROVIDER": gen["provider"], "LLM_MODEL": gen["model"],
        "LLM_REASONING_EFFORT": gen.get("reasoning_effort", ""),
        # one trace per answer is not what a benchmark wants
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
        "RETRIEVAL_CACHE_DIR": spec.get("retrieval_cache", ""),
    })
    if gen["provider"] in ("openai", "vllm"):
        prefix = gen["provider"].upper()
        env[f"{prefix}_BASE_URL"] = gen["base_url"]
        env[f"{prefix}_API_KEY"] = key
    elif gen["provider"] in ("gemini", "anthropic"):
        env[f"{gen['provider'].upper()}_API_KEY"] = key
    return env


def run_cell(cell: dict, spec: dict) -> int:
    cmd = [sys.executable, "-m", "eval.run", "--config", f"configs/{cell['config']}.yaml",
           "--dataset", spec["dataset"], "--split", spec["split"], "--as-of", str(spec["as_of"]),
           "--temperature", str(spec["temperature"]), "--seed", str(cell["seed"]),
           "--out", str(cell["path"]), "--resume",
           # a spent daily quota stops the cell instead of erroring every question
           "--max-consecutive-errors", str(spec.get("max_consecutive_errors", 5))]
    print(f"[matrix] {cell['generator']['name']} {cell['config']} s{cell['seed']}", flush=True)
    return subprocess.run(cmd, env=env_for(cell["generator"], spec)).returncode


def judge(paths: list[Path], spec: dict) -> int:
    j = spec["judge"]
    cmd = [sys.executable, "-m", "eval.judge", "run", *map(str, paths), "--model", j["model"],
           "--base-url", j["base_url"], "--api-key-env", j["api_key_env"],
           "--reasoning-effort", j.get("reasoning_effort", "")]
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-config")
    ap.add_argument("--only-generator")
    ap.add_argument("--only-seed", type=int)
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()
    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    todo = [c for c in cells(spec)
            if (not args.only_config or c["config"] == args.only_config)
            and (not args.only_generator or c["generator"]["name"] == args.only_generator)
            and (args.only_seed is None or c["seed"] == args.only_seed)]
    for c in todo:
        state = "done" if done(c["path"]) else "todo"
        if args.dry_run:
            print(f"{state:5} {c['path']}")
    if args.dry_run:
        return 0
    failed = []
    for c in todo:
        if done(c["path"]):
            continue
        if run_cell(c, spec) != 0 or not done(c["path"]):
            failed.append(c["path"])
            # a provider that refuses one cell will refuse the next one too
            print(f"[matrix] stopped at {c['path']}; rerun to resume", flush=True)
            break
    finished = [c["path"] for c in todo if done(c["path"])]
    if finished and spec.get("judge") and not args.no_judge and judge(finished, spec) != 0:
        print("[matrix] judging stopped early; rerun to resume", flush=True)
        failed.append("judge")
    if finished:
        out = Path(spec["out"])
        subprocess.run([sys.executable, "-m", "eval.report", *map(str, finished),
                        "--out", str(out / "summary.md"), "--svg", str(out / "risk-coverage.svg")])
    print(f"[matrix] {len(finished)}/{len(todo)} cells done")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
