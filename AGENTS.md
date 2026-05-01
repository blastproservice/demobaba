# AGENTS.md

## Purpose
This file helps AI coding agents understand the BABA Parfume backend architecture, coding conventions, and where to make safe changes.

## Project summary
- Backend: FastAPI app in `main.py`
- Templates: Jinja2 HTML templates under `templates/`
- Static assets: `static/`
- Data layer: Supabase client in `database.py` with env vars `SUPABASE_URL` and `SUPABASE_KEY`
- Routers: modular FastAPI routers under `routers/`
  - `routers/customer/store.py` for customer-facing pages and API endpoints
  - `routers/admin/*.py` for admin pages and admin-related operations
- Shared helpers and common conventions in `routers/common.py`
- Optional Telegram bot integration in `bot.py` loaded during FastAPI lifespan

## Key conventions
- Keep the app modular. Add new features by creating or extending routers under `routers/` instead of changing `main.py`.
- Use `APIRouter` and include routers in `main.py`; customer routes are unprefixed and admin routes usually use `/admin`.
- Use `response_class=HTMLResponse` for server-rendered pages, `JSONResponse` for API responses.
- Render templates with a `request` context object and use `render_admin_template()` for admin pages when possible.
- Centralize repeated data transformation logic in helper functions, not directly inside route handlers.
- Use `try/except Exception as e` and log errors with `logger` instead of bare excepts.
- Avoid duplicate Supabase query patterns; prefer reusable helpers and normalized response shaping.

## Supabase and environment
- `database.py` creates a Supabase client from `.env`
- If Supabase is unavailable, many routes gracefully fall back or return a 503/JSON error
- Do not hardcode credentials or production URLs in source files

## What to expect in this repo
- A server-rendered architecture, not a React/Next.js frontend
- Route logic mixed with lightweight data shaping and template context assembly
- A small admin dashboard using Jinja2 templates and Supabase queries
- Customer-facing endpoints that expose both page views and REST-style `/api/v1/*` routes

## Best practices for AI agents
- Preserve existing business routes and Jinja2 structure when changing views
- Keep page rendering separate from API logic; use dedicated endpoints for data fetching
- When adding new admin features, update shared helpers in `routers/common.py` first if behavior is reused
- Prefer smaller, composable helper functions for query building and template context
- Use environment-driven configuration and avoid adding new hardcoded settings directly into route files

## References
- No README or architecture docs exist. Use `main.py`, `routers/common.py`, and router files under `routers/` as the source of truth.
