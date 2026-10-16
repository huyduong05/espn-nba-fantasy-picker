.PHONY: install check check-python check-extension test test-python test-extension

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e '.[dev]'
	npm --prefix extension install

check: check-python check-extension

check-python:
	.venv/bin/ruff format --check src tests
	.venv/bin/ruff check src tests
	.venv/bin/mypy src
	.venv/bin/pytest

check-extension:
	.venv/bin/fantasy-picker extension build-player-index
	npm --prefix extension run check

test: test-python test-extension

test-python:
	.venv/bin/pytest

test-extension:
	npm --prefix extension test

