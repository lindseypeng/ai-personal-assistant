# Nylas Webhook Troubleshooting Guide

## What You're Setting Up

In this part of the project, you connect your local development server to Nylas using a webhook. A webhook is how Nylas notifies your app in real time when new emails arrive.

Your local machine isn't publicly accessible from the internet, so we use a **tunnel** ([Cloudflare Tunnel](https://github.com/cloudflare/cloudflared)) to temporarily expose your local port 8000 at a public URL. Nylas sends its webhook events to this public URL, which forwards them to your local app.

This setup is temporary and meant for testing during development. In production, you'd deploy the app to a server with a fixed URL.

## The Goal

Nylas should deliver events to your `/events` endpoint without a `401 Unauthorized` error. When everything works:

- The webhook is listed under **Notifications** in the Nylas Dashboard
- `WEBHOOK_SECRET` in `.env` matches the secret Nylas generated
- The `main.py` terminal shows a `200` response when an email arrives
- `http://localhost:8000` lists the new message

## Reset Checklist: Webhook Stops Working

The webhook becomes invalid once the tunnel URL expires or changes. Most problems are fixed by following these steps in order:

1. Stop any running `main.py` processes.
2. Delete the old webhook in the Nylas Dashboard under **Notifications**.
3. Clear `SERVER_URL` and `WEBHOOK_SECRET` in `.env`.
4. Start the tunnel in a separate terminal and keep it open:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

5. Copy the `https://...trycloudflare.com` URL it prints into `SERVER_URL` (**use the HTTPS URL, not HTTP**).
6. Start the server: `cd app` then `uv run main.py`.
7. In another terminal, create the webhook: `cd app/config` then `uv run config_webhook.py`.
8. Copy the printed secret into `WEBHOOK_SECRET`.
9. Stop the `main.py` server and start it again with `uv run main.py` so it loads the new secret.
10. Send yourself an email and watch the `main.py` terminal for a `200` response.

## Common Issues and Fixes

### 1. Environment Variables Not Loading

**Symptoms:** You get a `401 Unauthorized` error, or the app doesn't pick up a new `SERVER_URL` or `WEBHOOK_SECRET`.

**Fix:**

- `app/main.py` calls `load_dotenv(override=True)`, so `.env` always wins over old values. Restart `main.py` after every `.env` change.
- `app/config/config_webhook.py` and `app/config/config_auth.py` use plain `load_dotenv()`, which does **not** override variables already set in your terminal. If you ever ran `export SERVER_URL=...` or similar, open a new terminal before running them.
- If values still look stale, restart your IDE (VS Code or Cursor) to clear cached environment variables.

### 2. Expired or Changed Tunnel URL

**Symptoms:** Emails arrive but nothing reaches `main.py`, or the tunnel terminal stopped.

The free Cloudflare quick tunnel needs no account, but it gives you a new random URL every time `cloudflared` starts. It is meant for testing, so it can also drop after your laptop sleeps or your network changes. Nothing in the app shows an error when this happens. Emails keep arriving in your inbox, but Nylas can no longer reach `main.py`.

**How to tell the tunnel is down:**

- The tunnel terminal has returned to a normal prompt, or shows connection errors.
- You send yourself an email, and no `POST /events` line appears in the `main.py` terminal.
- No new email appears at `http://localhost:8000`.
- The webhook under **Notifications** in the Nylas Dashboard shows a failing or inactive status.

**How to check it:** Replace the URL with your `SERVER_URL` and run:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://your-tunnel-name.trycloudflare.com
```

- `200` means the tunnel and `main.py` are both working.
- Any other code, or a connection error, means the tunnel or `main.py` is down. Check that both terminals are still running.
- Right after starting a tunnel, the new URL can take up to a minute to work. Wait and try again before assuming it's broken.

**Fix:** Restart the tunnel, then follow the [Reset Checklist](#reset-checklist-webhook-stops-working) above, since the new tunnel has a new URL. Delete the old webhook each time you create a new one.

If Cloudflare is unavailable, you can use [Pinggy](https://pinggy.io/) as a backup. Its free URLs expire after 60 minutes:

```bash
ssh -p 443 -R0:localhost:8000 free.pinggy.io
```

On Windows, replace `localhost` with `127.0.0.1`.

### 3. Firewall or VPN Interference

**Symptoms:** The tunnel command can't connect, or the webhook fails to verify.

**Fix:**

- Temporarily disable antivirus, firewall, or VPN software
- On a corporate or school network, try a personal hotspot instead

### 4. Webhook Secret Mismatch

**Symptoms:** The webhook registers, but requests to `/events` return `401`.

**Fix:**

- Make sure `WEBHOOK_SECRET` in `.env` exactly matches the secret printed by `config_webhook.py`, with no extra spaces or quotes
- Restart `main.py` after updating `.env`
- If it still fails, delete the webhook, create it again manually in the Nylas Dashboard, and copy that secret into `.env`

### 5. Port Conflicts

**Symptoms:** `main.py` fails to start with an "address already in use" error, or the tunnel can't forward requests.

**Fix:**

1. Find what is using port 8000 with `lsof -i :8000` (macOS or Linux) and stop it, or close old `main.py` terminals.
2. If you need a different port, change `port=8000` at the bottom of `app/main.py` (for example to `8085`).
3. Use the same port in the tunnel command:

   ```bash
   cloudflared tunnel --url http://localhost:8085
   ```

4. Then follow the [Reset Checklist](#reset-checklist-webhook-stops-working) to register a webhook for the new URL.

The port is set in code, not in `.env`.

## Notes from the Community

- Some Windows users needed `127.0.0.1` instead of `localhost` in tunnel commands
- Nylas blocks ngrok URLs, so don't use ngrok
- If you see `500` errors, check that your Pydantic models allow optional fields (for example `snippet: Optional[str] = None`)
- In VS Code or Cursor, restart the terminal after updating `.env`
