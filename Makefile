.PHONY: up down logs status test backup restore

up:
	docker compose up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f

status:
	docker compose ps

test:
	cd api && python3 -m pytest

backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh
