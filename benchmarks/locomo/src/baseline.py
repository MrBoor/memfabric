"""Full-context baseline: dump the entire conversation into the LLM context.

No memory system — just feed the full conversation + question to the LLM
and let it answer directly. This establishes the baseline that MemFabric
needs to beat.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
from tqdm import tqdm

from .utils import (
    format_session_text,
    get_qa_pairs,
    get_sessions,
    normalize_category,
)

BASELINE_SYSTEM_PROMPT = """\
You are answering questions about a conversation between two people. \
The full conversation history is provided below. Answer each question \
concisely and directly (1-3 sentences) based on what you find in the conversation. \
If the answer is not in the conversation, say so honestly. Do not make up information.
"""


def build_full_conversation_text(sample: dict) -> str:
    """Build the full conversation text from all sessions."""
    conv = sample["conversation"]
    speaker_a = conv.get("speaker_a", "Speaker A")
    speaker_b = conv.get("speaker_b", "Speaker B")
    sessions = get_sessions(conv)

    parts = []
    for key, dt, turns in sessions:
        parts.append(format_session_text(key, dt, turns, speaker_a, speaker_b))

    return "\n\n".join(parts)


def query_baseline(
    question: str,
    conversation_text: str,
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
) -> tuple[str, dict]:
    """Answer a question using the full conversation context.

    Returns (answer, stats).
    """
    client = openai.OpenAI()
    start = time.time()

    messages = [
        {"role": "system", "content": BASELINE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Here is the full conversation:\n\n"
                f"{conversation_text}\n\n"
                f"Question: {question}"
            ),
        },
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        answer = response.choices[0].message.content or ""
        usage = response.usage
        stats = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.prompt_tokens + usage.completion_tokens,
            "elapsed_seconds": time.time() - start,
        }
    except Exception as e:
        answer = f"[Error: {e}]"
        stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "elapsed_seconds": time.time() - start,
        }

    return answer, stats


def _baseline_one(qa: dict, conversation_text: str, model: str) -> dict:
    """Process a single QA pair for baseline. Used by ThreadPoolExecutor."""
    question = qa["question"]
    ground_truth = qa["answer"]
    category = normalize_category(qa.get("category", "unknown"))

    answer, stats = query_baseline(question, conversation_text, model=model)

    return {
        "question": question,
        "predicted": answer,
        "ground_truth": ground_truth,
        "category": category,
        "evidence": qa.get("evidence", []),
        "stats": stats,
        "_index": qa["_index"],
        "_sample_id": qa["_sample_id"],
    }


def run_baseline_dataset(
    dataset: list[dict],
    output_dir: str,
    model: str = "gpt-4o-mini",
    sample_ids: list[str] | None = None,
    exclude_adversarial: bool = True,
    verbose: bool = True,
    concurrency: int = 1,
) -> dict[str, list[dict]]:
    """Run full-context baseline for all (or selected) conversations.

    Uses a single progress bar across all conversations.
    """
    # Gather all tasks
    all_tasks = []
    for sample in dataset:
        sample_id = sample.get("sample_id", "unknown")
        if sample_ids and sample_id not in sample_ids:
            continue

        conversation_text = build_full_conversation_text(sample)
        qa_pairs = get_qa_pairs(sample, exclude_adversarial=exclude_adversarial)
        for i, qa in enumerate(qa_pairs):
            qa["_index"] = i
            qa["_sample_id"] = sample_id
            all_tasks.append((qa, conversation_text, model))

    if not all_tasks:
        return {}

    # Run with single progress bar
    results_by_sample = {}
    pbar = tqdm(total=len(all_tasks), desc="Baseline", disable=not verbose, unit="q")

    if concurrency <= 1:
        for qa, conv_text, mdl in all_tasks:
            pbar.set_description(f"Baseline {qa['_sample_id']}")
            result = _baseline_one(qa, conv_text, mdl)
            results_by_sample.setdefault(qa["_sample_id"], []).append(result)
            pbar.update(1)
            pbar.set_postfix(tokens=result["stats"]["total_tokens"])
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_baseline_one, qa, conv_text, mdl): qa
                for qa, conv_text, mdl in all_tasks
            }
            for future in as_completed(futures):
                result = future.result()
                sid = result["_sample_id"]
                results_by_sample.setdefault(sid, []).append(result)
                pbar.update(1)
                pbar.set_description(f"Baseline {sid}")
                pbar.set_postfix(tokens=result["stats"]["total_tokens"])

    pbar.close()

    # Sort, save, clean up
    all_results = {}
    os.makedirs(output_dir, exist_ok=True)
    for sample_id, results in sorted(results_by_sample.items()):
        results.sort(key=lambda r: r["_index"])
        for r in results:
            del r["_index"]
            del r["_sample_id"]
        all_results[sample_id] = results

        out_path = os.path.join(output_dir, f"{sample_id}_results.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)

    if verbose:
        total_tokens = sum(r["stats"]["total_tokens"] for res in all_results.values() for r in res)
        total_q = sum(len(res) for res in all_results.values())
        print(f"  Baseline complete: {total_q} questions, {total_tokens:,} tokens")

    return all_results
