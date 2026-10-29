.PHONY: install lint format test eval eval-stage run audit up down k8s-render

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests evals
	ruff format --check src tests evals

format:
	ruff format src tests evals
	ruff check --fix src tests evals

test:
	pytest -q

eval:
	python -m evals.offline.run_eval

run:
	uvicorn pia.api.main:create_app --factory --reload --port 8000

audit:
	pip-audit

up:
	docker compose up -d --build

down:
	docker compose down

eval-stage:
	python -m evals.offline.run_eval --llm anthropic

k8s-render:
	kubectl kustomize deploy/k8s/overlays/$(ENV)
