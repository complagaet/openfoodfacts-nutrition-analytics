PROFILE ?= demo
PYTHON ?= .venv/bin/python
RUN = $(PYTHON) -I -m offna
BATCH_ROWS_demo = 2500
BATCH_ROWS_full = 250000
SUBSET_ROWS_demo = 10000
SUBSET_ROWS_full = 1000000

.PHONY: setup acquire acquire-csv fixture etl audit csv-audit aggregates benchmark sql model eda pipeline app menu test lint

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PYTHON) -r requirements.txt
	uv pip install --python $(PYTHON) --no-deps -e .

acquire:
	$(RUN) acquire --source parquet

acquire-csv:
	$(RUN) acquire --source csv-head --bytes 20000000

fixture:
	$(RUN) acquire --source fixture --rows 10000

etl:
	$(RUN) etl --profile $(PROFILE) --batch-rows $(BATCH_ROWS_$(PROFILE))

audit:
	$(RUN) audit --profile $(PROFILE)

csv-audit:
	$(RUN) csv-audit --profile $(PROFILE) --input data/raw/csv_head.tsv

aggregates:
	$(RUN) aggregates --profile $(PROFILE)

benchmark:
	$(RUN) benchmark --profile $(PROFILE) --subset-rows $(SUBSET_ROWS_$(PROFILE)) --repeats 3 $(if $(filter full,$(PROFILE)),--full,)

sql:
	$(RUN) sql --profile $(PROFILE)

model:
	$(RUN) model --profile $(PROFILE)

eda:
	$(RUN) eda --profile $(PROFILE)

pipeline: etl audit aggregates benchmark sql model eda

app:
	$(PYTHON) -m streamlit run app.py

menu:
	$(RUN) menu --profile $(PROFILE)

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
