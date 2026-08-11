.PHONY: dev dev-web dev-api dev-worker test lint build docker-up docker-down

dev:
	@echo "Run make dev-web, make dev-api, and make dev-worker in separate terminals."

dev-web:
	npm run dev

dev-api:
	SOURCEDGRID_DATA_DIR=./data .venv/bin/uvicorn --app-dir backend app.main:app --reload --port 8000

dev-worker:
	cd backend && SOURCEDGRID_DATA_DIR=../data ../.venv/bin/python -m app.worker

test:
	.venv/bin/pytest backend/tests
	npm run build

lint:
	.venv/bin/ruff check backend
	npm run lint

build:
	npm run build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
