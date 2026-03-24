"""Evaluation: compute F1, BLEU-1, and J-score (LLM-as-judge) metrics.

Matches the LoCoMo benchmark methodology:
- F1: token-level precision/recall
- BLEU-1: unigram precision with brevity penalty
- J-score: GPT-4o-mini judges each answer as CORRECT or WRONG
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
from tqdm import tqdm

from .utils import normalize_answer

# ── Token-level F1 ──────────────────────────────────────────────────────────

def compute_f1(predicted: str, ground_truth: str) -> float:
    """Compute token-level F1 between predicted and ground truth answers."""
    pred_tokens = normalize_answer(predicted).split()
    truth_tokens = normalize_answer(ground_truth).split()

    if not pred_tokens and not truth_tokens:
        return 1.0
    if not pred_tokens or not truth_tokens:
        return 0.0

    common = Counter(pred_tokens) & Counter(truth_tokens)
    num_same = sum(common.values())

    if num_same == 0:
        return 0.0

    precision = num_same / len(pred_tokens)
    recall = num_same / len(truth_tokens)
    return 2 * precision * recall / (precision + recall)


# ── BLEU-1 ──────────────────────────────────────────────────────────────────

def compute_bleu1(predicted: str, ground_truth: str) -> float:
    """Compute BLEU-1 (unigram precision with brevity penalty)."""
    pred_tokens = normalize_answer(predicted).split()
    truth_tokens = normalize_answer(ground_truth).split()

    if not pred_tokens:
        return 0.0
    if not truth_tokens:
        return 0.0

    # Clipped unigram precision
    truth_counts = Counter(truth_tokens)
    pred_counts = Counter(pred_tokens)

    clipped = 0
    for token, count in pred_counts.items():
        clipped += min(count, truth_counts.get(token, 0))

    precision = clipped / len(pred_tokens)

    # Brevity penalty
    bp = 1.0
    if len(pred_tokens) < len(truth_tokens):
        bp = math.exp(1 - len(truth_tokens) / len(pred_tokens))

    return bp * precision


# ── J-score (LLM-as-Judge) ──────────────────────────────────────────────────

JUDGE_PROMPT = """\
Your task is to label an answer to a question as "CORRECT" or "WRONG".

You will be given:
- A question
- A gold (ground truth) answer
- A predicted answer

You should be generous with your grading — as long as the predicted answer touches on \
the same topic and conveys the same core information as the gold answer, it should be \
counted as CORRECT. Minor differences in phrasing, extra details, or slightly different \
wording are acceptable. For temporal questions, accept different date formats \
(e.g., "May 7th" vs "7 May") and relative references (e.g., "last Tuesday") as long as \
they refer to the same time.

Respond with a JSON object containing:
- "reasoning": a brief explanation of your judgment
- "label": either "CORRECT" or "WRONG"

Question: {question}
Gold answer: {gold_answer}
Predicted answer: {predicted_answer}
"""


def judge_answer(
    question: str,
    gold_answer: str,
    predicted_answer: str,
    model: str = "gpt-4o-mini",
) -> tuple[bool, str]:
    """Use an LLM to judge whether the predicted answer is correct.

    Returns (is_correct, reasoning).
    """
    client = openai.OpenAI()

    prompt = JUDGE_PROMPT.format(
        question=question,
        gold_answer=gold_answer,
        predicted_answer=predicted_answer,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        label = result.get("label", "WRONG").upper()
        reasoning = result.get("reasoning", "")
        return label == "CORRECT", reasoning
    except Exception as e:
        return False, f"Judge error: {e}"


# ── Aggregate evaluation ────────────────────────────────────────────────────

def _evaluate_one(r: dict, judge_model: str) -> dict:
    """Evaluate a single result. Used by ThreadPoolExecutor."""
    f1 = compute_f1(r["predicted"], r["ground_truth"])
    bleu = compute_bleu1(r["predicted"], r["ground_truth"])
    is_correct, reasoning = judge_answer(
        r["question"],
        r["ground_truth"],
        r["predicted"],
        model=judge_model,
    )
    return {
        **r,
        "f1": f1,
        "bleu1": bleu,
        "j_correct": is_correct,
        "j_reasoning": reasoning,
        "_index": r.get("_index", 0),
    }


def evaluate_results(
    results: list[dict],
    judge_model: str = "gpt-4o-mini",
    verbose: bool = True,
    concurrency: int = 1,
) -> dict:
    """Evaluate a list of query results with all three metrics.

    Args:
        results: List of dicts with "question", "predicted", "ground_truth", "category".
        judge_model: Model to use as judge for J-score.
        verbose: Show progress.
        concurrency: Number of parallel judge calls.

    Returns:
        Dict with overall and per-category metrics.
    """
    # Tag with index to preserve order
    for i, r in enumerate(results):
        r["_index"] = i

    if concurrency <= 1:
        # Sequential path
        evaluated = []
        iterator = tqdm(results, desc="Judging answers", disable=not verbose)
        for r in iterator:
            evaluated.append(_evaluate_one(r, judge_model))
        evaluated.sort(key=lambda r: r["_index"])
        for r in evaluated:
            del r["_index"]
        metrics = _aggregate_metrics(evaluated)
        metrics["evaluated_results"] = evaluated
        return metrics

    # Parallel path
    evaluated = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_evaluate_one, r, judge_model): r
            for r in results
        }
        pbar = tqdm(total=len(results), desc="Judging answers", disable=not verbose)
        for future in as_completed(futures):
            evaluated.append(future.result())
            pbar.update(1)
        pbar.close()

    evaluated.sort(key=lambda r: r["_index"])
    for r in evaluated:
        del r["_index"]
    # Clean up index tags from input
    for r in results:
        r.pop("_index", None)

    metrics = _aggregate_metrics(evaluated)
    metrics["evaluated_results"] = evaluated
    return metrics


def _aggregate_metrics(evaluated: list[dict]) -> dict:
    """Compute overall and per-category averages."""
    categories = set(r["category"] for r in evaluated)

    def avg_metrics(items):
        if not items:
            return {"f1": 0, "bleu1": 0, "j_score": 0, "count": 0}
        return {
            "f1": sum(r["f1"] for r in items) / len(items),
            "bleu1": sum(r["bleu1"] for r in items) / len(items),
            "j_score": sum(1 for r in items if r["j_correct"]) / len(items),
            "count": len(items),
        }

    overall = avg_metrics(evaluated)

    per_category = {}
    for cat in sorted(categories):
        cat_items = [r for r in evaluated if r["category"] == cat]
        per_category[cat] = avg_metrics(cat_items)

    return {
        "overall": overall,
        "per_category": per_category,
    }


def evaluate_dataset(
    results_dir: str,
    output_path: str,
    judge_model: str = "gpt-4o-mini",
    verbose: bool = True,
    concurrency: int = 1,
) -> dict:
    """Evaluate all result files in a directory.

    Uses a single progress bar across all conversations.
    """
    report = {"samples": {}, "overall": {}}

    # Load all results and tag with sample_id
    result_files = sorted(f for f in os.listdir(results_dir) if f.endswith("_results.json"))
    all_items = []
    for rf in result_files:
        sample_id = rf.replace("_results.json", "")
        with open(os.path.join(results_dir, rf)) as f:
            results = json.load(f)
        for i, r in enumerate(results):
            r["_sample_id"] = sample_id
            r["_index"] = i
            all_items.append(r)

    if not all_items:
        return report

    # Judge all items with a single progress bar
    correct_count = 0
    total_done = 0

    def _format_jscore():
        if total_done == 0:
            return "0.0%"
        return f"{correct_count / total_done * 100:.1f}%"

    if concurrency <= 1:
        evaluated = []
        pbar = tqdm(all_items, desc="Judging", disable=not verbose, unit="q")
        for r in pbar:
            result = _evaluate_one(r, judge_model)
            evaluated.append(result)
            total_done += 1
            if result["j_correct"]:
                correct_count += 1
            pbar.set_postfix(j_score=_format_jscore())
        pbar.close()
    else:
        evaluated = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_evaluate_one, r, judge_model): r for r in all_items}
            pbar = tqdm(total=len(all_items), desc="Judging", disable=not verbose, unit="q")
            for future in as_completed(futures):
                result = future.result()
                evaluated.append(result)
                total_done += 1
                if result["j_correct"]:
                    correct_count += 1
                pbar.update(1)
                pbar.set_postfix(j_score=_format_jscore())
            pbar.close()

    # Sort by original order and group by sample
    evaluated.sort(key=lambda r: (r["_sample_id"], r["_index"]))

    all_evaluated = []
    for r in evaluated:
        sid = r.pop("_sample_id")
        r.pop("_index")
        all_evaluated.append(r)
        report.setdefault("_by_sample", {}).setdefault(sid, []).append(r)

    # Per-sample metrics
    for sid, items in report.pop("_by_sample", {}).items():
        report["samples"][sid] = {
            "overall": _aggregate_metrics(items)["overall"],
            "per_category": _aggregate_metrics(items)["per_category"],
        }

    # Overall across all samples
    if all_evaluated:
        report["overall"] = _aggregate_metrics(all_evaluated)

    # Save reports
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    detail_path = output_path.replace(".json", "_detailed.json")
    with open(detail_path, "w") as f:
        json.dump(all_evaluated, f, indent=2)

    if verbose:
        overall = report["overall"]
        o = overall.get("overall", overall) if isinstance(overall.get("overall"), dict) else overall
        print(f"\n  J-score: {o['j_score']*100:.1f}%  F1: {o['f1']*100:.1f}%  "
              f"BLEU-1: {o['bleu1']*100:.1f}%  ({o['count']} questions)")

    return report
