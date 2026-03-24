#!/usr/bin/env python3
"""Main entry point for the MemFabric LoCoMo benchmark.

Usage:
    # Full benchmark (ingest + query + evaluate)
    python run_benchmark.py --data data/locomo10.json

    # Individual phases
    python run_benchmark.py --phase ingest --data data/locomo10.json
    python run_benchmark.py --phase query --data data/locomo10.json
    python run_benchmark.py --phase evaluate

    # Single conversation (defaults to conv-26)
    python run_benchmark.py --single
    python run_benchmark.py --single --samples conv-42  # override default

    # Custom models
    python run_benchmark.py --data data/locomo10.json --ingest-model claude-sonnet-4-20250514 --query-model gpt-4o-mini

    # Full-context baseline (no memory system)
    python run_benchmark.py --baseline --data data/locomo10.json --samples conv-26
    python run_benchmark.py --baseline --data data/locomo10.json --query-model gpt-4o-mini
"""

import argparse
import json
import os
import sys
import time

from src.baseline import run_baseline_dataset
from src.evaluate import evaluate_dataset, evaluate_results
from src.ingest import ingest_all
from src.query import query_dataset
from src.utils import load_dataset
from src.versions import get_version, list_versions, LATEST_VERSION


def main():
    parser = argparse.ArgumentParser(description="MemFabric LoCoMo Benchmark")
    parser.add_argument("--data", default="data/locomo10.json", help="Path to LoCoMo dataset JSON")
    parser.add_argument(
        "--phase",
        choices=["ingest", "query", "evaluate", "all"],
        default="all",
        help="Which phase to run (default: all)",
    )
    parser.add_argument("--ingest-provider", default="anthropic", choices=["anthropic", "openai"], help="LLM provider for ingest")
    parser.add_argument("--query-provider", default="openai", choices=["anthropic", "openai"], help="LLM provider for query")
    parser.add_argument("--ingest-model", default="claude-haiku-4-5-20251001", help="Model for ingestion phase")
    parser.add_argument("--query-model", default="gpt-4o-mini", help="Model for query phase")
    parser.add_argument("--judge-model", default="gpt-4o-mini", help="Model for J-score judging")
    parser.add_argument("--samples", nargs="*", default=None, help="Specific sample IDs to process (default: all)")
    parser.add_argument("--single", action="store_true", help="Run on a single conversation only (default: conv-26)")
    parser.add_argument("--memory-dir", default="memory", help="Base directory for memory files")
    parser.add_argument("--snapshot-dir", default="memory_snapshots", help="Directory to snapshot memory state")
    parser.add_argument("--results-dir", default="results", help="Directory for query results")
    parser.add_argument("--baseline", action="store_true", help="Run full-context baseline instead of MemFabric")
    parser.add_argument("--version", default=None, help=f"MemFabric tool version (default: {LATEST_VERSION})")
    parser.add_argument("--list-versions", action="store_true", help="List available versions and exit")
    parser.add_argument("--concurrency", type=int, default=10, help="Parallel API calls for query/judge (default: 10)")
    parser.add_argument("--include-adversarial", action="store_true", help="Include adversarial questions")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()

    if args.list_versions:
        for v in list_versions():
            print(f"  {v['version']:6s}  {v['description']}")
        return

    verbose = not args.quiet

    DEFAULT_SINGLE_CONV = "conv-26"
    if args.single and not args.samples:
        args.samples = [DEFAULT_SINGLE_CONV]

    # Load dataset
    dataset = None
    needs_data = args.baseline or args.phase in ("ingest", "query", "all")
    if needs_data:
        if not os.path.exists(args.data):
            print(f"Error: Dataset not found at {args.data}")
            print("Download the LoCoMo dataset and place it in the data/ directory.")
            print("See: https://huggingface.co/datasets/Percena/locomo-mc10")
            sys.exit(1)
        dataset = load_dataset(args.data)
        if verbose:
            print(f"Loaded {len(dataset)} conversations from {args.data}")

    start_time = time.time()
    v = get_version(args.version)
    report = {"config": vars(args), "memfabric_version": v.metadata()}

    # ── Baseline mode ──────────────────────────────────────────────────────
    if args.baseline:
        if verbose:
            print("\n" + "=" * 60)
            print("FULL-CONTEXT BASELINE")
            print("=" * 60)

        all_results = run_baseline_dataset(
            dataset=dataset,
            output_dir=args.results_dir,
            model=args.query_model,
            sample_ids=args.samples,
            exclude_adversarial=not args.include_adversarial,
            verbose=verbose,
            concurrency=args.concurrency,
        )

        report["baseline_query"] = {}
        for sid, results in all_results.items():
            tokens = sum(r["stats"]["total_tokens"] for r in results)
            report["baseline_query"][sid] = {
                "num_questions": len(results),
                "total_tokens": tokens,
                "avg_tokens_per_query": tokens / len(results) if results else 0,
            }

        # Auto-evaluate
        if verbose:
            print("\n" + "=" * 60)
            print("EVALUATE BASELINE")
            print("=" * 60)

        eval_report_path = os.path.join(args.results_dir, "evaluation_report.json")
        eval_report = evaluate_dataset(
            results_dir=args.results_dir,
            output_path=eval_report_path,
            judge_model=args.judge_model,
            verbose=verbose,
            concurrency=args.concurrency,
        )
        report["evaluation"] = {
            "overall": eval_report.get("overall", {}),
            "samples": eval_report.get("samples", {}),
        }

        total_time = time.time() - start_time
        report["total_elapsed_seconds"] = total_time
        report_path = os.path.join(args.results_dir, "benchmark_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        if verbose:
            print(f"\n{'='*60}")
            print(f"Baseline complete in {total_time:.1f}s")
            print(f"Report saved to: {report_path}")
            overall = report["evaluation"].get("overall", {})
            o = overall.get("overall", overall) if isinstance(overall.get("overall"), dict) else overall
            if o:
                print(f"\nFINAL SCORES:")
                print(f"  J-score: {o.get('j_score', 0)*100:.1f}%")
                print(f"  F1:      {o.get('f1', 0)*100:.1f}%")
                print(f"  BLEU-1:  {o.get('bleu1', 0)*100:.1f}%")

        return

    run_ingest = args.phase in ("ingest", "all")
    run_query = args.phase in ("query", "all")
    run_evaluate = args.phase in ("evaluate", "all")

    # ── Phase 1: Ingest ─────────────────────────────────────────────────────
    if run_ingest:
        if verbose:
            print("\n" + "=" * 60)
            print("PHASE 1: INGEST")
            print("=" * 60)

        ingest_stats = ingest_all(
            dataset=dataset,
            base_memory_dir=args.memory_dir,
            snapshot_dir=args.snapshot_dir,
            provider=args.ingest_provider,
            model=args.ingest_model,
            sample_ids=args.samples,
            verbose=verbose,
            version=args.version,
            concurrency=min(args.concurrency, 3),
        )

        report["ingest"] = {
            sid: {
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.total_tokens,
                "tool_calls": s.tool_calls,
                "llm_calls": s.llm_calls,
                "elapsed_seconds": s.elapsed_seconds,
                "errors": s.errors,
            }
            for sid, s in ingest_stats.items()
        }

    # ── Phase 2: Query ──────────────────────────────────────────────────────
    if run_query:
        if verbose:
            print("\n" + "=" * 60)
            print("PHASE 2: QUERY")
            print("=" * 60)

        all_results = query_dataset(
            dataset=dataset,
            base_memory_dir=args.memory_dir,
            output_dir=args.results_dir,
            provider=args.query_provider,
            model=args.query_model,
            sample_ids=args.samples,
            exclude_adversarial=not args.include_adversarial,
            verbose=verbose,
            concurrency=args.concurrency,
            version=args.version,
        )

        # Aggregate query stats
        report["query"] = {}
        for sid, results in all_results.items():
            tokens = sum(r["stats"]["total_tokens"] for r in results)
            report["query"][sid] = {
                "num_questions": len(results),
                "total_tokens": tokens,
                "avg_tokens_per_query": tokens / len(results) if results else 0,
            }

    # ── Phase 3: Evaluate ───────────────────────────────────────────────────
    if run_evaluate:
        if verbose:
            print("\n" + "=" * 60)
            print("PHASE 3: EVALUATE")
            print("=" * 60)

        eval_report_path = os.path.join(args.results_dir, "evaluation_report.json")
        eval_report = evaluate_dataset(
            results_dir=args.results_dir,
            output_path=eval_report_path,
            judge_model=args.judge_model,
            verbose=verbose,
            concurrency=args.concurrency,
        )
        report["evaluation"] = {
            "overall": eval_report.get("overall", {}),
            "samples": {
                sid: data
                for sid, data in eval_report.get("samples", {}).items()
            },
        }

    # ── Summary ─────────────────────────────────────────────────────────────
    total_time = time.time() - start_time
    report["total_elapsed_seconds"] = total_time

    report_path = os.path.join(args.results_dir, "benchmark_report.json")
    os.makedirs(args.results_dir, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Benchmark complete in {total_time:.1f}s")
        print(f"Report saved to: {report_path}")

        if "evaluation" in report and "overall" in report["evaluation"]:
            overall = report["evaluation"]["overall"]
            # _aggregate_metrics nests as {"overall": {...}, "per_category": {...}}
            o = overall.get("overall", overall) if isinstance(overall.get("overall"), dict) else overall
            print(f"\nFINAL SCORES:")
            print(f"  J-score: {o.get('j_score', 0)*100:.1f}%")
            print(f"  F1:      {o.get('f1', 0)*100:.1f}%")
            print(f"  BLEU-1:  {o.get('bleu1', 0)*100:.1f}%")


if __name__ == "__main__":
    main()
