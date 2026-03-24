"""Ingest phase: process conversations session-by-session into MemFabric memory files.

For each session, the LLM reads the dialogue and decides what to remember,
creating/updating memory files with descriptive names.

Sessions within a conversation are sequential (each builds on previous memory),
but multiple conversations can be ingested in parallel.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from .agent_loop import LoopStats, run_anthropic_loop, run_openai_loop
from .memfabric import MemFabricLocal
from .utils import format_session_text, get_sessions
from .versions import get_version

INGEST_SYSTEM_PROMPT = """\
You are a memory management agent. You are processing a conversation between two people, \
one session at a time. Your job is to extract and store important information from each session \
into memory files.

You have access to memory tools: list_memories, read_memory, remember, update_memory, and reorganize.

Guidelines:
- Store facts, preferences, events, plans, relationships, opinions, and any details that might \
be useful for answering questions about these people later.
- Use descriptive kebab-case filenames that capture the topic. Examples: \
"audrey-career-and-work", "andrew-health-updates", "shared-travel-plans", \
"audrey-hobbies-and-interests", "relationship-dynamics".
- Before creating a new file, call list_memories to check if a relevant file already exists. \
If so, append to it with remember rather than creating a duplicate.
- Include dates when available — they matter for temporal questions.
- Extract BOTH speakers' information — don't focus on just one person.
- Capture specific details: names, places, dates, amounts, opinions, plans.
- If information contradicts what you previously stored, use update_memory to correct it.
- After processing several sessions, consider using reorganize to keep files focused and well-named.

Remember: the filenames are the primary retrieval mechanism. Someone will later look at \
the list of filenames to decide which files contain the answer to a question. \
Make filenames specific and descriptive.
"""


def ingest_conversation(
    sample: dict,
    memory_dir: str,
    provider: str = "anthropic",
    model: str | None = None,
    pbar: tqdm | None = None,
    pbar_lock: threading.Lock | None = None,
    version: str | None = None,
) -> LoopStats:
    """Process a conversation's sessions into MemFabric memory files.

    Sessions are processed sequentially (each builds on previous memory).
    """
    if model is None:
        model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o-mini"

    v = get_version(version)
    memfabric = MemFabricLocal(memory_dir)
    conversation = sample["conversation"]
    speaker_a = conversation.get("speaker_a", "Speaker A")
    speaker_b = conversation.get("speaker_b", "Speaker B")
    sessions = get_sessions(conversation)
    sample_id = sample.get("sample_id", "unknown")

    total_stats = LoopStats()

    for session_key, dt, turns in sessions:
        session_text = format_session_text(session_key, dt, turns, speaker_a, speaker_b)

        user_msg = (
            f"Process the following conversation session and store important information "
            f"in memory. The conversation is between {speaker_a} and {speaker_b}.\n\n"
            f"{session_text}"
        )

        if provider == "anthropic":
            messages = [{"role": "user", "content": user_msg}]
            _, stats = run_anthropic_loop(
                messages=messages,
                system=v.ingest_prompt,
                memfabric=memfabric,
                model=model,
                version=version,
            )
        else:
            messages = [
                {"role": "system", "content": v.ingest_prompt},
                {"role": "user", "content": user_msg},
            ]
            _, stats = run_openai_loop(
                messages=messages,
                memfabric=memfabric,
                model=model,
                version=version,
            )

        total_stats.input_tokens += stats.input_tokens
        total_stats.output_tokens += stats.output_tokens
        total_stats.tool_calls += stats.tool_calls
        total_stats.llm_calls += stats.llm_calls
        total_stats.elapsed_seconds += stats.elapsed_seconds
        total_stats.errors.extend(stats.errors)

        if pbar is not None:
            if pbar_lock:
                with pbar_lock:
                    pbar.update(1)
                    pbar.set_description(f"Ingesting {sample_id}")
                    pbar.set_postfix(tools=total_stats.tool_calls, tokens=total_stats.total_tokens)
            else:
                pbar.update(1)
                pbar.set_postfix(tools=total_stats.tool_calls, tokens=total_stats.total_tokens)

    return total_stats


def _ingest_one_conversation(
    sample: dict,
    base_memory_dir: str,
    snapshot_dir: str | None,
    provider: str,
    model: str | None,
    version: str | None,
    pbar: tqdm | None,
    pbar_lock: threading.Lock | None,
) -> tuple[str, LoopStats]:
    """Ingest a single conversation. Used by ThreadPoolExecutor."""
    sample_id = sample.get("sample_id", "unknown")

    memory_dir = os.path.join(base_memory_dir, sample_id)
    if os.path.exists(memory_dir):
        shutil.rmtree(memory_dir)
    os.makedirs(memory_dir)

    stats = ingest_conversation(
        sample=sample,
        memory_dir=memory_dir,
        provider=provider,
        model=model,
        pbar=pbar,
        pbar_lock=pbar_lock,
        version=version,
    )

    if snapshot_dir:
        snap_path = os.path.join(snapshot_dir, sample_id)
        if os.path.exists(snap_path):
            shutil.rmtree(snap_path)
        shutil.copytree(memory_dir, snap_path)

    return sample_id, stats


def ingest_all(
    dataset: list[dict],
    base_memory_dir: str,
    snapshot_dir: str | None = None,
    provider: str = "anthropic",
    model: str | None = None,
    sample_ids: list[str] | None = None,
    verbose: bool = True,
    version: str | None = None,
    concurrency: int = 3,
) -> dict:
    """Ingest all (or selected) conversations.

    Sessions within each conversation are sequential, but multiple
    conversations are ingested in parallel (default: 3 concurrent).
    """
    all_stats = {}

    samples = []
    for sample in dataset:
        sample_id = sample.get("sample_id", "unknown")
        if sample_ids and sample_id not in sample_ids:
            continue
        samples.append(sample)

    total_sessions = sum(len(get_sessions(s["conversation"])) for s in samples)
    pbar = tqdm(total=total_sessions, desc="Ingesting", disable=not verbose, unit="session")
    pbar_lock = threading.Lock()

    if concurrency <= 1 or len(samples) <= 1:
        for sample in samples:
            sample_id, stats = _ingest_one_conversation(
                sample, base_memory_dir, snapshot_dir, provider, model, version, pbar, None
            )
            all_stats[sample_id] = stats
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    _ingest_one_conversation,
                    sample, base_memory_dir, snapshot_dir, provider, model, version, pbar, pbar_lock
                ): sample
                for sample in samples
            }
            for future in as_completed(futures):
                sample_id, stats = future.result()
                all_stats[sample_id] = stats

    pbar.close()

    if verbose:
        total_tokens = sum(s.total_tokens for s in all_stats.values())
        total_tools = sum(s.tool_calls for s in all_stats.values())
        print(f"  Ingest complete: {len(all_stats)} conversations, {total_sessions} sessions, "
              f"{total_tools} tool calls, {total_tokens:,} tokens")

    return all_stats
