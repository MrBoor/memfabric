#!/usr/bin/env python3
"""Compare ingest quality across multiple LLM models on a single conversation.

Runs ingest with each model, then queries + judges all with the same model
(GPT-4o-mini) to isolate the effect of ingest quality.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.agent_loop import run_anthropic_loop, run_openai_loop, LoopStats
from src.evaluate import evaluate_dataset
from src.memfabric import MemFabricLocal
from src.query import query_dataset
from src.utils import load_dataset, get_sessions, format_session_text, get_qa_pairs
from src.versions import get_version

# ── Model configs ───────────────────────────────────────────────────────────

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")

MODELS = {
    "haiku": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
    },
    "sonnet": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
    },
    "deepseek-v3": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat-v3-0324",
    },
    "minimax-m2.5": {
        "provider": "openrouter",
        "model": "minimax/minimax-m2.5",
    },
    "mimo-v2-pro": {
        "provider": "openrouter",
        "model": "xiaomi/mimo-v2-pro",
    },
}

QUERY_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
SAMPLE_ID = "conv-26"
VERSION = "v2"
CONCURRENCY = 10


def ingest_with_model(
    model_key: str,
    sample: dict,
    base_dir: str,
    version: str,
) -> tuple[str, LoopStats, str]:
    """Ingest a conversation with a specific model. Returns (model_key, stats, memory_dir)."""
    cfg = MODELS[model_key]
    memory_dir = os.path.join(base_dir, f"memory-{model_key}")
    if os.path.exists(memory_dir):
        shutil.rmtree(memory_dir)
    os.makedirs(memory_dir)

    v = get_version(version)
    memfabric = MemFabricLocal(memory_dir)
    conversation = sample["conversation"]
    speaker_a = conversation.get("speaker_a", "Speaker A")
    speaker_b = conversation.get("speaker_b", "Speaker B")
    sessions = get_sessions(conversation)

    total_stats = LoopStats()

    for session_key, dt, turns in sessions:
        session_text = format_session_text(session_key, dt, turns, speaker_a, speaker_b)
        user_msg = (
            f"Process the following conversation session and store important information "
            f"in memory. The conversation is between {speaker_a} and {speaker_b}.\n\n"
            f"{session_text}"
        )

        if cfg["provider"] == "anthropic":
            messages = [{"role": "user", "content": user_msg}]
            _, stats = run_anthropic_loop(
                messages=messages,
                system=v.ingest_prompt,
                memfabric=memfabric,
                model=cfg["model"],
                version=version,
            )
        else:
            # OpenAI or OpenRouter
            messages = [
                {"role": "system", "content": v.ingest_prompt},
                {"role": "user", "content": user_msg},
            ]
            kwargs = {}
            if cfg["provider"] == "openrouter":
                kwargs["base_url"] = "https://openrouter.ai/api/v1"
                kwargs["api_key"] = OPENROUTER_KEY
            _, stats = run_openai_loop(
                messages=messages,
                memfabric=memfabric,
                model=cfg["model"],
                version=version,
                **kwargs,
            )

        total_stats.input_tokens += stats.input_tokens
        total_stats.output_tokens += stats.output_tokens
        total_stats.tool_calls += stats.tool_calls
        total_stats.llm_calls += stats.llm_calls
        total_stats.elapsed_seconds += stats.elapsed_seconds
        total_stats.errors.extend(stats.errors)

    return model_key, total_stats, memory_dir


def main():
    # Load data
    data = load_dataset("data/locomo10.json")
    sample = next(s for s in data if s["sample_id"] == SAMPLE_ID)
    n_sessions = len(get_sessions(sample["conversation"]))
    n_questions = len(get_qa_pairs(sample, exclude_adversarial=True))

    print(f"Model comparison: {SAMPLE_ID} ({n_sessions} sessions, {n_questions} questions)")
    print(f"Version: {VERSION}")
    print(f"Models: {', '.join(MODELS.keys())}")
    print(f"Query/Judge: {QUERY_MODEL}")
    print()

    base_dir = "runs/model-comparison"
    os.makedirs(base_dir, exist_ok=True)
    start = time.time()

    # ── Phase 1: Ingest with all models in parallel ─────────────────────
    print("=" * 60)
    print("PHASE 1: INGEST (all models in parallel)")
    print("=" * 60)

    ingest_results = {}
    with ThreadPoolExecutor(max_workers=len(MODELS)) as executor:
        futures = {
            executor.submit(ingest_with_model, key, sample, base_dir, VERSION): key
            for key in MODELS
        }
        pbar = tqdm(total=len(MODELS), desc="Ingesting", unit="model")
        for future in as_completed(futures):
            model_key, stats, memory_dir = future.result()
            ingest_results[model_key] = {
                "stats": stats,
                "memory_dir": memory_dir,
            }
            # Count files
            files = [f for f in os.listdir(memory_dir) if f.endswith(".md")]
            total_bytes = sum(os.path.getsize(os.path.join(memory_dir, f)) for f in files)
            pbar.set_description(f"Done: {model_key}")
            pbar.update(1)
            print(f"\n  {model_key}: {len(files)} files, {total_bytes:,} bytes, "
                  f"{stats.tool_calls} tools, {stats.total_tokens:,} tokens, "
                  f"{stats.elapsed_seconds:.0f}s")
            if stats.errors:
                print(f"    ERRORS: {stats.errors[:3]}")
        pbar.close()

    # ── Phase 2: Query each model's memory with GPT-4o-mini ─────────────
    print("\n" + "=" * 60)
    print("PHASE 2: QUERY (GPT-4o-mini on each model's memory)")
    print("=" * 60)

    for model_key in MODELS:
        memory_dir = ingest_results[model_key]["memory_dir"]
        results_dir = os.path.join(base_dir, f"results-{model_key}")
        os.makedirs(results_dir, exist_ok=True)

        print(f"\n  Querying with {model_key}'s memory...")
        query_dataset(
            dataset=[sample],
            base_memory_dir=os.path.dirname(memory_dir),
            output_dir=results_dir,
            provider="openai",
            model=QUERY_MODEL,
            sample_ids=[SAMPLE_ID],
            verbose=True,
            concurrency=CONCURRENCY,
            version=VERSION,
        )
        # Rename result file so evaluate finds it
        src = os.path.join(results_dir, f"{SAMPLE_ID}_results.json")
        if not os.path.exists(src):
            # query_dataset uses the subdir name as sample_id lookup
            # The memory_dir is base_dir/memory-{model_key}/{SAMPLE_ID} won't exist
            # We need to handle this - the memory is directly in memory-{model_key}/
            print(f"    Warning: results not found, checking memory structure...")

    # Fix: query_dataset expects memory at base_memory_dir/sample_id/
    # But we stored it at base_dir/memory-{model_key}/
    # Let me create symlinks
    print("\n  Fixing memory paths...")
    for model_key in MODELS:
        memory_dir = ingest_results[model_key]["memory_dir"]
        # Create a parent dir structure that query_dataset expects
        query_mem_base = os.path.join(base_dir, f"querymem-{model_key}")
        os.makedirs(query_mem_base, exist_ok=True)
        link_path = os.path.join(query_mem_base, SAMPLE_ID)
        if os.path.exists(link_path):
            os.remove(link_path) if os.path.islink(link_path) else shutil.rmtree(link_path)
        os.symlink(os.path.abspath(memory_dir), link_path)

    # Re-run queries with correct paths
    for model_key in MODELS:
        results_dir = os.path.join(base_dir, f"results-{model_key}")
        query_mem_base = os.path.join(base_dir, f"querymem-{model_key}")

        # Check if results already exist and are valid
        result_file = os.path.join(results_dir, f"{SAMPLE_ID}_results.json")
        if os.path.exists(result_file):
            with open(result_file) as f:
                existing = json.load(f)
            if len(existing) == n_questions and not any("[Error" in r["predicted"] for r in existing):
                print(f"  {model_key}: results already valid, skipping query")
                continue

        print(f"\n  Querying with {model_key}'s memory...")
        query_dataset(
            dataset=[sample],
            base_memory_dir=query_mem_base,
            output_dir=results_dir,
            provider="openai",
            model=QUERY_MODEL,
            sample_ids=[SAMPLE_ID],
            verbose=True,
            concurrency=CONCURRENCY,
            version=VERSION,
        )

    # ── Phase 3: Judge all ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PHASE 3: JUDGE")
    print("=" * 60)

    all_scores = {}
    for model_key in MODELS:
        results_dir = os.path.join(base_dir, f"results-{model_key}")
        eval_path = os.path.join(results_dir, "evaluation_report.json")

        print(f"\n  Judging {model_key}...")
        report = evaluate_dataset(
            results_dir=results_dir,
            output_path=eval_path,
            judge_model=JUDGE_MODEL,
            verbose=True,
            concurrency=CONCURRENCY,
        )

        overall = report.get("overall", {})
        o = overall.get("overall", overall)
        all_scores[model_key] = o

    # ── Summary ─────────────────────────────────────────────────────────
    total_time = time.time() - start

    print("\n" + "=" * 60)
    print("RESULTS COMPARISON")
    print("=" * 60)
    print(f"\n{'Model':>15s}  {'J-Score':>8s}  {'F1':>6s}  {'Files':>5s}  {'Memory':>8s}  {'Ingest Tokens':>14s}  {'Time':>6s}")
    print("-" * 75)

    for model_key in MODELS:
        o = all_scores.get(model_key, {})
        s = ingest_results[model_key]["stats"]
        memory_dir = ingest_results[model_key]["memory_dir"]
        files = [f for f in os.listdir(memory_dir) if f.endswith(".md")]
        total_bytes = sum(os.path.getsize(os.path.join(memory_dir, f)) for f in files)

        j = o.get("j_score", 0) * 100
        f1 = o.get("f1", 0) * 100
        print(f"{model_key:>15s}  {j:>7.1f}%  {f1:>5.1f}%  {len(files):>5d}  {total_bytes:>7,}B  {s.total_tokens:>14,}  {s.elapsed_seconds:>5.0f}s")

    print(f"\nTotal time: {total_time:.0f}s")

    # Save comparison report
    report = {
        "sample_id": SAMPLE_ID,
        "version": VERSION,
        "query_model": QUERY_MODEL,
        "judge_model": JUDGE_MODEL,
        "models": {},
    }
    for model_key in MODELS:
        o = all_scores.get(model_key, {})
        s = ingest_results[model_key]["stats"]
        memory_dir = ingest_results[model_key]["memory_dir"]
        files = [f for f in os.listdir(memory_dir) if f.endswith(".md")]

        report["models"][model_key] = {
            "provider": MODELS[model_key]["provider"],
            "model_id": MODELS[model_key]["model"],
            "j_score": o.get("j_score", 0),
            "f1": o.get("f1", 0),
            "bleu1": o.get("bleu1", 0),
            "num_files": len(files),
            "memory_bytes": sum(os.path.getsize(os.path.join(memory_dir, f)) for f in files),
            "ingest_tokens": s.total_tokens,
            "ingest_seconds": s.elapsed_seconds,
            "tool_calls": s.tool_calls,
        }

    with open(os.path.join(base_dir, "comparison_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {base_dir}/comparison_report.json")


if __name__ == "__main__":
    main()
