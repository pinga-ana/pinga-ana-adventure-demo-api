# Desenvolvimento local: carrega variáveis de `.env` via python-dotenv no `app.main`.
PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: venv install dev

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev:
	@test -f $(UVICORN) || { echo "Execute: make install"; exit 1; }
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000
