# Metadata Governance Platform — Makefile
# All targets run inside Docker. No host Python required.

COMPOSE ?= docker compose

.PHONY: help up down restart logs ps build pull \
        portal-shell portal-bash migrate makemigrations createsuperuser \
        generate-small generate-medium generate-large \
        alation-sync clean nuke restart-portal test

help:
	@echo "Metadata Governance Platform"
	@echo ""
	@echo "make up                - Build & start all services"
	@echo "make down              - Stop all services"
	@echo "make restart           - Restart all services"
	@echo "make restart-portal    - Restart Django portal + celery"
	@echo "make logs              - Tail all logs"
	@echo "make ps                - List running containers"
	@echo "make build             - Rebuild images"
	@echo ""
	@echo "make migrate           - Run Django migrations"
	@echo "make createsuperuser   - Create Django admin user"
	@echo "make portal-shell      - Open Django shell"
	@echo "make portal-bash       - Open bash in portal container"
	@echo ""
	@echo "make generate-small    - Trigger Small dataset (10K rows)"
	@echo "make generate-medium   - Trigger Medium dataset (1M rows)"
	@echo "make generate-large    - Trigger Large dataset (100M rows, slow)"
	@echo ""
	@echo "make clean             - Stop + remove containers, keep volumes"
	@echo "make nuke              - Stop + remove containers AND volumes (DESTROYS DATA)"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

restart-portal:
	$(COMPOSE) restart metadata-portal celery-worker celery-beat data-generator

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

pull:
	$(COMPOSE) pull

portal-shell:
	$(COMPOSE) exec metadata-portal python manage.py shell

portal-bash:
	$(COMPOSE) exec metadata-portal bash

migrate:
	$(COMPOSE) exec metadata-portal python manage.py migrate

makemigrations:
	$(COMPOSE) exec metadata-portal python manage.py makemigrations

createsuperuser:
	$(COMPOSE) exec metadata-portal python manage.py createsuperuser

generate-small:
	$(COMPOSE) exec metadata-portal python manage.py generate_dataset --size small --domain "$${DOMAIN:-school}"

generate-medium:
	$(COMPOSE) exec metadata-portal python manage.py generate_dataset --size medium --domain "$${DOMAIN:-school}"

generate-large:
	$(COMPOSE) exec metadata-portal python manage.py generate_dataset --size large --domain "$${DOMAIN:-school}"

alation-sync:
	$(COMPOSE) exec metadata-portal python manage.py sync_alation

clean:
	$(COMPOSE) down

nuke:
	$(COMPOSE) down -v
