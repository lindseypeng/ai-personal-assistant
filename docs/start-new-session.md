# Start a New Session

Some Part 1 steps in the [Week 2 README](https://github.com/lindseypeng/ai-personal-assistant/blob/week-2/README.md) run once, and some run every time you work on the project:

| Step | When to run it |
|------|----------------|
| Step 1: Connect your email account | Once. Run it again only to switch accounts or if your grant expires. |
| Step 2: Start the tunnel | Every session, and again whenever it drops |
| Step 3: Start `main.py` | Every session |
| Step 4: Create the webhook | Whenever the tunnel URL changes, which is every time the tunnel restarts |
| Step 5: Test the webhook | Whenever you want to confirm emails are arriving |

If you finished Part 1 before and are coming back to test again:

1. Start the tunnel in a separate terminal and keep it open: `cloudflared tunnel --url http://localhost:8000`. If `cloudflared` isn't installed yet, run `brew install cloudflared` first (Windows: `winget install --id Cloudflare.cloudflared`).
2. Start the server: `cd app` then `uv run main.py`
3. Compare the `https://...trycloudflare.com` URL the tunnel prints with `SERVER_URL` in `.env`.
   - **Same URL:** The tunnel from your last session is still running. You're done. Send yourself an email to test.
   - **Different URL:** This is the usual case, because each new tunnel gets a new URL. Delete the old webhook under **Notifications** in the Nylas Dashboard, update `SERVER_URL`, then continue below.
4. Run `cd app/config` then `uv run config_webhook.py` to create the webhook and get a new secret.
5. Paste the secret into `WEBHOOK_SECRET` in `.env`.
6. **Restart `main.py` so it loads the new secret.**
7. Send yourself an email to test.

## Why Start and Restart `main.py`?

`main.py` is the app that receives your emails. The tunnel only forwards traffic to it, so it must be running to capture anything. It is started and restarted for two separate reasons:

- **Start `main.py` first** so it can answer Nylas's test request when you create the webhook. Without it, Nylas won't create the webhook.
- **Restart `main.py` after** because creating the webhook gives you a new secret. `main.py` reads `.env` only when it starts, so it needs a restart to load the new secret and stop rejecting emails with `401`.

When your tunnel URL stays the same and you don't create a new webhook, neither applies. You just start `main.py` once and it works.

If it still doesn't work, see the [Webhook Troubleshooting Guide](webhook-troubleshoot-guide.md).
