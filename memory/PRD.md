# Metadata Governance Platform — PRD

## Original problem statement
Build a fully containerized metadata governance platform. No host Python / venvs / pip — everything via Docker Compose. Services:
metadata-portal (Django), postgres, redis, celery-worker, celery-beat, minio, kafka, zookeeper, schema-registry, marquez, marquez-db, nginx, data-generator.

User uploads Excel Data Product Definitions → Data Products published to Alation. Auto-discover datasets, generate contracts, register schemas, create lineage in Marquez, sync lineage to Alation.

Demo dataset sizes: Small=10K, Medium=1M, Large=100M.

Docker startup must: build images, run migrations, init MinIO buckets, generate sample datasets, create admin user, start all services. Must run with `docker compose up -d` and zero host Python.

## User clarifications
- **UI**: Django Admin with three buttons (Small, Medium, Large) on a dedicated Data Generator page. Large button has confirmation modal.
- **Excel generator is separate from data generator**. Generator creates data + writes definition Excel; uploading the Excel triggers the pipeline that publishes to Alation.
- **Domain-driven generation**: Emergent LLM (Claude Sonnet 4.6 via emergentintegrations) designs realistic datasets from any domain keyword (school, restaurant, hospital, …). LLM picks a random realistic instance name.
- **Connectors**: pluggable architecture for MinIO, AWS S3, AWS Athena, AWS Glue, Marquez — extensible.
- **Alation**: dual-mode client. `ALATION_MODE=mock` writes payloads to ./alation_sync/. `ALATION_MODE=real` exchanges Refresh Token → Access Token automatically.
- **Delivery**: code in /app, user pushes via Emergent's Save-to-GitHub to `ntawunhlanhla` namespace.

## Architecture summary
13 docker-compose services with healthchecks + dependency ordering. `init-job` runs once to create buckets. `metadata-portal` runs migrations + collectstatic + superuser bootstrap on first start. Three Celery workers: default queue, pipeline queue (ingestion), generator queue (data-generator).

## Implementation status (this session)
- [x] docker-compose.yml (19 services: portal stack + OpenMetadata stack, healthchecks, depends_on conditions)
- [x] Makefile (up/down/logs/migrate/generate-*/nuke/...)
- [x] .env.example, .gitignore
- [x] portal/Dockerfile + entrypoint.sh + requirements.txt
- [x] Django project (settings, urls, wsgi, asgi, celery)
- [x] governance app: models (10), admin, urls, views, signals, apps, tasks
- [x] Services: minio_client, schema_registry, marquez_client, llm_designer (Emergent LLM), data_generator (Faker → Parquet streaming), excel_service (build + parse), contract_generator (YAML)
- [x] **catalog/ adapter package**: base + mock + openmetadata (default) + alation, plus `get_catalog_client()` factory
- [x] Connectors: base + minio (full) + s3 + athena + glue + marquez
- [x] **OpenMetadata services**: openmetadata-db, openmetadata-opensearch, openmetadata-migrate, openmetadata-server (image `docker.getcollate.io/openmetadata/server:1.5.13`)
- [x] Templates: admin generator page (with Large confirm modal), home page with OpenMetadata link, change_list extension
- [x] Management commands: generate_dataset, sync_alation
- [x] init-job (Dockerfile + init.py, creates 4 MinIO buckets)
- [x] nginx (Dockerfile + config, port 80 → portal, static/media served from volumes)
- [x] README with end-to-end walkthrough + OpenMetadata bot token setup

## What's NOT done (deferred)
- Periodic celery-beat schedule for `sync_alation` (Beat is running but no schedule rows seeded — admin can add via django_celery_beat).
- True streaming write of 100M-row Parquet (current implementation buffers chunks then yields once). For 100M+ on low-RAM hosts, switch to direct multipart upload to MinIO.
- Real Alation v2 custom object schema may differ per tenant — payload builder is generic and easy to override.
- UI tests / integration tests — none added (test_reports/ kept but empty).

## Bug fixes applied during deployment
- **`docker compose up -d` now creates DB tables**: `entrypoint.sh` runs `makemigrations governance --noinput` before `migrate --noinput`.
- **Celery workers can read uploaded Excel files**: `portal-media` volume mounted in `celery-worker`, `celery-beat`, `data-generator` (was only in `metadata-portal`).
- **OpenMetadata JWT auto-bootstrap**: `OpenMetadataClient` now auto-fetches the ingestion-bot JWT by logging in as admin (defaults `admin@open-metadata.org` / `admin` — overridable via `OPENMETADATA_ADMIN_EMAIL`/`OPENMETADATA_ADMIN_PASSWORD`). Handles 3 different OM API response shapes for cross-version compatibility. Cached for 50 minutes.

## Next action items (after first boot)
1. Run `docker compose up -d`. Wait ~90s for healthchecks.
2. Visit `http://localhost/admin/` (admin/admin) → Data Generator → type "school" → click Small.
3. Watch run progress; once `completed`, download generated Excel from MinIO `excel-uploads/auto/`.
4. Upload Excel via Data Product Uploads → product published (to mock or real Alation).
5. View lineage at `http://localhost:3000`.

## Future / backlog
- P1: Real-time progress over SSE / websockets (currently polling).
- P1: Bulk Excel upload (zip of definitions).
- P2: Data Contract validation against actual Parquet (great_expectations integration).
- P2: Slack/Email notifications on publish success/failure.
- P3: Multi-tenant support (per-org Postgres schemas).
