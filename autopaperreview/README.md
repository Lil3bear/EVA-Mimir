# Autopaperreview / Autoresearch v0

An Overleaf-source workspace for reading papers, adding PDF comments, revising
LaTeX with local model clients, compiling PDFs, and inspecting revision history.
This directory is self-contained; the other EVA-Mimir directories are unchanged.

## Features

- Import a trusted Overleaf source ZIP, compile and scroll through its PDF.
- Select text for translation and comments; revise the corresponding TeX source.
- Evidence-grounded writing, review, rebuttal, citation and figure skills.
- Native Codex / Claude Code adapters and configurable API review providers.
- Validate patches and compile before publication; retain comments that were not
  actually addressed. Record model provenance and source Git history.
- Optional Overleaf Git push, independent of internal version history.
- Remote team login and a persistent queue polled by your local executor over
  HTTPS. Visitors do not need ZeroTier or a model client on their own computers.

## Install Locally

Requirements: Node.js 22, npm, Git, and a TeX installation (`pdflatex`, `xelatex`
or `lualatex`, plus `bibtex` as required by your paper). The app reports missing
TeX packages rather than fabricating a PDF. For ACM papers, install the template's
dependencies in your TeX distribution, including `textcase` when required.

```sh
git clone --branch autoresearch-v0 https://github.com/Lil3bear/EVA-Mimir.git
cd EVA-Mimir/autopaperreview
npm ci
npm run build
```

Install and authenticate the native Codex CLI separately when using the default
provider. Its credentials stay in your native client configuration. Select a
model your account actually supports; a model ID in this code is not a guarantee
that a provider offers it.

```sh
AI_PROVIDER=codex OPENAI_MODEL=gpt-6.1-sol \
LOCAL_REVISION_ONLY=1 ARCHIVE_APPLIED_COMMENTS=1 SETTINGS_LOCKED=1 \
NODE_ENV=production BIND_HOST=127.0.0.1 PORT=4317 \
DATA_DIR="$HOME/.local/share/autopaperreview-data" node server/index.mjs
```

Open <http://localhost:4317>. Import a demo first, then a trusted Source ZIP.
The top book icon opens the illustrated guide at `/guide/index.html`.
Development mode: `npm run dev`. This starts the backend and Vite integration.

For a standard compatible API, set `AI_PROVIDER=openai`, `OPENAI_BASE_URL`,
`OPENAI_API_KEY`, `OPENAI_MODEL`, and `AI_API_FORMAT` (`responses` or `chat-json`).
Supply credentials through your own private environment/configuration, never in
committed files. Native Claude and multi-provider configuration are described in
[installation and providers](docs/INSTALL.md). No expensive fallback is enabled
merely by deploying the queue.

## Share With A Team

Follow [docs/INSTALL.md](docs/INSTALL.md) for the Linux gateway, private config,
HTTPS reverse proxy/tunnel, and the Mac/Linux outbound worker. The architecture is:

```text
Browser -> authenticated HTTPS gateway -> persistent remote queue
                                           ^
                                           | local worker polls HTTPS
                                           v
                              local application and native model clients
                              -> TeX -> compilation -> logs and Git versions
```

The source of truth stays on the executor machine. Keep it awake and connected.
Unclaimed writes expire after 24 hours; uncertain executions are not blindly
replayed. Temporary tunnels and a single personal computer are not high
availability. See [delivery guarantees](deploy/PULL-EXECUTION.md).

## Test

```sh
npm test
npm run build
npx playwright install chromium
node scripts/guide-screenshots.mjs
```

Compilation tests need TeX on PATH. Tests use isolated data directories and mock
model responses. Some optional smoke scripts can call configured models; inspect
them before running, as those calls may be billable.

The ten-user load harness runs against an isolated copy with a mock model:

```sh
LOAD_PROJECT_DIR=/absolute/path/to/data/project-uuid \
LOAD_TEX_FILE=main.tex node scripts/team-load-test.mjs
```

It requires an existing compiled trusted project. Never point other smoke tools
at a private production paper without reviewing their effects.

## Included And Excluded

Included: frontend, backend, model adapters, queue/worker, tests, dependencies lock,
skills and reference Markdown, vendored licensed review prompts, Docker files,
generic installation instructions and a credential-free illustrated guide.

Not published: papers, PDFs, comments, revision databases, Git credentials, model
keys, native client sessions, private team passwords, runtime directories, build
artifacts, and one-off scripts targeting the author's private manuscript or server.
The private operational manual is deliberately replaced by the safe public guide.

Respect the licenses and attribution in [ATTRIBUTION.md](ATTRIBUTION.md) and
`vendor/`. Ding Xiaohan's macro structure, micro readability and rebuttal rules
are independently summarized with source links in their respective skills; the
original articles are not reproduced. No new license is asserted for upstream
EVA-Mimir files by this addition.

## Security And Backup

Only import trusted LaTeX. Compilation is not a hardened sandbox for hostile
multi-tenant uploads. Team authentication is shared, not per-user isolation.
Do not expose the local backend directly. Back up the local `DATA_DIR`, source
Git history, private credential directory and gateway queue volume. PDF/source
exports alone are not full backups. Review revisions before pushing to Overleaf.
