# OCR-008D — GitHub Release Preparation

## Git audit

The working branch is `feat/ocr-001`. After `git fetch origin --prune`, both
remote branches match their local counterparts at their published tips:

- `main` and `origin/main` point to the same commit;
- `origin/feat/ocr-001` remains at the initial project architecture commit;
- the local feature branch contains nine unpublished commits, from the OCR-004
  checkpoint through Docker packaging.

The deployment image was built from the Docker packaging commit. A read-only
checksum comparison of the Docker, Compose, dependency and diagnostic-client
files confirms that the running deployment matches `a87fe63`. The additional
diagnostic-resilience fix in this release-preparation working tree has not been
deployed; publishing it must not be mistaken for a production rollout.

## Security audit

The publishable commit range was checked for tracked `.env`, SQLite databases,
user documents, raw OCR fixtures, private-key fingerprints and common API/token
formats. No credential or user-data artifact was found.

The only assignment-pattern findings are deliberately non-secret test values
and documented placeholders. `.env.example` is tracked with empty values.
`.gitignore` excludes `.env`, local state, diagnostics, samples, OCR fixtures
and generated artifacts; `.dockerignore` excludes the same runtime data from
the build context.

Two local deployment/incident reports are deliberately ignored because they
contain private operational infrastructure details. The public OCR-008 summary
contains no host address, account path, credential or user-document data.

## Documentation delivered

- Russian README with capabilities, format support, architecture, local setup,
  Compose operations, environment setup, tests and known limitations.
- Current `ARCHITECTURE.md` describing the implemented pipeline and boundaries.
- `DEPLOYMENT.md` for safe Compose operation, updates and SQLite backup.
- `SECURITY.md` for credentials, document data, transport and publication
  practices.
- `ROADMAP.md` for observability, diagnostics, XLSX, Web UI, batch processing,
  structured extraction, API and monetization.

## Verification

- `uv sync --locked` — passed.
- `uv run pytest -q` — passed (94 tests).
- `git diff --check` — passed.
- `docker compose config --quiet` — passed.

## Publication plan

Commit the selected source, test and public documentation changes, then push
`feat/ocr-001` with a normal non-force push. Open a pull request to `main` and
do not merge it automatically. No GitHub Release or version tag is part of
this step.
