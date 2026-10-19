# Installation And Providers

## 1. Local Application

Run the Node.js application using the commands in `../README.md`. Install TeX
Live, MacTeX or TinyTeX separately, with the packages needed by your manuscript.
Confirm `git --version`, `node --version`, and `pdflatex --version` work in the
same environment that starts the app. No existing paper or restored database is
needed: import the demo or your own Overleaf Source ZIP.

All commands here run at the repository root. No container runtime is required.

## 2. Providers

The default `AI_PROVIDER=codex` uses the installed, authenticated native Codex
client. `OPENAI_MODEL` selects its model. Native account names do not mean offline
inference, free usage, or unlimited context.

API configuration uses `AI_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
`OPENAI_MODEL` and `AI_API_FORMAT`. Choose a channel that supports ordinary API
requests; an upstream restricted to a native client is not made compatible by
changing its model name.

Optional review providers are loaded from `REVIEW_PROVIDER_FILE`, defaulting to
`~/.config/autopaperreview/tokenhub.json`. Example shape, with placeholders only:

```json
{
  "baseURL": "https://tokenhub.tencentmaas.com/v1",
  "apiKey": "REPLACE_LOCALLY",
  "models": [{"id": "provider-model-id", "name": "Your review model"}]
}
```

This registry currently validates the TokenHub origin specifically; arbitrary API
origins instead use the primary provider environment variables above.
Store it outside the repository with mode `0600`. The UI exposes available
reviewer choices. Inspect `server/peer-review.mjs` and
`server/revision-provider.mjs` before enabling collaboration. `REVISION_REVIEWER`
selects a configured reviewer, `REVISION_COWRITER_MODEL` enables a supported
co-writer, `REVISION_COWRITER_AUTH=local` keeps native Claude credentials local,
and `REVISION_CROSSCHECK_MODEL` selects the final Codex check. Native Claude must
already be authenticated and available on PATH. Local-auth mode must bind the
backend to loopback, not a public shared listener. Do not infer availability of
DeepSeek or Claude versions from historical IDs in the code. Provider failures
must be resolved with that provider; no automatic paid fallback is promised.

## 3. Generate Private Team Configuration

First choose an HTTPS gateway URL from your domain/reverse proxy or tunnel.
The URL must point to the remote gateway's port 4318, not the local model backend.

```sh
node deploy/init-pull-config.mjs https://papers.example.com team
```

This creates `~/.config/autopaperreview/team-bridge.json` and a private
`team-login.txt`, both mode `0600`. Existing config is never overwritten. Read
the generated login file locally and share login details securely with teammates.
The bridge file contains a separate queue token and password hash, not any native
model credentials. Never commit either file. Use a different username if desired.

## 4. Remote Linux Gateway

On the remote server, clone this branch, then:

```sh
cd EVA-Mimir
npm ci
npm run build
mkdir -p "$HOME/.config/autopaperreview/queue"
chmod 700 "$HOME/.config/autopaperreview/queue"
```

Transfer only the generated `team-bridge.json` to the remote private directory
over a secure channel. Do not transfer `~/.codex`, `~/.claude`, model keys, or your
whole home directory. Run the gateway as a dedicated unprivileged user with
access to its private configuration and queue directory.

```sh
TEAM_GATEWAY_BIND=127.0.0.1 \
TEAM_QUEUE_DIR="$HOME/.config/autopaperreview/queue" \
node deploy/run-team-bridge.mjs --remote
```

Point your HTTPS reverse proxy/tunnel at `http://127.0.0.1:4318`. Preserve the
public Host header. The configured `access.origin` must exactly match that public
HTTPS origin. Configure your proxy to allow the intended ZIP body size and at
least 60 seconds response time. The application queue has a 128 MiB body limit.
Do not expose port 4317 or worker credentials to the public internet.

## 5. Start The Outbound Worker

On the local executor machine, with the application already running on 4317:

```sh
node deploy/run-pull-worker.mjs
```

On macOS, optionally install the worker LaunchAgent:

```sh
node deploy/install-pull-worker.mjs
```

This installs only the worker; keep the application running separately under your
preferred service manager. On Linux, run the same worker command using a private
systemd user service with a suitable HOME. Exactly one worker process should own
the receipt directory. Four internal slots transport requests; project locks still
prevent simultaneous AI writers for the same paper.

Login from a fresh browser, check the executor status, import a demo, and verify
PDF compilation. Submit a small explicit comment only after confirming provider
costs and consent. A queue receipt means delivery, not successful paper revision.
Check the revision log and compiled PDF before calling the work complete.

## Recovery

The worker log on macOS is `~/.config/autopaperreview/logs/pull-worker.err`.
Receipts live under `~/.config/autopaperreview/execution-receipts`. Keep the local
workspace and remote queue backed up. Do not delete receipts to retry uncertain
paid operations. If your tunnel URL changes, update `access.origin` in both private
configuration copies and restart the gateway and worker. The browser itself needs
only the team login, never a native model login or ZeroTier installation.
