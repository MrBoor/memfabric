#!/usr/bin/env python3
"""Quick test: ingest 3 sessions, answer 5 questions, evaluate."""

from __future__ import annotations

import json
import os
import shutil

from src.memfabric import MemFabricLocal
from src.agent_loop import run_anthropic_loop, run_openai_loop
from src.ingest import INGEST_SYSTEM_PROMPT
from src.versions import get_version
from src.evaluate import compute_f1, compute_bleu1, judge_answer
from src.utils import load_dataset, get_sessions, format_session_text, get_qa_pairs, normalize_category

# Set OPENAI_API_KEY and ANTHROPIC_API_KEY env vars before running

MEMORY_DIR = "memory/test_run"
INGEST_MODEL = "claude-haiku-4-5-20251001"
QUERY_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
NUM_SESSIONS = 3
NUM_QUESTIONS = 5
QUERY_SYSTEM_PROMPT = get_version().query_prompt


def main():
    # Clean up
    if os.path.exists(MEMORY_DIR):
        shutil.rmtree(MEMORY_DIR)
    os.makedirs(MEMORY_DIR)

    # Load data
    data = load_dataset("data/locomo10.json")
    # conv-26 is the default single-conversation eval target
    sample = next(s for s in data if s["sample_id"] == "conv-26")
    conv = sample["conversation"]
    speaker_a = conv["speaker_a"]
    speaker_b = conv["speaker_b"]
    sessions = get_sessions(conv)

    print(f"Sample: {sample['sample_id']} ({speaker_a} & {speaker_b})")
    print(f"Total sessions: {len(sessions)}, using first {NUM_SESSIONS}")
    print()

    # ── INGEST ──────────────────────────────────────────────────────────
    print("=" * 50)
    print("PHASE 1: INGEST")
    print("=" * 50)

    memfabric = MemFabricLocal(MEMORY_DIR)
    total_ingest_tokens = 0

    for session_key, dt, turns in sessions[:NUM_SESSIONS]:
        session_text = format_session_text(session_key, dt, turns, speaker_a, speaker_b)
        print(f"\nIngesting {session_key} ({dt})...")

        user_msg = (
            f"Process the following conversation session and store important "
            f"information in memory. The conversation is between {speaker_a} "
            f"and {speaker_b}.\n\n{session_text}"
        )
        messages = [{"role": "user", "content": user_msg}]
        _, stats = run_anthropic_loop(
            messages=messages, system=INGEST_SYSTEM_PROMPT, memfabric=memfabric, model=INGEST_MODEL
        )
        total_ingest_tokens += stats.total_tokens
        print(f"  {stats.tool_calls} tool calls, {stats.total_tokens} tokens, {stats.elapsed_seconds:.1f}s")

    # Show memory files
    print(f"\nMemory files created:")
    for f in sorted(os.listdir(MEMORY_DIR)):
        if f.endswith(".md"):
            size = os.path.getsize(os.path.join(MEMORY_DIR, f))
            print(f"  {f} ({size} bytes)")

    # ── QUERY ───────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("PHASE 2: QUERY")
    print("=" * 50)

    qa_pairs = get_qa_pairs(sample, exclude_adversarial=True)[:NUM_QUESTIONS]
    results = []
    total_query_tokens = 0

    for i, qa in enumerate(qa_pairs):
        q = qa["question"]
        gt = qa["answer"]
        cat = normalize_category(qa["category"])
        print(f"\nQ{i+1} [{cat}]: {q}")
        print(f"  Gold: {gt}")

        messages = [
            {"role": "system", "content": QUERY_SYSTEM_PROMPT},
            {"role": "user", "content": q},
        ]
        answer, stats = run_openai_loop(
            messages=messages, memfabric=MemFabricLocal(MEMORY_DIR), model=QUERY_MODEL
        )
        total_query_tokens += stats.total_tokens
        print(f"  Pred: {answer[:200]}")
        print(f"  ({stats.tool_calls} tools, {stats.total_tokens} tokens, {stats.elapsed_seconds:.1f}s)")

        results.append({"question": q, "predicted": answer, "ground_truth": gt, "category": cat})

    # ── EVALUATE ────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("PHASE 3: EVALUATE")
    print("=" * 50)

    for r in results:
        r["f1"] = compute_f1(r["predicted"], r["ground_truth"])
        r["bleu1"] = compute_bleu1(r["predicted"], r["ground_truth"])
        is_correct, reasoning = judge_answer(r["question"], r["ground_truth"], r["predicted"], JUDGE_MODEL)
        r["j_correct"] = is_correct
        r["j_reasoning"] = reasoning
        verdict = "CORRECT" if is_correct else "WRONG"
        print(f"\n  Q: {r['question'][:80]}")
        print(f"  F1={r['f1']:.2f}  BLEU={r['bleu1']:.2f}  Judge={verdict}")
        print(f"  Reasoning: {reasoning[:120]}")

    # Summary
    n = len(results)
    avg_f1 = sum(r["f1"] for r in results) / n
    avg_bleu = sum(r["bleu1"] for r in results) / n
    j_score = sum(1 for r in results if r["j_correct"]) / n

    print(f"\n{'='*50}")
    print(f"SUMMARY ({n} questions, {NUM_SESSIONS} sessions)")
    print(f"{'='*50}")
    print(f"  J-score:  {j_score*100:.0f}%")
    print(f"  F1:       {avg_f1*100:.1f}%")
    print(f"  BLEU-1:   {avg_bleu*100:.1f}%")
    print(f"  Ingest tokens: {total_ingest_tokens}")
    print(f"  Query tokens:  {total_query_tokens}")
    print(f"  Total tokens:  {total_ingest_tokens + total_query_tokens}")


if __name__ == "__main__":
    main()
