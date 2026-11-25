SHELL := /bin/bash

# Портабельные входы. PROFILE — имя файла в profiles/ либо путь к профилю.
PYTHON      ?= python3
PROFILE     ?= live
RUN         ?= $(shell date -u +%Y%m%dT%H%M%SZ)-local
SCENARIO    ?= read-smoke
ARTIFACTS   ?= artifacts/$(RUN)

PROFILE_PATH := $(if $(wildcard $(PROFILE)),$(PROFILE),profiles/$(PROFILE).json)

FILEQA_PROFILE   ?= $(PROFILE_PATH)
FILEQA_ORIGIN    ?=
FILEQA_RUN_ID    ?= $(RUN)
FILEQA_ARTIFACTS ?= $(ARTIFACTS)
PYTHONPATH       := src:$(PYTHONPATH)

export FILEQA_PROFILE FILEQA_ORIGIN FILEQA_RUN_ID FILEQA_ARTIFACTS PYTHONPATH

.PHONY: install selftest e2e capacity security load report all

install:
	$(PYTHON) -m pip install -e ".[dev]"

# Автономная самопроверка инструментов на синтетических данных (без сети).
selftest:
	$(PYTHON) -m pytest tests/harness tests/capacity/test_selftest.py --junitxml=$(ARTIFACTS)/selftest/junit.xml -q

e2e:
	$(PYTHON) -m pytest tests/e2e -m e2e --junitxml=$(ARTIFACTS)/e2e/junit.xml -q

capacity:
	$(PYTHON) -m pytest tests/capacity -m capacity --junitxml=$(ARTIFACTS)/capacity/junit.xml -q

security:
	$(PYTHON) -m pytest tests/security -m security --junitxml=$(ARTIFACTS)/security/junit.xml -q

# k6 выполняется на машине с k6 (например, сервер-генератор). Здесь — команда.
# MANIFEST передаётся АБСОЛЮТНЫМ путём: k6 open() с относительным путём считает
# его от каталога сценария, а не от рабочего каталога.
load:
	@echo "Подготовь фикстуру и манифест:"
	@echo "  $(PYTHON) -m fileqa.prepare --profile $(PROFILE_PATH) --run $(RUN) --out $(abspath $(ARTIFACTS))/manifest.json"
	@echo "Затем на машине с k6:"
	@echo "  k6 run -e MANIFEST=$(abspath $(ARTIFACTS))/manifest.json load/k6/scenarios/$(SCENARIO).js"
	@echo "или совместимо с историей (read-smoke):"
	@echo "  k6 run -e FILE_URL=... -e FILE_SHA256=... -e VUS=1 load/k6/scenarios/read-smoke.js"

report:
	$(PYTHON) tools/collect.py $(ARTIFACTS) --profile $(PROFILE_PATH)
	$(PYTHON) tools/report.py $(ARTIFACTS)

all: install selftest
