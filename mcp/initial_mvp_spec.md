# MemFabric

## Self-Organizing Memory Layer for LLMs

A self-hosted MCP server that gives any LLM persistent, self-organizing memory across all your devices and AI tools.

---

## Motivation

Every time you start a new conversation with an AI, you start from zero. It doesn't know your name, your projects, your preferences, or what you told it yesterday. If you use multiple AI tools (Claude, ChatGPT, Cursor, OpenClaw, etc.), the problem multiplies: each one is a stranger.

Current solutions are either locked to one platform (Claude's memory, ChatGPT's memory) or require complex infrastructure (vector databases, embedding pipelines, RAG systems). They're opaque, non-portable, and you can't read or edit what they store.

MemFabric takes a different approach:

- **Memory is plain .md files** with semantic filenames. Human-readable, editable, debuggable.
- **The LLM does all the thinking.** The server is dumb storage with a clean API. No AI model runs on the server.
- **Memory self-organizes.** Files get merged, split, synthesized, and renamed as your thinking evolves. The LLM decides when and how.
- **One memory, every tool.** Deploy once, connect from any MCP-compatible client on any device. All your AI tools share the same memory.
- **You own everything.** Self-hosted. Your data never touches a third-party service.

### Core Promise

One memory. Every AI tool. Every device. It grows with you.

---

## How It Works

```
Claude Desktop (home laptop)  ──→
Claude app (phone)             ──→
Cursor (work laptop)           ──→  MemFabric Server  ──→  /data/memory/*.md
ChatGPT (browser)              ──→  (Railway)            /data/system/rules.md
OpenClaw (home server)         ──→
```

The MCP server runs on Railway (or any PaaS with persistent volumes). It exposes MCP tools that any compatible client can call. Memory files live on a persistent volume attached to the server. Deploy by connecting your GitHub repo to Railway. No Docker knowledge required.

The server does NO AI work. It reads files, writes files, moves files, and returns metadata. Every decision about what to store, where to store it, what to merge, and what to surface is made by the connected LLM client.

---

## Architecture

### Storage

All data is stored as plain .md files on a persistent volume:

```
/data/
  /memory/
    about-alex.md
    career-goals-2026.md
    product-pricing-strategy.md
    people-i-work-with.md
    opinion-on-microservices-vs-monolith.md
    daughters-school-schedule.md
    ...
  /system/
    rules.md
    status.json
```

### Memory Files

Each .md file is a living document organized by semantic topic. Entries are appended over time. A single file might span weeks or months if the topic persists.

Example file `choosing-customers-strategically.md`:

```markdown
# Choosing Customers Strategically

## 2026-03-19
Source: conversation
Seth Godin podcast insight: choosing your customers is the most
important strategic decision. It determines product, pricing,
distribution, and your daily life. The Humane Pin failed because
they targeted Apple-level buyers but shipped a non-Apple product.

## 2026-03-24
Source: conversation
Realized this applies to consulting too. A friend who sold to
real estate agents warned "be careful who you sell to." Your
customers become your daily life.

## 2026-04-02
Source: user request
Decided: target audience is smart, pragmatic people in AI, often
immigrants, who have lives outside work. Not workaholics. This
filters everything.
```

### Self-Organizing Behavior

Memory files are not static. The LLM can restructure them through four operations:

**Merge:** Two or more files that are about the same topic get combined. The LLM reads all source files, writes a synthesized version that preserves all important information as one coherent document. Source files are deleted.

```
Before:
  smallest-viable-audience.md
  choosing-customers-strategically.md
After:
  customer-selection-and-audience-strategy.md
```

**Split:** One file that grew too broad gets separated into focused files. Source file is deleted.

```
Before:
  startup-strategy-thoughts.md (pricing + hiring mixed together)
After:
  pricing-strategy-early-stage.md
  hiring-first-ten-employees.md
```

**Synthesize:** A new pattern emerges across multiple files. A new file is created that captures the insight. Source files are NOT deleted. This is additive.

```
New file:
  pattern-embedded-distribution.md
  (references: distribution-tradeoffs.md, telegram-as-interface.md, 
   dev-tools-spreading-via-github.md)
```

**Rename:** A file's name no longer reflects its content. The filename updates. Content stays the same.

### File Naming

Filenames are the primary retrieval mechanism. There is no vector database, no embedding search. The LLM reads the list of filenames and decides which ones are relevant. This means filenames must be:

- Lowercase kebab-case
- Specific and semantic
- Self-explanatory without opening the file

Good: `product-pricing-strategy.md`, `daughters-school-schedule.md`, `opinion-on-microservices-vs-monolith.md`

Bad: `misc-notes.md`, `march-2026.md`, `conversation-5.md`, `untitled.md`

### Rules File

`/data/system/rules.md` controls how memory behaves. It is read by the LLM to understand user preferences. Users can edit it through the LLM at any time.

### Auth

A single token set at deploy time via environment variable. Every MCP request must include this token. One server = one user. No user management needed.

---

## MCP Server Description

This is the description that the LLM sees when it connects. It teaches the LLM how to use memory naturally:

```
MemFabric is the user's persistent memory. It stores what matters
from conversations as organized .md files that persist across
all sessions and all AI tools the user connects to.

You have access to the user's memory through these tools. Use
your judgment on when to read and write. Some guidelines:

READING MEMORY:
- If the user asks something personal, references a past
  conversation, or asks "do you remember...", check memory.
- If the user starts a topic where past context would help
  (a project they've mentioned before, a decision they were
  weighing), check memory.
- If the conversation is casual or about general knowledge,
  you probably don't need to check memory.
- When you do check, start with list_memories(). Scan the
  filenames. Only read files that seem relevant.

WRITING MEMORY:
- When the user shares something that would be useful in
  future conversations, store it. Preferences, decisions,
  ideas, context about their life or work, people they
  mention, opinions, project updates.
- Don't store every message. Store what matters.
- When in doubt about whether to store something, lean
  toward storing it. It's easier to clean up later than to
  lose something.
- Check list_memories() before writing to see if you should
  append to an existing file or create a new one.

MAINTENANCE:
- After writing, occasionally check get_status(). If memory
  is getting messy (many new files since last reorganize),
  consider tidying up with reorganize().

ONBOARDING:
- Call get_rules() on first interaction. If is_onboarded is
  false, have a friendly conversation to learn about the
  user, then store their profile and update the rules.
- After onboarding, you don't need to call get_rules() every
  time. The rules rarely change. Check them if the user asks
  to change how memory works.

The goal is natural, invisible memory. The user should feel
like you remember things about them without it being awkward
or slow.
```

---

## MCP Tools

### `start()`

```
Onboarding tool. Call this the very first time a user connects
and get_rules() shows is_onboarded: false.

This begins a friendly conversation to learn basic facts about
the user. DO NOT ask all questions at once. Have a natural
conversation, one or two questions at a time.

Gather the following:
- Name (what should I call you?)
- Age or age range
- Where they live (city, country)
- Family status (partner, kids, etc.)
- What they do for work
- Their preferred language for communication
- What they mainly use AI tools for
- Anything else they want you to always know about them

After the conversation:
1. Call remember() to store the user's basic profile in a
   file named "about-{name}"
2. Call edit_rules() to set is_onboarded: true and adjust
   any rules based on what you learned (e.g. if the user
   said "don't store anything about my health" or "write
   entries in Spanish")

This only needs to happen once.
```

Returns: a welcome message template to begin the onboarding conversation.


### `remember(filename, content, entry_date?)`

```
Store information in the user's memory. This is the primary
write operation.

Use this whenever the user shares something worth keeping:
preferences, decisions, ideas, project context, people they
mention, opinions, goals, life updates, technical choices,
or anything they explicitly ask you to remember.

YOU decide the filename and content. The server just writes.

Filename rules:
- Use lowercase kebab-case (e.g. "career-goals-2026")
- Be specific and semantic. The filename should tell you
  what's inside without opening it.
- BAD: "misc-notes.md", "march-2026.md", "conversation-5.md"
- GOOD: "product-pricing-strategy.md",
  "daughters-school-schedule.md",
  "opinion-on-microservices-vs-monolith.md"

Before calling remember, first call list_memories() to check
if a relevant file already exists. If it does, use that
filename to append. If not, create a new one.

Content should be lean. Capture the insight, decision, or
fact. Not the full conversation. Write in a way that will
be useful months from now when context is lost.

Each call appends a new dated entry to the file. Existing
entries are preserved.
```

Parameters:
- `filename` (required): semantic filename without .md extension
- `content` (required): the entry text
- `entry_date` (optional): ISO date string, defaults to now

Returns: confirmation, filename, entry count in file.


### `list_memories()`

```
Returns all memory filenames with metadata. This is the table
of contents of everything you know about the user.

Call this when you need context about the user. Scan the
filenames first. Because filenames are semantic, you can
often tell what's relevant without reading file contents.

Only call read_memory() on files that seem relevant to the
current conversation.
```

Returns: list of objects with filename, entry count, last updated date, file size in bytes, first line of content.


### `read_memory(filename)`

```
Read the full contents of a memory file.

Call this after list_memories() when you identify files
relevant to the current conversation. Read before responding
so your answers reflect what you already know about the user.

Also call this before remember() with an existing filename to
understand the current state of that memory thread before
appending.

You can read multiple files in sequence if several are
relevant.
```

Parameters:
- `filename` (required): the filename to read, without .md extension

Returns: full file contents as string.


### `update_memory(filename, content)`

```
Overwrite an entire memory file with new content.

Use this when:
- The user says their situation has changed ("I moved to
  Berlin", "I quit that job", "I changed my mind about X")
- A file has become stale or inaccurate
- You want to rewrite a file to be clearer or better
  organized after reading it

This replaces ALL content in the file. If you want to
preserve existing entries and add a new one, use remember()
instead.

Before calling this, always read_memory() first so you know
what you're replacing.
```

Parameters:
- `filename` (required): the filename to overwrite
- `content` (required): the complete new content

Returns: confirmation, filename, new file size.


### `reorganize(operations)`

```
Restructure memory files. The server executes file operations;
you provide all the content and decisions.

Call this when get_status() shows files_since_last_reorganize
has grown large, or when you notice during list_memories()
that files overlap or have grown unwieldy.

Before calling, read the files you plan to reorganize so you
can write good merged/split content.

Operation types:

MERGE: Two or more files that are about the same topic.
Read all source files, synthesize a single coherent version
that preserves all important information but reads as one
unified document. Source files are deleted.

SPLIT: One file that contains distinct threads. Read the
file, separate into focused files with clear names. Source
file is deleted.

SYNTHESIZE: A pattern you notice across multiple files.
Create a new file capturing the insight. Source files are
NOT deleted. This is additive.

RENAME: A file whose name no longer reflects its content.
Content stays the same.

You can send multiple operations in one call.
```

Parameters:
- `operations` (required): list of operation objects, each with:
  - `type`: `"merge"` | `"split"` | `"synthesize"` | `"rename"`
  - For merge: `source_files` (list), `target_filename` (string), `content` (string - the full synthesized content)
  - For split: `source_file` (string), `new_files` (object of filename -> full content)
  - For synthesize: `source_files` (list), `target_filename` (string), `content` (string - the full synthesized content)
  - For rename: `old_filename` (string), `new_filename` (string)

Returns: summary of operations performed (files created, deleted, renamed).


### `edit_rules(content)`

```
Overwrite rules.md with new content.

rules.md controls how memory behaves: what to store, what
to skip, naming conventions, language preferences, and any
standing instructions from the user.

Call get_rules() first to read the current version, then
modify and write back.

Users can trigger this by saying things like "stop storing
things about my health", "always write memory entries in
Spanish", "use shorter filenames", "don't store one-off
questions", etc.
```

Parameters:
- `content` (required): the complete new rules.md contents

Returns: confirmation.


### `get_rules()`

```
Read rules.md. This file tells you:
- What to store and what to skip
- How to name files
- What language to write entries in
- Any user-specific instructions for memory management
- Whether onboarding has been completed (is_onboarded field)

If is_onboarded is false, call start() to begin onboarding.

You don't need to call this every conversation. Check it on
first interaction and if the user asks to change how memory
works.
```

Returns: rules.md contents as string.


### `get_status()`

```
Returns metadata about the memory system. Use this to decide
if maintenance is needed.

Call this after storing new memories to check if
reorganization is due. The key field is
files_since_last_reorganize. When this exceeds the threshold,
consider running list_memories(), reviewing files for overlaps
or patterns, and calling reorganize().

Also useful for general awareness of memory size and health.
```

Returns:
```json
{
  "total_files": 47,
  "files_since_last_reorganize": 12,
  "last_reorganize_date": "2026-03-15",
  "largest_files": [
    {"name": "product-strategy-decisions", "entries": 23, "bytes": 8400}
  ],
  "oldest_untouched_files": [
    {"name": "old-project-timeline", "last_updated": "2026-01-10"}
  ],
  "total_memory_size_bytes": 94000,
  "reorganize_threshold": 10
}
```

---

## Default rules.md

This ships as the initial configuration. Users can modify it at any time through any connected LLM.

```markdown
# Memory Rules

## Status
is_onboarded: false

## What to store
- Anything that might be useful in future conversations
- Preferences, decisions, opinions, and the reasoning behind them
- People the user mentions and context about them
- Projects, goals, and their status
- Ideas, hypotheses, and evolving thinking
- Life context (family, location, work, interests)
- Things the user explicitly asks to remember

## What to skip
- Small talk and pleasantries
- One-off questions with no lasting relevance
- Anything the user explicitly says to forget
- Temporary task details (formatting requests, one-off calculations)

## How to store
- Keep entries lean: capture the insight, not the full conversation
- When storing a decision, include the reasoning
- When storing a person, include relationship context
- Write so it's useful months from now when context is lost

## File naming
- Use lowercase kebab-case
- Be specific and semantic
- The filename alone should tell you what's inside

## Language
- Write memory entries in English

## Reorganization
- Reorganize when files_since_last_reorganize exceeds threshold
- Prefer merging over accumulating many small overlapping files
- When merging, synthesize a coherent document, don't just concatenate
```

---

## Onboarding Flow

First connection ever. `get_rules()` returns default with `is_onboarded: false`.

```
Agent: Hey! I'm your memory layer. I work across all your
AI tools, so anything I learn here, your other tools will
know too. Let me learn a bit about you first. What should
I call you?

User: Alex

Agent: Hey Alex. Where are you based?

User: Jersey City, originally from Ukraine

Agent: What do you do for work?

User: Software engineer, working on AI products

Agent: And outside of work? Anything you'd want me to keep
in mind?

User: Married, have a 3 year old daughter. I like chess
and reading sci-fi.

Agent: Got it. Any preferences for how I manage your
memory? For example, should I write entries in English or
Ukrainian? Anything I should never store?

User: English is fine. Don't store anything about my
daughter's health.

Agent: Done. You're all set. From now on, every AI tool
you connect will know who you are.
```

After this, the agent:
1. Calls `remember("about-alex", ...)` with profile info
2. Calls `edit_rules()` to set `is_onboarded: true`, add the exclusion about daughter's health, and adjust any other rules based on what was learned

---

## Tech Stack

- **Language:** Python
- **Protocol:** MCP SDK (official Python SDK), Streamable HTTP transport for remote access
- **Storage:** File system on Railway persistent volume (.md files)
- **Deployment:** Railway (connect GitHub repo, auto-deploys on push, no Docker needed). "Deploy to Railway" button for one-click setup.
- **Auth:** Single token via Railway environment variable
- **Dependencies:** None beyond MCP SDK. No database, no vector store, no AI model, no embedding pipeline.

---

## What This Is NOT

- **Not an AI model.** Zero inference on the server. The connected LLM does all thinking.
- **Not a vector database.** No embeddings, no similarity search. The LLM reads filenames and file contents directly.
- **Not a RAG system.** No retrieval pipeline. The LLM decides what to read.
- **Not a chatbot.** There's no UI. The LLM client is the UI.
- **Not a second brain app.** No Notion, no Obsidian, no graph view. Just files.
- **Not a local-only tool.** It's a server, accessible from any device anywhere.
- **Not multi-user.** One server = one user. Deploy separate instances for separate people.

---

## Key Design Decisions

### Why .md files instead of a database?
- Human-readable. You can open any file and see exactly what the system knows.
- Editable. You can manually fix or update any memory with a text editor.
- Debuggable. When something goes wrong, you read a file, not query a database.
- The LLM works with text natively. No serialization/deserialization layer needed.
- Git-compatible if users want version history (optional, not required).

### Why semantic filenames instead of embeddings?
- LLMs are excellent at scanning a list of descriptive names and picking relevant ones.
- No embedding infrastructure to maintain.
- No drift between embedding model versions.
- Filenames are a human-readable index. You can browse your own memory by listing a directory.
- Scales well enough: even 500 well-named files produce a scannable list for an LLM.

### Why no AI on the server?
- Keeps the server simple, cheap, and fast.
- No model costs, no GPU, no API keys to manage on the server side.
- The LLM client already has intelligence. Don't duplicate it.
- Users can connect any LLM they want. The memory layer doesn't care which one.
- Easier to maintain, deploy, and debug.

### Why self-hosted?
- Memory contains the user's raw, unfiltered thinking. Privacy matters.
- No vendor lock-in. If you stop using the service, your files are right there.
- Users in the target audience (engineers, AI practitioners) are comfortable with self-hosting.
- Avoids building auth, billing, and multi-tenancy for v1.

---

## Success Metric

You open Claude on your phone at a coffee shop. You say "what was I thinking about that distribution problem?" and it already knows, because you talked about it yesterday in Cursor on your laptop. No setup, no copy-paste, no context-setting. It just knows.

---

## Implementation Plan

### Phase 1: Core Server
- [ ] Set up Python project with MCP SDK
- [ ] Implement file storage layer (read, write, append, delete, rename .md files)
- [ ] Implement `remember()` tool
- [ ] Implement `list_memories()` tool
- [ ] Implement `read_memory()` tool
- [ ] Implement `update_memory()` tool
- [ ] Implement `get_rules()` and `edit_rules()` tools
- [ ] Implement `start()` onboarding tool
- [ ] Create default rules.md
- [ ] Add token-based auth
- [ ] Write MCP server description and tool descriptions

### Phase 2: Self-Organization
- [ ] Implement `reorganize()` tool (merge, split, synthesize, rename operations)
- [ ] Implement `get_status()` tool
- [ ] Implement status.json tracking (files created since last reorg, timestamps)

### Phase 3: Deployment
- [ ] Configure Railway project with persistent volume
- [ ] Set up Streamable HTTP transport for remote MCP access
- [ ] Create railway.json config and "Deploy to Railway" button
- [ ] Write setup documentation (Railway deploy + MCP client config)
- [ ] Test with Claude Desktop, Cursor, and at least one other MCP client

### Phase 4: Polish
- [ ] Test onboarding flow end-to-end
- [ ] Test reorganize operations (merge, split, synthesize) with real data
- [ ] Stress test with 100+ memory files
- [ ] Write README with setup instructions and examples
- [ ] Open source the repo
