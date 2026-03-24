"""Generic agentic loop: LLM <-> tool calls until final text answer.

Supports both Anthropic (Claude) and OpenAI APIs for the LLM.
Tool calls are dispatched to a MemFabricLocal instance.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import anthropic
import openai

from .memfabric import MemFabricLocal
from .versions import get_version


@dataclass
class LoopStats:
    """Tracks token usage and latency for a single agent loop run."""

    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def run_anthropic_loop(
    messages: list[dict],
    system: str,
    memfabric: MemFabricLocal,
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 20,
    temperature: float = 0.0,
    version: str | None = None,
) -> tuple[str, LoopStats]:
    """Run an agentic loop with Claude, dispatching tool calls to MemFabric.

    Returns (final_text_answer, stats).
    """
    client = anthropic.Anthropic()
    stats = LoopStats()
    start = time.time()

    # Get tool schemas from versioned definitions
    tool_defs = get_version(version).tools
    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in tool_defs
    ]

    for _ in range(max_turns):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=tools,
                temperature=temperature,
            )
        except Exception as e:
            stats.errors.append(str(e))
            break

        stats.llm_calls += 1
        stats.input_tokens += response.usage.input_tokens
        stats.output_tokens += response.usage.output_tokens

        # Check if the model wants to use tools
        if response.stop_reason == "tool_use":
            # Collect all tool uses and results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    stats.tool_calls += 1
                    result = memfabric.execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            # Final text response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            stats.elapsed_seconds = time.time() - start
            return text, stats

    stats.elapsed_seconds = time.time() - start
    # If we hit max turns, extract whatever text we have
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    return text or "[No answer produced within turn limit]", stats


def run_openai_loop(
    messages: list[dict],
    memfabric: MemFabricLocal,
    model: str = "gpt-4o-mini",
    max_turns: int = 20,
    temperature: float = 0.0,
    version: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[str, LoopStats]:
    """Run an agentic loop with OpenAI-compatible API, dispatching tool calls to MemFabric.

    Supports OpenAI, OpenRouter, and any OpenAI-compatible endpoint via base_url.
    Returns (final_text_answer, stats).
    """
    kwargs = {}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    client = openai.OpenAI(**kwargs)
    stats = LoopStats()
    start = time.time()

    # Get tool schemas from versioned definitions
    tool_defs = get_version(version).tools
    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tool_defs
    ]

    for _ in range(max_turns):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
            )
        except Exception as e:
            stats.errors.append(str(e))
            break

        stats.llm_calls += 1
        choice = response.choices[0]
        usage = response.usage
        stats.input_tokens += usage.prompt_tokens
        stats.output_tokens += usage.completion_tokens

        if choice.finish_reason == "tool_calls":
            # Process tool calls
            messages.append(choice.message.model_dump())
            for tc in choice.message.tool_calls:
                stats.tool_calls += 1
                args = json.loads(tc.function.arguments)
                result = memfabric.execute_tool(tc.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
        else:
            # Final text response
            stats.elapsed_seconds = time.time() - start
            return choice.message.content or "", stats

    stats.elapsed_seconds = time.time() - start
    return choice.message.content or "[No answer produced within turn limit]", stats
