# DigitalOcean walkthrough

This page is a placeholder for the full deploy walkthrough that lands in
Phase C. The runtime code (Phase A) and the container packaging
(Phase B, `Dockerfile` + `docker-compose.yml`) are ready; what's missing
is the infrastructure-side recipe (provisioning the droplet, getting
HTTPS, running the container as a service).

For now, the protocol-level documentation lives in
[Serving Claude.ai and ChatGPT](serving-claude-and-chatgpt.md), which
covers running `voli serve`, the endpoint surface, and per-provider
connector configuration. For inspecting a running server (local or
deployed) with `curl`, see the standalone
[poking cookbook](poking.html).

## What this page will cover when filled in

1. **Provision a droplet**
   - Create a DigitalOcean account and add an SSH key.
   - Spin up a `s-1vcpu-1gb` droplet in `nyc1` with the Docker
     marketplace image.
   - Lock down SSH (key-only, fail2ban, ufw allow 22 / 80 / 443).

2. **Get the code onto the box**
   - `git clone https://github.com/playforest/voli`.
   - Build the Docker image with the bundled `Dockerfile`, or
     `docker compose up --build` to use the bundled `docker-compose.yml`.
   - Configure secrets via `.env.deploy` (see [`.env.deploy.example`](https://github.com/playforest/voli/blob/main/.env.deploy.example)).

3. **Public URL with HTTPS**
   - Two options:
     - Bring your own domain: point an A record at the droplet IP, run
       Caddy as a reverse proxy. Caddy auto-issues Let's Encrypt
       certs; ~10 lines of `Caddyfile`.
     - No domain: run a Cloudflare Tunnel from the droplet. Cloudflare
       hands you a public hostname under their domain with HTTPS
       included; nothing to configure on the droplet's network.

4. **Run as a service**
   - Recommended: `docker compose up -d` from the repo root. The bundled
     `docker-compose.yml` already sets `restart: unless-stopped` and
     declares a named volume for `/var/voli`.
   - Alternative: systemd unit running the container directly, with the
     `--restart=unless-stopped` flag and journald for logs.
   - Set `VOLI_SERVER_URL` (or pass `--server-url`) to the public HTTPS
     URL so the OpenAPI spec advertises the right host.

5. **Connect the providers**
   - Follow [Serving Claude.ai and ChatGPT](serving-claude-and-chatgpt.md).

6. **Cost-down-when-idle**
   - Snapshot the droplet, destroy it, restore on demand. Snapshot
     storage is ~$1/month; restore takes ~5 minutes.
   - Or: hourly billing means a one-evening test costs ~$0.05. Don't
     keep the droplet running 24/7 if you only use voli during US
     market hours.

Track Phase C progress in the project's task list / commits.
