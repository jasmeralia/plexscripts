SHELL := /bin/bash

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest
INSTALL_BIN := /usr/local/bin
INSTALL_LIB := /usr/local/lib/plexadm
INSTALL_SHARE := /usr/local/share/plexadm

.PHONY: help install install-system lintfix lint test clean

help:
	@printf '%s\n' \
		'Targets:' \
		'  install         Create .venv and install development requirements' \
		'  install-system  Install plexadm and shell helpers into /usr/local/bin' \
		'  lintfix         Auto-format and auto-fix lint issues' \
		'  lint            Run ruff and mypy checks' \
		'  test            Run pytest with coverage XML for Codecov' \
		'  clean           Remove local test/lint caches'

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

install-system: install
	install -d $(INSTALL_LIB)
	cp -R plexadm $(INSTALL_LIB)/
	install -m 0755 bin/plexadm $(INSTALL_BIN)/plexadm
	install -d $(INSTALL_BIN)/plexadm-scripts
	find scripts -maxdepth 1 -type f -name '*.sh' -exec install -m 0755 {} $(INSTALL_BIN)/plexadm-scripts/ \;
	install -d $(INSTALL_SHARE)/reference
	find reference -maxdepth 1 -type f \( -name '*.txt' -o -name '*.json' \) -exec install -m 0644 {} $(INSTALL_SHARE)/reference/ \;

lintfix: install
	$(RUFF) format .
	$(RUFF) check --fix .

lint: install
	$(RUFF) format --check .
	$(RUFF) check .
	$(MYPY) plexadm tests
	bash -n scripts/*.sh
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; else echo 'shellcheck not installed; skipped'; fi
	@if command -v hadolint >/dev/null 2>&1; then \
		hadolint Dockerfile; \
	else \
		docker run --rm -i hadolint/hadolint < Dockerfile; \
	fi

test: install
	$(PYTEST)

clean:
	rm -rf .coverage coverage.xml htmlcov .mypy_cache .pytest_cache .ruff_cache
