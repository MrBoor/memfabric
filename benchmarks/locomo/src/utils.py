"""Utility functions for loading data and formatting conversations."""

import json
import re


def load_dataset(path: str) -> list[dict]:
    """Load the LoCoMo dataset from JSON."""
    with open(path) as f:
        data = json.load(f)
    # Handle both list and dict formats
    if isinstance(data, dict):
        return list(data.values()) if not any(k.startswith("sample") for k in data) else [data]
    return data


def get_sessions(conversation: dict) -> list[tuple[str, str, list[dict]]]:
    """Extract ordered sessions from a conversation.

    Returns list of (session_key, datetime_str, turns).
    """
    sessions = []
    i = 1
    while f"session_{i}" in conversation:
        key = f"session_{i}"
        dt_key = f"session_{i}_date_time"
        dt = conversation.get(dt_key, "")
        turns = conversation[key]
        sessions.append((key, dt, turns))
        i += 1
    return sessions


def format_session_text(
    session_key: str,
    datetime_str: str,
    turns: list[dict],
    speaker_a: str,
    speaker_b: str,
) -> str:
    """Format a session's turns into readable text for the LLM."""
    lines = []
    session_num = session_key.replace("session_", "")
    if datetime_str:
        lines.append(f"[Session {session_num} — {datetime_str}]")
    else:
        lines.append(f"[Session {session_num}]")
    lines.append("")

    for turn in turns:
        speaker = turn.get("speaker", "Unknown")
        text = turn.get("text", "")
        lines.append(f"{speaker}: {text}")

    return "\n".join(lines)


def get_qa_pairs(sample: dict, exclude_adversarial: bool = True) -> list[dict]:
    """Extract QA pairs from a sample, optionally excluding adversarial ones.

    LoCoMo categories:
      1 = single-hop
      2 = multi-hop
      3 = temporal
      4 = open-domain (commonsense/world knowledge)
      5 = adversarial
    """
    qa_list = sample.get("qa", [])
    if exclude_adversarial:
        qa_list = [q for q in qa_list if normalize_category(q.get("category", "")) != "adversarial"]
    return qa_list


CATEGORY_MAP = {
    "1": "single-hop",
    "2": "multi-hop",
    "3": "temporal",
    "4": "open-domain",
    "5": "adversarial",
    "single-hop": "single-hop",
    "single_hop": "single-hop",
    "multi-hop": "multi-hop",
    "multi_hop": "multi-hop",
    "multihop": "multi-hop",
    "temporal": "temporal",
    "open-domain": "open-domain",
    "open_domain": "open-domain",
    "opendomian": "open-domain",
    "adversarial": "adversarial",
}


def normalize_category(cat: str) -> str:
    """Normalize question category to a standard name."""
    cat = str(cat).strip().lower()
    return CATEGORY_MAP.get(cat, cat)


def normalize_answer(text) -> str:
    """Normalize an answer for token-level metric computation."""
    text = str(text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
