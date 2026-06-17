# Test credentials

## Django Admin (created automatically on first boot)
- URL: http://localhost/admin/
- Username: `admin`
- Password: `admin`
- Email: `admin@example.com`

> Override via env vars: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL` in `.env`.

## MinIO Console
- URL: http://localhost:9001/
- Access Key: `minioadmin`
- Secret Key: `minioadmin`

## Marquez UI
- URL: http://localhost:3000/  (no auth)

## Schema Registry (REST)
- URL: http://localhost:8081/  (no auth)

## Postgres (portal DB — inside Docker network only)
- Host: `postgres` (internal)
- DB: `metadata`
- User: `metadata`
- Password: `metadata`

## Marquez DB (inside Docker network only)
- Host: `marquez-db`
- DB / User / Pass: `marquez` / `marquez` / `marquez`

## Alation (user must supply)
- Set in `.env`: `ALATION_BASE_URL`, `ALATION_REFRESH_TOKEN`, `ALATION_USER_ID`, `ALATION_DATA_SOURCE_ID`, `ALATION_FOLDER_ID`.
- Default mode is `mock` — no creds required for demo.

## Emergent LLM
- `EMERGENT_LLM_KEY` baked into `.env.example` (universal key). Top-up at Profile → Universal Key.
