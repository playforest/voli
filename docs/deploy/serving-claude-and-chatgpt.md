# Serving voli to Claude.ai and ChatGPT

Voli's HTTP server (`voli serve`) hosts the same tool catalogue on two
protocols at once:

- `/mcp` for Claude.ai's Custom Integrations and any other MCP-aware
  client. Streamable-HTTP transport.
- `/openapi.json` plus `/tools/<name>` for ChatGPT Custom GPT Actions
  and any OpenAPI 3.1 consumer.

Both surfaces sit behind one bearer-token auth check, and both dispatch
to `voli.llm.tools.build_default_tools()`, so adding a new tool to voli
exposes it to every client at once.

This page covers the protocol surface and the per-provider connector
configuration. The actual hosting setup (DigitalOcean, HTTPS, etc.) is
in [DigitalOcean walkthrough](digitalocean.md).

## Run the server

```bash
export VOLI_AUTH_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
export POLYGON_API_KEY=pk_your_polygon_key

poetry run voli serve --port 8080 --server-url https://voli.example.com
```

Flags worth knowing:

| Flag | Effect |
| --- | --- |
| `--host` | Interface to bind. Default `0.0.0.0` (all interfaces). Use `127.0.0.1` to restrict to localhost. |
| `--port` | Port. Default `8080`. |
| `--server-url URL` | Public URL, embedded in `/openapi.json` so ChatGPT calls back to the right host. Required for ChatGPT; optional locally. |
| `--no-auth` | Disables the bearer-token check. Local development only. The CLI prints a loud stderr warning if you flip this. |
| `--raw-only` | Drops the analytics shortcut tools, leaving only the four primitives. |

The server refuses to start when `VOLI_AUTH_TOKEN` is unset and
`--no-auth` isn't passed. That's deliberate: an unauthenticated public
deploy lets strangers run up your Polygon bill.

## Endpoints

| Path | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/healthz` | GET | public | Liveness probe for load balancers and uptime monitors. |
| `/openapi.json` | GET | bearer | OpenAPI 3.1 spec describing every `/tools/<name>` route. |
| `/tools/<name>` | POST | bearer | Calls one tool with the JSON body as arguments; returns the tool's JSON output. |
| `/mcp` | GET / POST | bearer | Streamable-HTTP MCP. Spec-compliant; clients negotiate session and stream over SSE. |

## Connect Claude.ai

1. Open https://claude.ai → Settings → Connectors → Add custom integration.
2. Enter your server's `/mcp` URL, e.g. `https://voli.example.com/mcp`.
3. For authentication, choose Bearer Token and paste the value of
   `VOLI_AUTH_TOKEN` from the server.
4. Save. Voli's tools appear in every Claude.ai conversation.

A successful connection means Claude can call the analytics tools
(`compute_atm_iv_term_structure`, `compute_skew_slope`,
`compute_atm_greeks`) and the four primitives (`get_underlying_snapshot`,
`list_option_contracts`, `get_option_quotes`, `get_option_greeks`)
mid-conversation.

## Connect ChatGPT

ChatGPT consumes voli through a Custom GPT with Actions. You build the
GPT once, then chat with it directly or use it from inside any normal
ChatGPT chat (depending on your plan).

1. Go to https://chatgpt.com/gpts/editor and create a new GPT.
2. Under Configure → Actions → Create new action.
3. In Schema, click Import from URL and paste
   `https://voli.example.com/openapi.json`. ChatGPT fetches the spec
   and lists every voli tool as a callable function.
4. Under Authentication, choose API Key → Auth Type: Bearer, then paste
   the `VOLI_AUTH_TOKEN` value.
5. Save.

If the import fails, the most common causes are: the server isn't
publicly reachable yet, the OpenAPI spec was generated without
`--server-url` and so has no `servers` block, or the auth token has a
typo. The Custom GPT Actions UI shows the response from the import
attempt; check there first.

## Tool surface visible to both providers

Both `/mcp` and `/openapi.json` describe the exact same set of
operations because they're generated from
`voli.llm.tools.build_default_tools()`. A new tool added to voli
appears in both surfaces simultaneously after a server restart.

## Rotating the bearer token

To rotate:

1. Generate a new token:
   ```bash
   python -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```
2. Update `VOLI_AUTH_TOKEN` on the server and restart `voli serve`.
3. Update the token in Claude.ai's connector and the ChatGPT Custom
   GPT's Action authentication.

Old token is rejected from the moment the server restarts; in-flight
requests with the old token receive a 401.

## See also

- [Poking around the server](poking.html): a copy-paste cookbook of
  `curl` and shell commands for inspecting every endpoint. Self-contained
  HTML with a sepia theme and a dark-mode toggle; open it directly from
  the repo or browse it on the deployed docs site.
- [DigitalOcean deploy walkthrough](digitalocean.md): provisioning the
  droplet, getting an HTTPS URL, running the server as a systemd unit.
- [Extending Voli: data providers](../extending/data-providers.md): how
  to add yfinance / Tradier / etc. so the served tools cover non-Polygon
  vendors.
