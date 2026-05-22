# cara-mcp — CARA Model Context Protocol server

Espone l'API REST di CARA come MCP server, così Claude Desktop /
Claude Code / qualsiasi LLM-client MCP-compatibile può interagire con
i dati e le funzioni di CARA via tool calls.

## Cosa fa (M0 scaffold)

- 3 tool dimostrativi: `list_tasks`, `add_task`, `list_shopping`
- Auth via long-lived API token (separato dal JWT user-facing)
- Trasporto: stdio (Claude Desktop) + HTTP/SSE opzionale per client web

## Architettura

```
Claude Desktop ──┐
Claude Code     ──┤   stdio   ┌─────────────┐    HTTP    ┌──────────────┐
Future agents    ──┴─────────►│ cara-mcp    │───────────►│ cara-backend │
                              │ (FastMCP)   │   /api/v1  │ (FastAPI)    │
                              └─────────────┘            └──────────────┘
```

cara-mcp è un **wrapper sottile**: non duplica logica, traduce tool
calls MCP in chiamate HTTP REST al backend esistente. Auth: API
token in env CARA_MCP_TOKEN, passato come Bearer.

## Esecuzione locale (dev)

```bash
cd mcp-server
uv sync
uv run python -m cara_mcp --transport stdio
```

## Integrazione Claude Desktop

In `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cara": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/opt/cara/mcp-server",
        "python", "-m", "cara_mcp",
        "--transport", "stdio"
      ],
      "env": {
        "CARA_API_BASE": "https://192.168.1.23:8455/api/v1",
        "CARA_MCP_TOKEN": "..."
      }
    }
  }
}
```

## Tool roadmap

| Tool | Stato | Backend endpoint |
|------|-------|------------------|
| list_tasks | ✅ M0 | GET /tasks |
| add_task | ✅ M0 | POST /tasks |
| list_shopping | ✅ M0 | GET /shopping |
| add_shopping | M1 | POST /shopping |
| list_reminders | M1 | GET /reminders/upcoming |
| add_reminder | M1 | POST /reminders |
| search_memory | M2 | GET /memory/facts |
| query_persona | M2 | GET /persona/me |
| chat_with_cara | M3 | POST /chat (SSE → first chunk only) |
| smarthome_execute | M3 | POST /smarthome/execute |
| list_today | M3 | GET wall/summary |

## Sicurezza

- **API token rotabile** lato admin in `/admin/mcp/tokens` (futuro).
  Per ora env var.
- **Scope tool**: ogni token può essere limitato a un sottoinsieme
  di tool (M1).
- **Audit log**: ogni tool call scrive entry su `audit_log` con
  `actor='mcp:<token_label>'`, `action='mcp.tool.<name>'`.
- **Rate limit**: 60 req/min per token (Redis sliding window).

## NON-goals (deliberati)

- Niente MCP client (CARA che chiama altri MCP server). Overengineering
  per ora.
- Niente write su `users`, `families`, `admin_settings`. Tool MCP sono
  read+per-user-write, mai admin.
- Niente accesso diretto al DB: tutto via HTTP REST del backend, così
  l'auth + audit log esistente fa lavoro.
