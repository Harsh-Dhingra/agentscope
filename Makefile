.PHONY: setup run test build evaluate
setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.lock
	.venv/bin/python -m pip install -e . --no-deps
	npm --prefix web ci
	npm --prefix web run build
run:
	.venv/bin/python -m uvicorn agentscope.api:app --host 127.0.0.1 --port 8765
test:
	.venv/bin/python -m pytest -q
build:
	npm --prefix web run build
evaluate:
	.venv/bin/python examples/evaluate.py
