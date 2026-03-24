# MemFabric

**Self-organizing agent memory. No embeddings, no vector DB.**

MemFabric is a memory system where the LLM organizes its own knowledge as plain markdown files with descriptive filenames. There is no vector database, no embedding pipeline, no retrieval model. The LLM reads a list of filenames, decides what's relevant, and reads those files. It stores new information by creating, appending to, or reorganizing files: merging, splitting, renaming, and synthesizing as its knowledge grows.

The server just stores and retrieves files. All intelligence (what to remember, how to organize, what's relevant) comes from the connected LLM.

## What it looks like

After a few weeks of conversations, your AI builds up memory like this:

```
memory/
  about-me.md           0.8 KB
  family-and-friends.md 1.4 KB
  food-and-cooking.md   1.1 KB
  health.md             0.6 KB
  travel.md             2.3 KB
```

Then in a new conversation:

```
You:   My sister is visiting this weekend. What should I cook?

AI:    [reads family-and-friends.md — sister is Sarah, loves Italian]
       [reads health.md — you're lactose intolerant]

       Since Sarah loves Italian and you're dairy-free, how about
       a lemon pasta with roasted garlic and cherry tomatoes? You
       made something similar last month and liked it.

You:   Perfect, let's do that.

AI:    [writes to food-and-cooking.md]

       Noted! I saved it so I'll remember for next time.
```

Two reads, one write. The AI connected your sister's preferences with your dietary needs without being reminded of either. No setup, no schema, no retrieval config. This is a small example; in practice you'll have 20-30 files or more, and the AI reorganizes them over time, merging, splitting, and rewriting to keep things clean.

## Use cases

- **Personal memory for AI chatbots** - give Claude, ChatGPT, or Gemini persistent memory that works across conversations and follows you between providers
- **Memory for [OpenClaw](https://github.com/anthropics/openclaw)** - equip open-source computer-use agents with long-term context about the user and their environment
- **Multi-agent shared memory** - multiple agents read and write to the same MemFabric instance, using filenames as a shared namespace
- **Coding assistants** - tools like Claude Code can remember codebase decisions, architecture context, and debugging history across sessions

## Why this works

Most memory systems for LLMs use embeddings and vector search to find relevant memories. This adds infrastructure, introduces retrieval errors, and creates a dependency on embedding quality. But LLMs are already excellent at judging relevance from natural language descriptions. That's literally what they do.

MemFabric exploits this: **the filename is the retrieval mechanism.** A file called `audrey-career-and-promotions.md` tells the LLM everything it needs to know about whether to read it. No embedding needed.

The LLM also manages file organization. When files get too large or topics overlap, the LLM merges, splits, or synthesizes them, the same way a human would reorganize their notes. This means the memory structure improves over time, adapting to the actual information being stored rather than following a fixed schema.

### Better models = better memory

Because all intelligence lives in the LLM, MemFabric gets better automatically as models improve. I tested 5 different models on the same memory task. The pattern is clear:

| Model | J-Score | Files created | Notes |
|-------|---------|---------------|-------|
| Haiku 4.5 | 78.3% | 15 | Too few files, topics lumped together |
| DeepSeek V3 | 79.6% | 34 | Over-fragmented, too many small files |
| MiniMax M2.5 | 82.2% | 18 | Good balance |
| Claude Sonnet | 83.6% | 23 | Most balanced, best temporal reasoning |
| MiMo-V2-Pro | 84.2% | 27 | Best overall, strongest multi-hop |

More capable models produce better-organized memory files: they create the right number of files, choose more descriptive names, and capture more nuanced information. The gap between the weakest and strongest model is 5.9pp, with no changes to the server or tools.

This is the key advantage over embedding-based approaches: vector databases don't get better when models improve. MemFabric does. Every future model improvement translates directly into better memory organization and retrieval.

## Benchmark results

I evaluated MemFabric on [LoCoMo](https://snap-research.github.io/locomo/) (Long Conversational Memory), a benchmark of 10 multi-session conversations with 1,540 questions testing single-hop recall, multi-hop reasoning, temporal reasoning, and open-domain knowledge.

### Leaderboard

All results below use the same evaluation protocol (gpt-4o-mini as query/judge model, binary J-score) for fair comparison.

| # | System | J-Score | Infrastructure |
|---|--------|---------|----------------|
| 1 | [MemMachine v0.1](https://memmachine.ai/blog/2025/09/memmachine-reaches-new-heights-on-locomo/) | 84.9% | Vector DB + reranker |
| **2** | **MemFabric** | **82.6%** | **Markdown files** |
| 3 | [Engram](https://www.engram.fyi/research) | 80.0% | SQLite |
| 4 | Baseline (full context) | 77.2% | Full conversation in LLM context |
| 5 | [Memobase](https://github.com/memodb-io/memobase/blob/main/docs/experiments/locomo-benchmark/README.md) | 75.8% | Database |
| 6 | [Zep](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/) | 75.1% | Database |
| 7 | [Mem0 Graph](https://arxiv.org/abs/2504.19413) | 68.4% | Qdrant + graph store |
| 8 | [Mem0](https://arxiv.org/abs/2504.19413) | 66.9% | Qdrant vector DB |
| 9 | [LangMem](https://arxiv.org/abs/2504.19413) | 58.1% | LangChain |
| 10 | [OpenAI Memory](https://arxiv.org/abs/2504.19413) | 52.9% | Proprietary |

Note: newer systems (SmartSearch, EverMemOS, MemMachine v0.2) report 91-93% using gpt-4.1-mini as both answer and judge model (vs. gpt-4o-mini above). Under that protocol, even the full-context baseline jumps from 77% to 91%, so these numbers are not directly comparable.

### Results by question type

| Category | MemFabric | Full-context baseline | Delta |
|----------|-----------|----------------------|-------|
| **Overall** | **82.6%** | 77.2% | **+5.4** |
| Open-domain | 86.7% | 90.1% | -3.4 |
| Single-hop | 80.5% | 76.2% | +4.3 |
| Multi-hop | 78.2% | 50.2% | **+28.0** |
| Temporal | 67.7% | 57.3% | +10.4 |

Multi-hop reasoning (connecting facts scattered across different conversation sessions) is where organized memory files dominate. The full-context baseline has every detail available but struggles to connect information spread across 20K tokens of conversation. MemFabric's organized files co-locate related information, making cross-session reasoning dramatically easier.

The open-domain gap (-3.4pp) is the inherent cost of summarization: any fact not captured during ingest is a potential miss.

### Key findings

**The ingest model matters most.** Swapping the query model (GPT-4o-mini vs GPT-5.4 Mini) improved scores by 0.2pp. Swapping the ingest model (Haiku to MiMo) improved scores by 3.9pp. The bottleneck is memory quality during extraction, not retrieval intelligence.

**File organization is retrieval.** The sweet spot is 20-27 files per conversation, each covering one topic for one person. Too few files (15) lumps topics together and hurts retrieval precision. Too many files (34) overwhelms the query model with choices.

**Cost: ~$8 for the full benchmark.** Ingest ~$5 (MiMo via OpenRouter), query + judge ~$3 (GPT-4o-mini). Total time: 77 minutes.

Full experiment history and analysis: [`benchmarks/locomo/RESULTS.md`](benchmarks/locomo/RESULTS.md)

## MCP tools

The server exposes 9 tools via the [Model Context Protocol](https://modelcontextprotocol.io):

| Tool | What it does |
|------|-------------|
| `remember(filename, content)` | Store a memory (creates or appends to a file) |
| `list_memories()` | List all files with metadata (entry count, size, preview) |
| `read_memory(filename)` | Read a specific memory file |
| `update_memory(filename, content)` | Replace a file's content entirely |
| `reorganize(operations)` | Merge, split, synthesize, rename, or delete files |
| `get_rules()` | Read memory behavior rules |
| `edit_rules(content)` | Update memory behavior rules |
| `get_status()` | Check system health and reorganization metrics |
| `start()` | Begin user onboarding |

## Setup

### Try it locally

The fastest way to try MemFabric is to run it locally as an MCP server. In this mode, only the AI client on your machine will have access to your memory. It won't be shared across devices or other AI tools.

```bash
cd mcp
uv sync
MEMFABRIC_DATA_DIR=./data uv run python server.py
# Server starts at http://localhost:8000, MCP endpoint at /mcp/
```

Then connect your local AI client to `http://localhost:8000/mcp/`. For example, in Claude Desktop, add this to your MCP config:

```json
{
  "mcpServers": {
    "memfabric": {
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

### Deploy to Railway (shared across all your AIs)

To share memory across Claude.ai, ChatGPT, and any other MCP client, deploy to a hosted server:

1. Push this repo to GitHub
2. Create a new project on [Railway](https://railway.com)
3. Connect your GitHub repo, point to the `mcp/` directory
4. Add a persistent volume mounted at `/data`
5. Set environment variables:
   - `MEMFABRIC_TOKEN`: secret token for auth (`openssl rand -hex 32`)
   - `MEMFABRIC_SERVER_URL`: your Railway public URL
6. Deploy

### Connect your AI

**Claude.ai:** Settings > Connectors > Add custom connector > enter `https://your-app.up.railway.app/mcp/`. OAuth flow handles auth automatically.

> **Tip:** Name the connector something like **"Memory — remembers everything across conversations"**. Claude sees this name in every conversation, so a descriptive name increases how often it actually uses the memory tools. You can also add a line to your Claude.ai custom instructions (Settings > Profile) like: *"You have persistent memory via the Memory connector. Use it to store important facts about me and recall them in future conversations."*

**ChatGPT:** Settings > Apps > Advanced Settings > Developer Mode > Create app > enter your MCP server URL. ChatGPT uses OAuth for MCP authentication.

**Any MCP client:** Point it at `https://your-app.up.railway.app/mcp/` with OAuth or a Bearer token header (`MEMFABRIC_TOKEN`).

## License

MIT
