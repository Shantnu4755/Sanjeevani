# CLAUDE.md: Sanjeevani

Self-healing monitor and status page: detects failures, restarts containers safely, escalates crash loops to a human. Part of a six-project portfolio platform that runs on one free Oracle ARM VM.

- **Source of truth:** the PDF `~/Downloads/Portfolio Projects Complete Build & Free Deployment Plan.pdf`.
- **Progress and deviations:** `../PROGRESS.md`. Update it after every step. Any change to the PDF's design goes under "Deviations from the plan" with the reason; never change the design silently.

## Rules (PDF "Coding rules")
1. Class-based views only (`BaseView`, a Flask `MethodView`) with **only `get()` and `post()`**. Updates and deletes are a POST to an action endpoint (for example `POST /claims/<id>/approve`). `tests/test_view_rules.py` enforces it.
2. Layers: **View** (HTTP only) → **Service** (business logic) → **Repository** (DB access) → **Model**. A view never writes SQL or opens sessions; a repository never imports Flask.
3. Errors: raise `AppError` subclasses from `app/exceptions.py`. One global handler returns `{"error": {"code", "message", "details", "request_id"}}`. No bare `except:`, no `print`, no swallowed errors (log with `logger.exception` when a loop must continue).
4. Every request is validated with Pydantic (`BaseView.parse_body` / `parse_query`) before it reaches a service.
5. Config from environment variables only (`app/config.py`, fails fast at boot). `.env.example` is committed, `.env` never is.
6. Structured JSON logs with `request_id` on every line. Allowed extra fields: `code`, `error_message`, `job_id`, `service`.
7. pytest for every service class, against real PostgreSQL (never SQLite). External calls (LLM, Telegram, Docker, HTTP) are mocked. CI fails under 80% coverage.

Also: Python 3.12, type hints everywhere, `ruff check .` clean, small commits prefixed `feat:` `fix:` `test:` `docs:` `chore:`. Push after every verified change (the local folder was once deleted by an outside process; GitHub is the backup).

## Layout (PDF 2.1)
`app/{__init__,config,extensions,exceptions,error_handlers,logging_setup}.py`, `app/models`, `app/schemas`, `app/repositories`, `app/services`, `app/views` (`base.py`, `health.py`, `__init__.py` with `register_routes`), `migrations/` (Alembic), `tests/`, `wsgi.py`, `gunicorn.conf.py`, `Dockerfile`, `ui/` (React UI, PDF 3A).

## Commands
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.txt
# local test databases: docker container "portfolio-test-pg" on port 55432 (password "test")
export TEST_DATABASE_URL=postgresql+psycopg://postgres:test@localhost:55432/sanjeevani_test
ruff check . && pytest --cov=app --cov-report=term-missing
DATABASE_URL=... alembic revision --autogenerate -m "describe change" && alembic upgrade head
docker build -t sanjeevani .
```
Dependencies: runtime packages go in `requirements.txt`, test tools in `requirements-dev.txt`. `requirements.lock` is the frozen runtime set (`pip freeze` of a runtime-only install, or of the built image), so pytest never ships in the image.

## Sanjeevani specifics (PDF 3.6)
- **Security:** never the raw Docker socket. `docker-proxy` (`wollomatic/socket-proxy`, `DOCKER_URL=tcp://docker-proxy:2375`) allows only container list/inspect and restart.
- **Tables:** `monitored_services`, `health_checks`, `incidents`, `restart_events` (auto/manual/failed).
- **Endpoints:** `GET /summary` (status page JSON), `GET /services`, `GET /services/<name>/checks`, `GET /incidents?open=`, `POST /services/<name>/restart` (`X-Admin-Token` = `ADMIN_TOKEN`).
- **Monitor:** `python -m app.monitor`, every `CHECK_INTERVAL` (30 s). 3 failed checks → restart. Restart budget `max_restarts_per_hour` (auto + failed attempts), then "NEEDS HUMAN". Recovery resolves the open incident on any healthy check. Alerts via Telegram (logged when not configured). Daily housekeeping of checks older than 7 days.
- **CLI:** `python -m app.cli add-service --name kavach --container kavach --url http://kavach:8000/health` (upsert), `list-services`, `disable-service`, `enable-service`.
- **Tests to write:** three failures trigger one restart; a fourth restart within an hour escalates instead; recovery resolves the incident; Telegram being down does not stop the loop; Docker errors are logged and alerted.
- **UI accent:** teal (hue 185), green and red for health states.
