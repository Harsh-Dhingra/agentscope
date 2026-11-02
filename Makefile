.PHONY: setup init-access run test build evaluate check
setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.lock
	.venv/bin/python -m pip install -e . --no-deps
	npm --prefix web ci
	npm --prefix web run build
init-access:
	.venv/bin/python -m agentscope.identity init
run:
	.venv/bin/python -m uvicorn agentscope.api:app --host 127.0.0.1 --port 8765
test:
	.venv/bin/python -m pytest -q
build:
	npm --prefix web run build
evaluate:
	.venv/bin/python examples/evaluate.py

check:
	.venv/bin/python -m agentscope.cli check --variant guarded --output data/ci-regression.json
