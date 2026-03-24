"""Versioned MemFabric tool definitions and prompts.

Each version is a complete snapshot of tool schemas, ingest prompt, and query prompt.
When iterating on the benchmark, create a new version rather than editing an existing one.
This preserves the ability to reproduce any previous run.

Usage:
    from src.versions import get_version, LATEST_VERSION

    v = get_version("v1")
    v.tools          # tool schemas for the LLM
    v.ingest_prompt  # system prompt for ingest phase
    v.query_prompt   # system prompt for query phase
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemFabricVersion:
    """A frozen snapshot of tool definitions and prompts."""

    id: str
    description: str
    tools: list[dict]
    ingest_prompt: str
    query_prompt: str

    def metadata(self) -> dict:
        """Return version info for embedding in run reports."""
        return {
            "version": self.id,
            "description": self.description,
            "num_tools": len(self.tools),
            "tool_names": [t["name"] for t in self.tools],
        }


# ═══════════════════════════════════════════════════════════════════════════
# v1 — Initial version (baseline benchmark run)
# ═══════════════════════════════════════════════════════════════════════════

_V1_TOOLS = [
    {
        "name": "list_memories",
        "description": (
            "List all memory files with metadata. Returns filename, size in bytes, "
            "first line preview, and number of entries for each file. Use this to decide "
            "which files to read — the filenames are descriptive and designed to help you "
            "find relevant information without reading every file."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_memory",
        "description": (
            "Read the full contents of a memory file. Use after list_memories to read "
            "files whose names suggest they contain information relevant to your current task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename (without .md extension) to read.",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Store a fact, event, or insight in a memory file. Creates the file if it "
            "doesn't exist, or appends a new dated entry if it does. Use descriptive "
            "kebab-case filenames that capture the topic, e.g. 'audrey-career-changes', "
            "'shared-travel-plans', 'andrew-health-updates'. Never use generic names "
            "like 'notes' or 'session-3'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Semantic kebab-case filename (no .md extension). Should describe the topic.",
                },
                "content": {
                    "type": "string",
                    "description": "The information to store.",
                },
                "entry_date": {
                    "type": "string",
                    "description": "Date for this entry in YYYY-MM-DD format. Use the date from the conversation if available.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "update_memory",
        "description": (
            "Replace the entire content of a memory file. Use this only when the ground "
            "truth has changed and the old content is no longer accurate — e.g. someone "
            "changed jobs, moved cities, or corrected earlier information. For adding new "
            "information, use 'remember' instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename (without .md extension) to overwrite.",
                },
                "content": {
                    "type": "string",
                    "description": "The new complete content for the file.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "reorganize",
        "description": (
            "Reorganize memory files by merging, splitting, renaming, or deleting them. "
            "Use this to keep memory well-organized as it grows. Operations:\n"
            "- merge: Combine multiple files into one. Provide sources, target name, and merged content.\n"
            "- split: Break a large file into focused smaller files. Provide source and targets with content.\n"
            "- rename: Change a file's name to be more descriptive.\n"
            "- delete: Remove a file that is no longer useful."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "List of operations to perform.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["merge", "split", "rename", "delete"],
                            },
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "For merge: filenames to merge.",
                            },
                            "target": {
                                "type": "string",
                                "description": "For merge: target filename.",
                            },
                            "source": {
                                "type": "string",
                                "description": "For split: source filename.",
                            },
                            "targets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "filename": {"type": "string"},
                                        "content": {"type": "string"},
                                    },
                                },
                                "description": "For split: target files with content.",
                            },
                            "content": {
                                "type": "string",
                                "description": "For merge: merged content.",
                            },
                            "old_name": {"type": "string", "description": "For rename."},
                            "new_name": {"type": "string", "description": "For rename."},
                            "filename": {"type": "string", "description": "For delete."},
                        },
                        "required": ["type"],
                    },
                }
            },
            "required": ["operations"],
        },
    },
]

_V1_INGEST_PROMPT = """\
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
Make filenames specific and descriptive.\
"""

_V1_QUERY_PROMPT = """\
You are answering questions about a conversation between two people. You have access to \
memory files that contain information extracted from their conversations.

To answer each question:
1. Call list_memories to see available memory files.
2. Read the files most likely to contain the answer (based on filenames).
3. Answer the question concisely and directly based on what you find in memory.

Important:
- Be concise — answer in 1-3 sentences.
- If you cannot find the answer in memory, say so honestly. Do not make up information.
- For temporal questions, pay attention to dates and the order of events.
- Give specific details (names, dates, places) when available in memory.\
"""

V1 = MemFabricVersion(
    id="v1",
    description="Initial version. Basic tool descriptions and prompts from first benchmark run.",
    tools=_V1_TOOLS,
    ingest_prompt=_V1_INGEST_PROMPT,
    query_prompt=_V1_QUERY_PROMPT,
)


# ═══════════════════════════════════════════════════════════════════════════
# v2 — Production-aligned tools + improved prompts
#
# Changes from v1:
#   - Tool descriptions ported from production MCP server (server.py)
#   - remember() description emphasizes "primary write tool", lean content
#   - read_memory() says "read before responding", "read multiple files"
#   - update_memory() refuses to create new files (use remember() instead)
#   - list_memories() returns last_updated date, skips headers for first_line
#   - remember() and update_memory() return all_files summary in response
#   - 3KB file size guidance: split large files into focused sub-files
#   - reorganize() adds synthesize operation (keeps sources unlike merge)
#   - Filename sanitization to kebab-case
#   - New files get # Title header
#   - Ingest prompt: more aggressive detail extraction, date normalization
#   - Query prompt: read 3+ files, say "I don't know" over guessing
# ═══════════════════════════════════════════════════════════════════════════

_V2_TOOLS = [
    {
        "name": "list_memories",
        "description": (
            "List all memory files with metadata. Call this at the start of every "
            "query and before calling remember() to check for existing files. Returns "
            "filenames, entry counts, last updated dates, sizes, and a 2-line content "
            "preview. Scan filenames and previews to decide which to read with read_memory()."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_memory",
        "description": (
            "Read the full contents of one or more memory files. Call this after "
            "list_memories() to read files relevant to the current question. Always "
            "read before responding so your answers reflect what you know. Use the "
            "filenames parameter to read multiple files in a single call — read at "
            "least 3 files for complex questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "A single filename to read, without .md extension.",
                },
                "filenames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple filenames to read at once, without .md extension.",
                },
            },
        },
    },
    {
        "name": "remember",
        "description": (
            "Store a fact, preference, decision, or any information worth keeping. "
            "This is the primary write tool — call it whenever you encounter "
            "something memorable. Always call list_memories() first to check if a "
            "relevant file exists. If it does, use that filename to append. If not, "
            "create a new one. Each call appends a dated entry; existing entries are "
            "preserved.\n\n"
            "Use semantic kebab-case filenames that describe the content. "
            "Good: 'favorite-papers', 'career-goals', 'family-context'. "
            "Bad: 'misc-notes', 'march-2026', 'session-5'.\n\n"
            "Write lean content — capture the insight or fact, not the full conversation.\n\n"
            "If adding an entry changes the semantic scope of the file, use new_filename "
            "to rename it. E.g. appending travel info to 'audrey-hobbies' → rename to "
            "'audrey-hobbies-and-travel'.\n\n"
            "The response includes an all_files summary showing every file and its size. "
            "If any file exceeds 3KB, consider: (1) rewriting it with update_memory() to "
            "condense the content without losing facts, or (2) splitting it into smaller, "
            "more focused files with reorganize(). Keeping files compact improves retrieval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Semantic kebab-case filename without .md extension, e.g. 'favorite-papers'.",
                },
                "content": {
                    "type": "string",
                    "description": "The entry text to store.",
                },
                "entry_date": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD), defaults to today.",
                },
                "new_filename": {
                    "type": "string",
                    "description": "Optional: rename the file after appending, if the entry changes the file's semantic scope.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "update_memory",
        "description": (
            "Replace the entire contents of a memory file. Use this when information "
            "is outdated or when a file needs rewriting for clarity. Always call "
            "read_memory() first so you know what you're replacing. If you want to "
            "add a new entry while keeping existing ones, use remember() instead. "
            "Cannot create new files — use remember() for that.\n\n"
            "The response includes an all_files summary. If any file exceeds 3KB, "
            "consider condensing it with update_memory() or splitting with reorganize()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to overwrite, without .md extension.",
                },
                "content": {
                    "type": "string",
                    "description": "The complete new file content.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "reorganize",
        "description": (
            "Restructure memory files by merging, splitting, synthesizing, or renaming. "
            "Call this when files overlap or grow too large. Read the files you plan to "
            "reorganize first.\n\n"
            "Operations:\n"
            "- merge: Combine files into one (deletes sources). Provide source_files, "
            "target_filename, content.\n"
            "- split: Break a file into parts (deletes source). Provide source_file, "
            "new_files (dict of filename -> content).\n"
            "- synthesize: Create insight from multiple files (keeps sources). Provide "
            "source_files, target_filename, content.\n"
            "- rename: Change a filename. Provide old_filename, new_filename.\n"
            "- delete: Remove a file. Provide filename."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "List of operations to perform.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["merge", "split", "synthesize", "rename", "delete"],
                            },
                            "source_files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "For merge/synthesize: source filenames.",
                            },
                            "target_filename": {
                                "type": "string",
                                "description": "For merge/synthesize: target filename.",
                            },
                            "source_file": {
                                "type": "string",
                                "description": "For split: source filename.",
                            },
                            "new_files": {
                                "type": "object",
                                "description": "For split: dict of filename -> content.",
                            },
                            "content": {
                                "type": "string",
                                "description": "For merge/synthesize: the content to write.",
                            },
                            "old_filename": {"type": "string", "description": "For rename."},
                            "new_filename": {"type": "string", "description": "For rename."},
                            "filename": {"type": "string", "description": "For delete."},
                        },
                        "required": ["type"],
                    },
                }
            },
            "required": ["operations"],
        },
    },
]

_V2_INGEST_PROMPT = """\
You are a memory management agent. You are processing a conversation between two people, \
one session at a time. Your job is to extract and store ALL important information from each \
session into memory files.

You have access to memory tools: list_memories, read_memory, remember, update_memory, \
and reorganize.

WHAT TO STORE — be thorough, capture everything that might matter:
- Personal facts: names, ages, locations, family members, number of children, pets (species and names)
- Preferences and opinions: favorites, likes, dislikes, and why
- Events: what happened, when (convert relative dates like "last week" to absolute dates \
using the session date), where, with whom
- Plans and goals: what they intend to do, timelines, deadlines
- Relationships: who knows whom, how they relate, dynamics
- Career and work: jobs, roles, changes, aspirations
- Hobbies and interests: specific activities, books read (with titles), music, sports
- Health and wellness: routines, challenges, milestones
- Specific details: exact book titles, band names, recipe names, amounts, scores, \
instruments played, places visited — these matter for questions later

HOW TO STORE:
- Call list_memories() first to check for existing files. Append to existing files with \
remember() rather than creating duplicates.
- Create per-person files for distinct topics. Don't lump everything about a person into one \
file. Good: "audrey-career", "audrey-pets", "audrey-hobbies", "andrew-health", \
"andrew-family". Bad: "audrey-everything", "andrew-notes". Each file should cover one \
topic for one person — this makes retrieval by filename accurate.
- Use semantic kebab-case filenames. The filename alone should tell you what's inside.
- Write lean entries — capture the fact, not the conversation. Do NOT include dates in \
the content text — use the entry_date parameter instead. Every remember() call MUST include \
entry_date in YYYY-MM-DD format derived from the session timestamp.
- When relative dates appear ("last Tuesday", "next month"), compute the actual date \
from the session timestamp and store that in entry_date.
- When new information changes someone's situation (new job, moved cities, new relationship \
status), append the update with remember() — don't overwrite. The chronological history \
matters for temporal questions. Reserve update_memory() for rewriting a file's structure \
for clarity, not for correcting facts.
- Extract BOTH speakers' information — don't focus on just one person.
- After each remember() or update_memory() call, check the all_files summary in the response. \
If any file exceeds 3KB, first try to condense it with update_memory() — rewrite to be \
shorter without losing any facts. If it's still too large, split it into focused sub-files \
with reorganize(). Compact files are easier to retrieve by filename.\
"""

_V2_QUERY_PROMPT = """\
You are answering questions about a conversation between two people. You have access to \
memory files that contain information extracted from their conversations.

To answer each question:
1. Call list_memories() to see all available memory files.
2. Read the 3-4 files most likely to contain the answer based on their filenames and previews. \
Use read_memory with the filenames parameter to read multiple files in one call.
3. If the answer is clearly in what you read, answer concisely (1-3 sentences).
4. If not, read 2-3 more files that might be relevant — the answer may be in a file with \
a less obvious name. Only give up after checking at least 5 files total.

Important:
- Be concise — answer in 1-3 sentences.
- If you cannot find the answer after reading 5+ files, say "I don't have that information \
in memory." Do NOT guess or make up plausible-sounding answers.
- For temporal questions, pay close attention to dates and the chronological order of events.
- Give specific details (names, dates, places, numbers) when available in memory.\
"""

V2 = MemFabricVersion(
    id="v2",
    description="Production-aligned tools. Better descriptions, get_status, synthesize, aggressive detail extraction.",
    tools=_V2_TOOLS,
    ingest_prompt=_V2_INGEST_PROMPT,
    query_prompt=_V2_QUERY_PROMPT,
)


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

VERSIONS: dict[str, MemFabricVersion] = {
    "v1": V1,
    "v2": V2,
}

LATEST_VERSION = "v2"


def get_version(version_id: str | None = None) -> MemFabricVersion:
    """Get a version by ID. Returns latest if None."""
    vid = version_id or LATEST_VERSION
    if vid not in VERSIONS:
        available = ", ".join(sorted(VERSIONS.keys()))
        raise ValueError(f"Unknown version '{vid}'. Available: {available}")
    return VERSIONS[vid]


def list_versions() -> list[dict]:
    """List all available versions with metadata."""
    return [v.metadata() for v in VERSIONS.values()]
