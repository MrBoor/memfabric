# MemFabric

Self-organizing memory layer for LLMs. One memory, every AI tool, every device.

A self-hosted MCP server that gives any LLM persistent, self-organizing memory as plain `.md` files. No database, no embeddings, no AI on the server. The connected LLM does all the thinking.

## How It Works

```
Claude.ai       ──→
ChatGPT         ──→  MemFabric Server  ──→  /data/memory/*.md
Gemini          ──→  (Railway)             /data/system/rules.md
Any MCP client  ──→
```

Memory is stored as semantically-named `.md` files. The LLM reads filenames to find relevant memories, reads/writes file contents, and self-organizes by merging, splitting, and synthesizing files over time.

## Deploy to Railway

1. Push this repo to GitHub
2. Create a new project on [Railway](https://railway.com)
3. Connect your GitHub repo
4. Add a persistent volume mounted at `/data`
5. Set environment variables:
   - `MEMFABRIC_TOKEN` — a secret token for auth (generate with `openssl rand -hex 32`)
   - `MEMFABRIC_SERVER_URL` — your Railway public URL (e.g. `https://your-app.up.railway.app`)
   - `PORT` — Railway sets this automatically
6. Deploy

Railway auto-detects Python, installs dependencies, and runs `server.py`.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MEMFABRIC_TOKEN` | Yes | Bearer token for authenticating MCP requests |
| `MEMFABRIC_SERVER_URL` | Yes (prod) | Public server URL for OAuth discovery (e.g. `https://your-app.up.railway.app`) |
| `MEMFABRIC_DATA_DIR` | No | Data directory path (default: `/data`) |
| `PORT` | No | Server port (default: `8000`, Railway sets automatically) |

## Connect MCP Clients

### Claude.ai

Claude.ai uses OAuth 2.0 for MCP server authentication. MemFabric includes a built-in OAuth provider that handles this automatically.

1. Go to **Settings** → **Integrations**
2. Click **Add integration**
3. Enter your server URL: `https://your-app.railway.app/mcp/`
4. Claude will initiate the OAuth flow automatically — no manual token entry needed
5. Once authorized, Claude discovers MemFabric's tools

Make sure `MEMFABRIC_SERVER_URL` is set on your server so OAuth discovery works correctly.

### ChatGPT (web)

ChatGPT supports MCP servers as external tools:

1. Open **Settings** → **Tools & integrations**
2. Click **Add tool** → **MCP server**
3. Enter your server URL: `https://your-app.railway.app/mcp/`
4. For authentication, set the header `Authorization: Bearer YOUR_TOKEN`
5. Save — ChatGPT will list the available MemFabric tools

ChatGPT will now share the same memory as all your other connected AI tools.

### Gemini (web)

Gemini supports connecting to remote MCP servers through extensions:

1. Open **Settings** → **Extensions**
2. Select **Add extension** → **MCP server**
3. Enter your server URL: `https://your-app.railway.app/mcp/`
4. Set the authorization header to `Bearer YOUR_TOKEN`
5. Enable the extension

Gemini will now be able to read and write to the same shared memory.

## MCP Tools

| Tool | Description |
|---|---|
| `start()` | Begin onboarding — learn about the user |
| `remember(filename, content, entry_date?)` | Store a memory entry |
| `list_memories()` | List all memory files with metadata |
| `read_memory(filename)` | Read a memory file |
| `update_memory(filename, content)` | Overwrite a memory file |
| `reorganize(operations)` | Merge, split, synthesize, or rename files |
| `get_rules()` | Read memory behavior rules |
| `edit_rules(content)` | Update memory behavior rules |
| `get_status()` | Check memory system health |

## Local Development

```bash
pip install -r requirements.txt
MEMFABRIC_DATA_DIR=./data python server.py
```

The server starts on `http://localhost:8000` with MCP endpoint at `/mcp/`.

## Architecture

- **Storage:** Plain `.md` files on disk. Human-readable, editable, git-compatible.
- **Retrieval:** Semantic filenames. The LLM scans filenames and decides what to read.
- **Intelligence:** Zero. The server is dumb storage. The LLM makes all decisions.
- **Auth:** OAuth 2.0 with auto-approval + static bearer token fallback. One server = one user.
