# Metadata Governance Platform

A fully containerized end-to-end metadata governance platform — **no host Python or virtualenv required**.

Generate domain-driven datasets (school, restaurant, hospital, bank, …) with three button-click sizes, automatically register schemas in Confluent Schema Registry, emit lineage to Marquez, generate an Excel Data Product Definition, then ingest that Excel back through Django Admin to auto-create the Data Product in Alation (real or mocked).

---

## Quick start

```bash
git clone https://github.com/ntawunhlanhla/metadata-governance-platform.git
cd metadata-governance-platform
cp .env.example .env          # edit credentials if needed
docker compose up -d
```

That's the entire installation. Wait 60–90 seconds, then open:

| URL | Service | Login |
|-----|---------|-------|
| http://localhost/admin/        | Django portal / admin | `admin / admin` |
| http://localhost:8585/         | **OpenMetadata** catalog | `admin@open-metadata.org / admin` |
| http://localhost:9001/         | MinIO console         | `minioadmin / minioadmin` |
| http://localhost:3000/         | Marquez UI (lineage)  | — |
| http://localhost:8081/         | Schema Registry REST  | — |
| http://localhost:5000/         | Marquez API           | — |

---

## End-to-end flow

```
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│ /admin/.../generator │───►│  data-generator      │───►│  MinIO (raw/*)       │
│  [Small] [Med] [Big] │    │  Celery worker       │    │  Schema Registry     │
│   + domain keyword   │    │  - LLM design        │    │  Marquez lineage     │
└──────────────────────┘    │  - Faker rows        │    │  Excel-uploads/auto/ │
                            └──────────────────────┘    └──────────────────────┘
                                                                 │
                                                                 ▼
                                                   ┌──────────────────────┐
                                                   │ User downloads xlsx, │
                                                   │ edits owner/domain   │
                                                   └──────────────────────┘
                                                                 │
                                                                 ▼
                                                   ┌──────────────────────┐
                                                   │ Django Admin upload  │
                                                   │ DataProductUpload    │
                                                   └──────────────────────┘
                                                                 │
                                                                 ▼
                                                   ┌──────────────────────┐
                                                   │ celery-worker (pipeline)
                                                   │  - parse xlsx         │
                                                   │  - build contract.yaml│
                                                   │  - publish to Alation │
                                                   └──────────────────────┘
```

---

## Services

| Service | Description |
|---------|-------------|
| `metadata-portal` | Django 5 portal + admin (gunicorn) |
| `postgres` | Portal database |
| `redis` | Celery broker |
| `celery-worker` | Pipeline queue (Excel ingestion, Alation sync) |
| `celery-beat` | Scheduled tasks |
| `data-generator` | Celery worker on `generator` queue (LLM + Faker + Parquet) |
| `minio` | S3-compatible object store (Parquet + contracts + Excel) |
| `kafka` + `zookeeper` | Kafka cluster (for Schema Registry) |
| `schema-registry` | Confluent Schema Registry |
| `marquez` + `marquez-db` | Lineage backend |
| `marquez-web` | Lineage UI |
| `init-job` | One-shot: creates MinIO buckets |
| `openmetadata-db` | OpenMetadata's Postgres |
| `openmetadata-opensearch` | OpenSearch (search backend for OpenMetadata) |
| `openmetadata-migrate` | One-shot: OpenMetadata schema migrations |
| `openmetadata-server` | **OpenMetadata data catalog** (UI on `:8585`) |
| `nginx` | Reverse proxy on port 80 |

---

## Step 1 — Generate data (button-driven)

1. Open **http://localhost/admin/** and log in (`admin / admin`).
2. Click **Generation Runs → 🪄 Data Generator** (top right).
3. Type a domain keyword: `school`, `restaurant`, `hospital`, `airline`, `bank`, anything.
4. Click **Small (10K)**, **Medium (1M)**, or **Large (100M)**.
   - The **Large** button shows a confirmation modal (≈ 8 GB, ≈ 10 minutes).
5. The Emergent LLM picks a realistic random instance (e.g. *Westridge Academy*) and designs 3–5 related datasets.
6. The `data-generator` container:
   - Generates Parquet → uploads to MinIO `raw/<product>/<dataset>/data.parquet`
   - Registers Avro schema in Schema Registry (`<product>.<dataset>-value`)
   - Emits OpenLineage events to Marquez (per-dataset + per-edge)
   - Builds the **Data Product Definition Excel** at `excel-uploads/auto/<product>_<run_id>_definition.xlsx`

You can monitor progress on the runs page (auto-refreshes status).

---

## Step 2 — Upload the Excel (creates the Data Product)

1. Open **MinIO console** at http://localhost:9001 → bucket `excel-uploads` → folder `auto/`.
2. Download the freshly-built `.xlsx`.
3. (Optional) Edit `owner_email`, `tags`, add quality rules, tweak descriptions.
4. In Django Admin, go to **Data Product Uploads → Add Data Product Upload**, attach the file, click **Save**.
5. The Excel is parsed → **DataProduct** + **Dataset** + **Column** + **LineageEdge** records are created → **contract.yaml** is written to MinIO `contracts/<product>/contract.yaml` → payload is **published to OpenMetadata** (or Alation, depending on `CATALOG_PROVIDER`).

---

## Step 3 — View results

- **OpenMetadata UI** at http://localhost:8585 — published Data Products + tables + lineage.
- **Django Admin → Data Products** — published products + external_id link.
- **Django Admin → Catalog Sync Logs** — every payload sent (success or fail).
- **Marquez UI** at http://localhost:3000 — see the lineage graph of jobs and datasets.
- **MinIO** at http://localhost:9001 — browse Parquet files and contracts.

---

## Catalog: OpenMetadata (default, runs in Docker)

OpenMetadata is the open-source data catalog included in this stack. UI at http://localhost:8585.

### First-time bot token setup (5 minutes)

1. Open http://localhost:8585.
2. Login: `admin@open-metadata.org` / `admin`.
3. Top-right gear → **Bots** → click **ingestion-bot**.
4. Click **Copy Token** next to the JWT field.
5. Paste into `.env`:
   ```
   OPENMETADATA_JWT_TOKEN=<paste>
   ```
6. Restart the portal:
   ```
   make restart-portal
   ```

That's it. Every subsequent Excel upload publishes a real Data Product into OpenMetadata's UI under **Domains → \<your domain\>** and **Explore → Data Products**.

> Until you paste the JWT token, the portal falls back to **mock mode** (writes JSON to `./alation_sync/*.json`). The pipeline still completes end-to-end so you can validate the rest.

---

## Alation: real tenant (optional, no Docker image exists)

> Use Alation only if you have a paid Alation tenant. There is no Alation Docker image.

Set in `.env`:

```
CATALOG_PROVIDER=alation
ALATION_MODE=real
ALATION_BASE_URL=https://yourtenant.alationcatalog.com
ALATION_REFRESH_TOKEN=<refresh token from Alation Account Settings>
ALATION_USER_ID=<your user id>
ALATION_DATA_SOURCE_ID=<source id where DPs live>
ALATION_FOLDER_ID=<optional folder id>
```

Then `make restart-portal`. The app auto-exchanges the Refresh Token for an API Access Token and refreshes it before expiry.

---

## Pluggable source connectors

Already wired into Django settings (`settings.CONNECTORS`):

- `minio` — full impl (lists Parquet, reads schema + samples)
- `s3` — boto3 (set `AWS_*` in `.env`)
- `athena` — Glue Catalog + Athena query
- `glue` — Glue Catalog only
- `marquez` — read datasets already in Marquez

Add your own connector by:
1. Subclassing `governance.connectors.base.BaseConnector`.
2. Implementing `discover_datasets`, `read_schema`, `read_sample`.
3. Registering it in `portal/settings.py → CONNECTORS`.

The `SourceConnection` model in Django Admin lets you create instances at runtime (`name`, `kind`, `config` JSON).

---

## Makefile shortcuts

```
make up                # build + start everything
make down              # stop
make restart-portal    # restart Django + celery
make logs              # tail all logs
make ps                # show service status
make migrate           # run Django migrations
make portal-shell      # open Django shell
make generate-small    # CLI: small dataset (DOMAIN=school by default)
make generate-medium   # CLI: 1M rows
make generate-large    # CLI: 100M rows  (also via UI button)
make alation-sync      # Re-publish failed Alation pushes
make nuke              # ⚠ remove all volumes (destroys MinIO + Postgres data)
```

Example: `DOMAIN=restaurant make generate-medium`

---

## Resource notes

- **Small (10K rows)**: ~5 sec, < 50 MB RAM.
- **Medium (1M rows)**: ~30 sec, ~500 MB RAM.
- **Large (100M rows)**: ~10 min, peak ~3 GB RAM, ~8 GB MinIO disk.
- **OpenMetadata stack** adds ~3 GB RAM (server 1 GB + opensearch 1 GB + postgres 200 MB).

**Total recommended**: Docker Desktop with **≥ 8 GB memory** allocated. Bump to ≥ 12 GB if you'll run Large generation.

---

## Troubleshooting

```bash
# Check what's running
docker compose ps

# Tail a specific service
docker compose logs -f metadata-portal
docker compose logs -f data-generator

# Reset everything
docker compose down -v
docker compose up -d --build
```

If Marquez UI shows nothing: confirm `marquez` is healthy (`docker compose ps`) and that the generator finished (`Generation Runs` should show `completed`).

If Alation publish fails: check **Alation Sync Logs** in Django admin — the request and error are recorded.

---

## License

MIT.
