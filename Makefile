.PHONY: install demo test lint serve docker-build docker-run

install:
	pip install -e ".[dev]"

demo:
	python scripts/demo.py

test:
	pytest -v --cov=txnagent --cov-report=term-missing

lint:
	ruff check src tests

serve:
	uvicorn txnagent.api.main:app --reload --port 8000

docker-build:
	docker build -t txnagent:local .

docker-run:
	docker compose up --build
