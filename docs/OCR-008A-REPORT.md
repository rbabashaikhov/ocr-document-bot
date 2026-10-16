# OCR-008A — Docker Packaging

## Changes

- Added a single multi-stage `Dockerfile` for Python 3.12. Dependencies are resolved by `uv sync --locked --no-dev`; the final image contains only the virtual environment and application source.
- Added `compose.yaml` with independent `ocr-telegram` and `ocr-email` processes from that image. Neither publishes a port.
- Email state is stored at `/data/email-adapter.sqlite3` in the named volume `ocr-document-bot-email-state`; the rest of each container filesystem is read-only. A non-empty image-owned `/data` directory initializes a new named volume with UID/GID `10001`, allowing SQLite and journal files to be written by the non-root process.
- Containers run as the unprivileged `ocrbot` UID/GID `10001`, drop Linux capabilities, prohibit privilege escalation, use a noexec `/tmp` tmpfs, limit PIDs/CPU/RAM, and rotate local Docker logs.
- Added `.dockerignore` to exclude `.env`, virtual environments, Git metadata, fixtures, diagnostics, local SQLite state, tests, artifacts, and user documents from the build context.
- Updated README with build, selective service lifecycle, logs, SQLite backup/restore, and safe update instructions.

## Lifecycle and state

Compose does not start services merely by reading the file. The initial VPS start requires an operator command (`docker compose up -d …`). `restart: unless-stopped` then provides host-restart recovery. The two pollers must not be scaled or started twice with the same Telegram token or IMAP mailbox/SQLite volume.

`STOPSIGNAL SIGTERM`, Docker `init: true`, exec-form commands, and a 30-second grace period provide normal process termination. The Email adapter has durable delivery state, so container recreation retains deduplication and `uncertain` SMTP records through the named volume.

## Healthcheck limitation

The Compose healthcheck verifies that PID 1 is alive. It detects a stopped adapter but cannot establish that a polling event loop is making progress or that external Telegram/IMAP/SMTP/Vision services are reachable: these adapters have no local health endpoint. The operational alternative is container status/log monitoring plus an explicitly authorized external canary; no external requests are sent by the healthcheck.

## Verification

- `docker compose config --quiet` — passed. It validated the resolved Compose model without printing `.env` values.
- Docker CLI is installed, but the local Docker daemon is unavailable (`Cannot connect to the Docker daemon`). Therefore image build, non-root runtime, startup/shutdown without external calls, SQLite write permissions, and persistence across actual container recreation remain unverified. These checks must be run when the daemon is accessible and must use a safe test `.env` that cannot contact production polling accounts.

The repository test suite and `git diff --check` are run separately for this stage. No deployment, merge, or real OCR/mail operation is part of OCR-008A.
