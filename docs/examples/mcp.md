# MCP server (Claude Desktop / claude.ai web)

Voli ships an [MCP](https://modelcontextprotocol.io) server so you can talk
to your local Voli installation **directly from Claude Desktop or claude.ai
web** — no terminal needed. Claude sees the seven tools (the same set
`voli llm-ask` uses), calls them when relevant, and answers in chat
grounded in live Polygon data.

## Install the optional extra

```bash
poetry install -E mcp
```

## Confirm the server runs

```bash
poetry run voli mcp-serve --help
```

```text
usage: voli mcp-serve [-h] [--raw-only]

options:
  -h, --help  show this help message and exit
  --raw-only  Expose only the four raw Polygon tools (skip the analytics layer).
```

The server itself communicates over stdio (the format Claude Desktop
expects). It blocks until the client disconnects.

## Wire it into Claude Desktop

=== "macOS"

    Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "voli": {
          "command": "poetry",
          "args": ["run", "voli", "mcp-serve"],
          "cwd": "/absolute/path/to/voli",
          "env": {
            "POLYGON_API_KEY": "pk_your_key_here"
          }
        }
      }
    }
    ```

=== "Windows"

    Edit `%APPDATA%\Claude\claude_desktop_config.json` with the same
    structure (use Windows-style paths in `cwd`).

=== "Linux"

    Edit `~/.config/Claude/claude_desktop_config.json` with the same
    structure.

Replace `cwd` with the path where you cloned Voli. Restart Claude Desktop
after saving — the Voli tools will appear in the **Available Tools**
panel.

## Wire it into claude.ai web (custom integrations)

claude.ai now supports remote MCP integrations via the **Settings →
Connectors** page. Until your Voli install is reachable from the public
internet you have two options:

1. **Local-only** — use Claude Desktop, which connects to local stdio
   servers like the one above.
2. **Tunnel it** — expose your local server with `ngrok http 8000` (or
   similar) and point a Connector at the tunnel URL. The MCP SDK supports
   HTTP transport too; if you'd like the Voli server to listen on HTTP
   instead of stdio, file an issue and we'll wire `voli mcp-serve --http
   PORT`.

## What Claude sees

Once connected, Claude has access to the same seven tools as `voli llm-ask`:

**Analytics (preferred):**

- `compute_atm_iv_term_structure` — front + next ATM IV, ATM strike, IV diff.
- `compute_skew_slope` — OLS slope of IV vs strike for one expiry.
- `get_atm_greeks` — ATM contract greeks for one expiry.

**Raw Polygon tools:**

- `get_underlying_snapshot`
- `list_option_contracts`
- `get_option_quotes`
- `get_option_greeks`
- `get_ticker_news` — recent headlines tagged to a ticker, newest-first.
  Useful when the model needs to explain *why* IV is elevated or what
  catalysed a price move.

Drop the analytics tools (`voli mcp-serve --raw-only`) if you want Claude
to chain the primitives itself — useful for exploring how the model
reasons over the chain.

## Sample chat

In Claude Desktop, type:

> What does NVDA's ATM IV term structure look like right now?

Claude calls `compute_atm_iv_term_structure(ticker="NVDA")`, gets the
front + next IV + ATM strike, and answers something like:

> NVDA's ATM IV is around 33.18% for this Friday's expiry and 34.57% for
> next week's, a 1.39 vol-point increase. The ATM strike is 200, right at
> spot ($199.84). The slight upward slope front-to-next is consistent
> with mild near-term event risk being priced in.

You'll see the **tool call indicator** in the Claude Desktop UI showing
the tool name and inputs as it runs.

## Privacy / cost notes

- The MCP server runs entirely on your machine. Claude sees only the tool
  results you allow it to fetch.
- Each tool call uses your Polygon API quota the same way `voli ask` does.
  The `~/.voli/cache.sqlite` cache is shared, so repeated questions about
  the same chain within the TTL are free.
- No Voli data leaves your machine except via the tool results you return
  to Claude.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tools don't appear in Claude Desktop | wrong `cwd` or `command` | Check the absolute path; run `poetry run voli mcp-serve` from a terminal first to confirm it boots. |
| `Missing POLYGON_API_KEY` errors mid-chat | `env` block in config missing the key | Add `POLYGON_API_KEY` under `env` in `claude_desktop_config.json` (or move it into your shell env). |
| Server starts but tools error out | stale cache | `rm ~/.voli/cache.sqlite` and reload Claude Desktop. |
| `ImportError: MCP server requires the 'mcp' package` | lean install | `poetry install -E mcp`. |

## See also

- [LLM-driven agent](llm-ask.md) — same tools, called via our CLI loop.
- [Architecture: caching](../architecture/caching.md) — how the cache the MCP server shares with `voli ask` is keyed.
