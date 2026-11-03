# Local Validation

Date: 2026-11-02 (America/Los_Angeles).

## Installed

- Pi 0.85.1, Node 22.22.0.
- Local package registered through `pi install` in user scope.
- Pi RPC `get_commands` lists `/mimir` from this package.
- Invoking `/mimir <Overleaf Git URL>` opens a loopback browser URL with the Git
  import form prefilled. Import still requires explicit source trust.
- Existing global default (`yescode`, `gpt-5.5`) and SoL-Pi registration retained.
- Existing Autopaperreview installation and manuscript data were not modified.
- Isolated private data root: `~/.local/share/mimir-pi/`, permissions 0700.
- Writer Pi settings use the official DeepSeek endpoint and an environment-key
  reference, not a persisted API key or a key on the command line.

## Verified

- Production frontend build.
- Regression suite: 154 tests, including a deterministic Pi CLI fixture that
  exercises propose, reject, accept, real TeX compilation, Git diffs, trajectory
  links and restore. The fixture is not a real-model quality evaluation.
- Desktop and mobile Git import UI; no page errors or mobile horizontal overflow.
- Multiple Pi sessions reuse one data-directory owner instead of starting
  competing writers. Closing a non-owner does not terminate the shared service.
- Owner shutdown closes its web service and cancels active Pi requests.

## CVPR Review Line Numbers

- The original native PDF reproduced inner-gutter line numbers, ruling out a
  browser text-layer issue. The installed lineno 5.7 matches upstream issue #26.
- Backed up the old package to `~/.local/share/mimir-pi/tex-backup/` and the old
  PDF to `~/.local/share/mimir-pi/cvpr-before.pdf`.
- Updated the TeX package manager infrastructure as required, then only lineno
  (5.7 -> 5.9). No TeX kernel or conference style file was changed.
- A three-pass build still misplaced some column-boundary numbers. A fourth
  LaTeX pass fixed those positions, so the compiler now includes that pass.
- Verified the rebuilt 11-page PDF: all 833 line-number text objects lie in the
  outer margins, with none in the text-column/gutter band. Inspected rendered
  pages and added a native two-column line-number regression test.
- Manuscript revision and source Git head are unchanged. No Overleaf push occurred.
- Upstream evidence: https://github.com/latex-lineno/lineno/issues/26 and
  https://github.com/latex-lineno/lineno/issues/30.

## Live Checks And Remaining Blockers

- The first real Pi writing request returned HTTP 402, insufficient balance.
  After the user reported the account was ready, a new explicitly requested smoke
  run succeeded with `deepseek-flash` through the installed Pi CLI. It generated
  a demo-only proposal, retained it pending approval, then the test accepted it,
  compiled the changed source and verified the Git diff and trajectory records.
  Commit: `d825efa8ab996611ac9baacbb1c827c8484991e6`.
  This test approval is not a personal preference signal from the user.
  No model fallback or remote push was performed.
- Credential-free Git attempts initially failed. After the user explicitly
  authorized using their supplied token, the project imported successfully:
  21 supported source/assets files, with an initial local Git snapshot. The token
  is stored in the separate AES-GCM credential store with mode 0600; it was not
  put into the Git remote URL, manuscript data or experience log.
  The imported `main.tex` compiled to an 11-page PDF, verified in the browser.
  Automatic push remains disabled. No remote paper was changed or pushed, and
  no browser cookies were read. Because the token appeared in chat, rotating it
  afterwards remains recommended.
- Automatic skill distillation and desktop-wide activity recording are not
  implemented. Git snapshots alone do not contain rejected candidates or intent.
- The upstream Zod 3 dependency still has a high-severity audit advisory;
  non-breaking fixes for the other reported dependencies were applied. Keep this
  prototype local and import only trusted LaTeX.
