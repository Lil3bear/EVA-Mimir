# Mimir Pi Writing

Local prototype built on the pinned autoresearch-v0 website (15099a7).
Pi itself is not modified. Existing website installations and their data are not used.

## Open

After installing this directory with `pi install /absolute/path/to/mimir-pi`,
restart Pi or run `/reload`, then enter:

```text
/mimir https://git@git.overleaf.com/PROJECT_ID
```

Pi opens a loopback-only browser workspace. Confirm the trusted source in the
Git import dialog. Existing Git credential helpers are used; otherwise enter the
Overleaf Git token only in that local dialog. Tokens are stored separately from
manuscript snapshots and model sessions. No remote push happens on import.
Only one writing service may own the data directory; other Pi sessions reuse its
link instead of opening a competing writer. The service stops when its owning
Pi session shuts down. `npm run writing` starts the
same workspace independently of the TUI.

## Model and Skills

The writer uses the local **DeepSeek Harness** as its model backend. Each request
runs one `dsh headless` session with tools disabled and the selected repository
skill contents in the prompt. JSON patches still go through the website's
location, current-version and compilation checks.

Authentication belongs to DSH: it reads the Harness credential store
(`~/.dsh/.credentials.yaml`) and does not need a separate key in this package.
The model name is taken from
`~/.config/autopaperreview/deepseek-official.json` when present, otherwise
`deepseek-flash`; the file's `apiKey`, if any, is not used for model calls.
Model failures do not select another provider. The user's global default model
and running DSH sessions are not changed.

## Personal Trajectory

Private data is under `~/.local/share/mimir-pi/`:

- `<project-id>/source-history.git`: accepted source snapshots and provenance.
- `experience/events.json`: comments, requests, candidates, rejections, application
  outcomes, manual edits, restore events and skill manifests.
- `experience/experience.md`: human-readable export at `/api/experience`.
- `pi-sessions/`: legacy Pi request/response sessions from earlier builds.
- `~/.dsh/sessions/`: DSH headless sessions used by the current backend.

Back up the entire data directory. Overleaf Git alone is not the trajectory:
it does not contain unpushed edits, rejected candidates, feedback or all model
requests. Automatic application is not evidence of human preference. Raw logs
are private data, not trusted instructions or automatically generated Skills.
No desktop-wide activity or hidden model reasoning is captured.

LaTeX compilation is not a hostile-code sandbox. Import only trusted projects.
This prototype does not automatically distill or activate Skills.

For CVPR review builds, use lineno 5.9 or newer: 5.7 has a known two-column
margin-switching bug. The compiler runs four LaTeX passes, including a final
stabilization pass after bibliography/layout updates. This does not modify the
manuscript or its conference style file.

Validation note: local package loading, browser import UI, source compilation and
unit/integration tests are checked separately from live model availability.
The first real Pi/DeepSeek smoke request returned HTTP 402 (insufficient balance).
A user-authorized retry subsequently completed a demo revision, compilation,
Git commit and trajectory export. User-authorized Overleaf token authentication,
source import and local PDF compilation were subsequently verified as well.
See `LOCAL-VALIDATION.md`; a smoke-test approval is not user preference evidence.
The dependency audit still flags the upstream Zod 3 dependency (GHSA-mrhx-c7xc-m3w5).
Non-breaking dependency fixes were applied; a Zod major migration was not attempted.
Keep the service on loopback and do not expose it as a public upload service.
