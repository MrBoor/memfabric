"""Query phase: answer benchmark questions using MemFabric memory retrieval.

For each question, the LLM uses memory tools (list_memories, read_memory)
to find relevant context, then produces a final text answer.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from .agent_loop import LoopStats, run_anthropic_loop, run_openai_loop
from .memfabric import MemFabricLocal
from .utils import get_qa_pairs, normalize_category
from .versions import get_version


def query_single(
    question: str,
    memory_dir: str,
    provider: str = "anthropic",
    model: str | None = None,
    version: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[str, LoopStats]:
    """Answer a single question using MemFabric memory.

    Returns (answer_text, stats).
    """
    if model is None:
        model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o-mini"

    v = get_version(version)
    memfabric = MemFabricLocal(memory_dir)

    if provider == "anthropic":
        messages = [{"role": "user", "content": question}]
        return run_anthropic_loop(
            messages=messages,
            system=v.query_prompt,
            memfabric=memfabric,
            model=model,
            max_turns=10,
            version=version,
        )
    else:
        messages = [
            {"role": "system", "content": v.query_prompt},
            {"role": "user", "content": question},
        ]
        return run_openai_loop(
            messages=messages,
            memfabric=memfabric,
            model=model,
            max_turns=10,
            version=version,
            base_url=base_url,
            api_key=api_key,
        )


def _query_one(qa: dict, memory_dir: str, provider: str, model: str, version: str | None = None) -> dict:
    """Process a single QA pair. Used by ThreadPoolExecutor."""
    question = qa["question"]
    ground_truth = qa["answer"]
    category = normalize_category(qa.get("category", "unknown"))

    answer, stats = query_single(
        question=question,
        memory_dir=memory_dir,
        provider=provider,
        model=model,
        version=version,
    )

    return {
        "question": question,
        "predicted": answer,
        "ground_truth": ground_truth,
        "category": category,
        "evidence": qa.get("evidence", []),
        "stats": {
            "input_tokens": stats.input_tokens,
            "output_tokens": stats.output_tokens,
            "total_tokens": stats.total_tokens,
            "tool_calls": stats.tool_calls,
            "llm_calls": stats.llm_calls,
            "elapsed_seconds": stats.elapsed_seconds,
        },
        "_index": qa["_index"],
        "_sample_id": qa["_sample_id"],
    }


def query_dataset(
    dataset: list[dict],
    base_memory_dir: str,
    output_dir: str,
    provider: str = "anthropic",
    model: str | None = None,
    sample_ids: list[str] | None = None,
    exclude_adversarial: bool = True,
    verbose: bool = True,
    concurrency: int = 1,
    version: str | None = None,
) -> dict[str, list[dict]]:
    """Run queries for all (or selected) conversations.

    Saves results to output_dir as JSON files.
    Returns dict mapping sample_id -> list of result dicts.
    """
    if model is None:
        model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o-mini"

    # Gather all QA pairs across conversations
    all_tasks = []  # (sample_id, memory_dir, qa_with_index)
    for sample in dataset:
        sample_id = sample.get("sample_id", "unknown")
        if sample_ids and sample_id not in sample_ids:
            continue

        memory_dir = os.path.join(base_memory_dir, sample_id)
        if not os.path.exists(memory_dir):
            if verbose:
                print(f"Warning: No memory directory for {sample_id}, skipping.")
            continue

        qa_pairs = get_qa_pairs(sample, exclude_adversarial=exclude_adversarial)
        for i, qa in enumerate(qa_pairs):
            qa["_index"] = i
            qa["_sample_id"] = sample_id
            all_tasks.append((sample_id, memory_dir, qa))

    if not all_tasks:
        return {}

    # Run all queries with a single progress bar
    results_by_sample = {}
    pbar = tqdm(total=len(all_tasks), desc="Querying", disable=not verbose, unit="q")

    if concurrency <= 1:
        for sample_id, memory_dir, qa in all_tasks:
            pbar.set_description(f"Querying {sample_id}")
            result = _query_one(qa, memory_dir, provider, model, version)
            results_by_sample.setdefault(sample_id, []).append(result)
            pbar.update(1)
            pbar.set_postfix(tokens=result["stats"]["total_tokens"])
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for sample_id, memory_dir, qa in all_tasks:
                future = executor.submit(_query_one, qa, memory_dir, provider, model, version)
                futures[future] = sample_id

            for future in as_completed(futures):
                result = future.result()
                sid = result["_sample_id"]
                results_by_sample.setdefault(sid, []).append(result)
                pbar.update(1)
                pbar.set_description(f"Querying {sid}")
                pbar.set_postfix(tokens=result["stats"]["total_tokens"])

    pbar.close()

    # Sort each conversation's results by original index, save, clean up
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
        print(f"  Query complete: {total_q} questions, {total_tokens:,} tokens")

    return all_results
