# Карта критериев: требование → код → подтверждение

Дополняет [ASSESSMENT.md](ASSESSMENT.md). Числа — полный прогон, см. [REPORT.md](REPORT.md).

## Общие требования 1–11

| № | Требование | Где выполнено | Чем подтвердить |
| --- | --- | --- | --- |
| 1 | ≥ 5 функций помимо `main` | ≈200 функций и методов в 22 модулях `src/offna/*` (например `flatten_nutriments`, `quality_rules`, `score_2023`, `group_split`, `run_queries`) | `rg "^def " src/offna` |
| 2 | `list` / `dict` | `config.py` (`RAW_COLUMNS`, `NUTRIENTS`, `PROFILES`), `nutriscore.py` (`THRESHOLDS_2023`), `cli.py` (`STAGES`) | код |
| 3 | `if` / `elif` / `else` | `menu.py::handle`, `cli.py::stage_acquire`, `csv_reader.py::iter_validated_records` | код, демо меню |
| 4 | `for` / `while` | цикл по пачкам в `etl.py::run_etl`, `while` в `menu.py::run_menu` и `ask_number` | код |
| 5 | Чтение и запись постоянных файлов | Parquet (`etl.py`, `aggregates.py`), SQLite (`database.py`), JSON-отчёты (`measure.py::write_json`), CSV-таблицы | `data/`, `outputs/`, `docs/results/` |
| 6 | `try…except` | `etl.py::iter_raw_batches` (нет снимка), `dashboard.py::load_aggregates` (нет агрегатов), `menu.py::ask_number` (`ValueError`), `cli.py::main` | `tests/test_menu.py`, `tests/test_pipeline.py::test_missing_aggregates_raise_friendly_error` |
| 7 | Меню или дашборд с фильтрами | `app.py` (Streamlit: страна, пищевая группа), `menu.py` | `make app`, `make menu`, `tests/test_app.py` |
| 8 | Несколько модулей, стандартная библиотека | пакет `offna`: `pathlib`, `json`, `datetime`, `sqlite3`, `argparse`, `subprocess`, `resource`, `hashlib` | структура в README |
| 9 | ≥ 2 подхода и baseline | движки: pandas default (baseline) vs pandas chunked vs Polars lazy; модели: Dummy (baseline) + правило + LR + HGB | REPORT §4, §7 |
| 10 | SQLite, ER, ≥ 8 SQL, результаты в pandas | `sql/schema.sql`, 10 запросов `sql/q*.sql`, `database.py::run_queries` (`pd.read_sql_query`) | [DATABASE.md](DATABASE.md), REPORT §5 |
| 11 | ≥ 500 тыс. строк или 200 МБ | 4 906 869 строк, 7,49 ГиБ | `docs/results/full_snapshot.json` |

## Обязательные задачи Cluster 8

| Задача | Где выполнено | Подтверждение |
| --- | --- | --- |
| Загрузка с ограниченной памятью, партиционированный Parquet, `category`/downcast, память до/после | `etl.py` (пачки по 250 000, партиции `food_group`), `measure_dtype_savings`, `csv_audit.py::wide_memory` | 257,6 → 121,3 МиБ; CSV 201 столбец: 20,99 → 8,81 МиБ; пик RSS ETL 3 582 МиБ (3,5 ГиБ) |
| ≥ 2 инструмента на одной задаче: время, пик памяти, совпадение | `engines.py`, `benchmark.py`, `bench_worker.py` (отдельные процессы) | REPORT §4, `docs/results/benchmark.json`, `tests/test_pipeline.py::test_all_engines_produce_equal_aggregates` |
| Ленивые вычисления / инкрементальные агрегаты | `engines.py::polars_lazy` (`collect_all`, streaming), `engines.py::pandas_chunked`, счётчики нарушений в `etl.py::run_etl` | код |
| Аудит пропусков, дубликатов, некорректных значений и дат, выбросов; правила очистки | `audit.py`, `etl.py::quality_rules`, `apply_cleaning` | REPORT §3 |
| EDA, 4–5 графиков, ≥ 1 Plotly, 2 гипотезы | `eda.py`, `hypotheses.py` | `docs/figures/fig1…fig5`, REPORT §6 |
| Дашборд или меню; агрегаты в Parquet/SQLite | `app.py`, `menu.py`, `aggregates.py` | `outputs/<profile>/aggregates/*.parquet` |
| Baseline + ≥ 2 модели, метрики, разбиение без утечки | `model.py` (group split, allowlist), `nutriscore.py` | REPORT §7, `tests/test_pipeline.py::test_feature_allowlist_has_no_target_leakage` |
| Специфика №43: широкая таблица 200+ столбцов | разворачивание `nutriments` (7 262 возможных столбца → 15 выбранных), CSV 201 столбец | REPORT §1–2 |
| Специфика №43: пропуски по странам | `audit.py::missingness_by_country`, H1 | REPORT §3, §6 |
| Специфика №43: Nutri-Score prediction vs rule baseline | `nutriscore.py::score_2023`, `model.py` | REPORT §7 |

## Критерии оценки (100 баллов)

| Критерий | Баллы | Основные артефакты |
| --- | ---: | --- |
| Программная реализация | 20 | пакет `offna`, `app.py`, `menu.py`, обработка ошибок, тесты pytest (`tests/`) |
| Данные и предобработка | 15 | `acquire.py`, `etl.py`, `audit.py`, `csv_audit.py`; REPORT §1–3 |
| Базы данных и SQL | 10 | `sql/`, `database.py`, DATABASE.md; REPORT §5 |
| Анализ и визуализация | 15 | `eda.py`, `hypotheses.py`, `docs/figures`; REPORT §6 |
| Методы, сравнение, обоснование | 15 | `benchmark.py`, `model.py`, `nutriscore.py`; REPORT §4, §7 |
| Качество кода и воспроизводимость | 10 | `requirements.txt`, `.python-version`, `Makefile`, фикстура, sha256 снимка, seed, ruff, pytest, история коммитов |
| Письменный отчёт | 5 | [REPORT.md](REPORT.md) |
| Презентация и защита | 10 | `docs/slides.pptx` (12 слайдов, генерируется `make slides` из [SLIDES.md](SLIDES.md) и `docs/results`); докладчики — `_TBD_` |

Комментарии в коде проекта не используются: пояснения вынесены в документы и сообщения коммитов.
Если преподаватель ожидает комментарии (критерий «понятные имена и комментарии»), это стоит обсудить заранее.
