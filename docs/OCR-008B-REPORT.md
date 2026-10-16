# OCR-008B/1 — Docker Smoke Test on Beget VPS

## Scope and isolation

The smoke test was performed through SSH alias `miniapps-vps` in an isolated, randomly named `/tmp/ocr-008b-smoke.*` directory. The build context consisted only of `Dockerfile`, `compose.yaml`, `.dockerignore`, `pyproject.toml`, `uv.lock`, `README.md`, and `src/`; it did not contain `.env`, SQLite, fixtures, diagnostics, user documents, or OCR responses.

No Telegram or Email adapter command was run. All runtime test containers used `--network none`, did not publish ports, and executed only Python/import, filesystem, SQLite, or `sleep` probes. Existing Docker projects, networks, images, containers, and host configuration were not changed. `docker system prune` was not used.

## VPS readiness

- Docker Engine: `29.7.2`.
- Docker Compose: `v5.5.0`.
- Root filesystem: 77 GB total, 52 GB free at the time of testing.
- Memory: 5.8 GiB total; approximately 2.4 GiB available at the time of testing; no swap.
- Existing running containers were listed read-only before work and were not stopped, restarted, or reconfigured.

## Results

| Check | Result |
| --- | --- |
| `docker compose config --quiet` with a temporary non-secret `.env` | Passed |
| Production image build | Passed; `ocr-document-bot:smoke-008b`, 177,987,529 bytes |
| Locked production dependencies | Passed during build with `uv sync --locked --no-dev` |
| Python and imports | Passed: Python 3.12; Telegram adapter, Email adapter, `DocumentOCRService`, and DOCX renderer imported |
| Runtime identity | Passed: UID/GID `10001` / `10001` |
| Read-only filesystem and `/tmp` | Passed: `/app` rejected writes; noexec temporary `/tmp` accepted a controlled write |
| SQLite named volume | Passed: UID 10001 created SQLite DB and row; a recreated container read the same row |
| SIGTERM / restart | Passed with Compose-equivalent `--init`: SIGTERM exit code `143`, restart policy `no` |
| Secret/state image check | Passed: no `/app/.env` or `/data/email-adapter.sqlite3` in final image; image history had no explicit Yandex, Telegram, or email-password assignment |

## SIGTERM note

An initial raw `docker run` probe without `--init` required SIGKILL after the grace period because Python was PID 1. This does not represent the Compose deployment: `compose.yaml` sets `init: true`. Repeating the probe with `--init` produced expected graceful SIGTERM termination (exit 143). The existing Compose setting is therefore required and must be retained.

## Cleanup

After validation, the dedicated smoke image tag, test named volume, temporary dummy `.env`, temporary `/tmp` build context, and all test containers were removed. No working adapter or real credential was used.

## Limitations

This validates Docker packaging and local process properties only. It does not validate production external connectivity, polling, OCR billing behavior, or Beget deployment configuration. Those remain outside OCR-008B/1.
