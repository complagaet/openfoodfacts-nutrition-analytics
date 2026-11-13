# Open Food Facts: Nutrition and Product Analytics

[![CI](https://github.com/complagaet/openfoodfacts-nutrition-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/complagaet/openfoodfacts-nutrition-analytics/actions/workflows/ci.yml)

Итоговый проект №43 по дисциплине **Programming for Data Analysis and Database**
(название курса взято из исходного задания; см. «Открытые вопросы»).
Кластер 8: **Large-Scale Data Processing (Pandas, Polars, Dask, Parquet)**.

Проект обрабатывает полный снимок Open Food Facts (4 906 869 продуктов, 7,5 ГиБ Parquet),
проводит аудит качества, сравнивает Pandas и Polars по времени и пиковой памяти,
загружает нормализованную схему в SQLite, проверяет две гипотезы и сравнивает
прогноз Nutri-Score моделями с официальным правилом.

## Команда

Группа **AAI-2606M**: Pavel Lukoyanov, Arsen Ozhetov, Ayan Amantay.
Распределение вклада фиксируется в [отчёте](docs/REPORT.md#вклад-участников).

## Быстрый запуск: чистый клон → дашборд (≈1 минута, без интернета для данных)

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/) (или обычный `pip`, см. ниже).
Демо работает на закоммиченной выборке `tests/fixtures/off_sample.parquet`
(10 000 продуктов, 1,4 МБ, ODbL).

```bash
git clone git@github.com:complagaet/openfoodfacts-nutrition-analytics.git
cd openfoodfacts-nutrition-analytics
make setup                 # .venv на Python 3.12 + зависимости из requirements-dev.txt
make pipeline              # ETL → аудит → агрегаты → бенчмарк → SQLite → модели → EDA (PROFILE=demo)
make test                  # pytest
make app                   # Streamlit: http://localhost:8501
```

Без `uv`:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
make pipeline
```

Пакет `offna` не устанавливается в `.venv`: `make` запускает его прямо из `src/`, pytest берёт `src/`
через `pythonpath`, поэтому правки кода видны сразу и устаревшая копия в site-packages
не может подменить исходники. (Editable-установка не годится: на macOS в `~/Documents`
система помечает её `.pth` скрытым, и Python 3.12 его пропускает.)

Консольное меню вместо дашборда: `make menu`. Презентация `docs/slides.pptx` пересобирается
из `docs/SLIDES.md` и `docs/results` командой `make slides` (python-pptx из `requirements-dev.txt`).
Отдельные этапы: `make etl`, `make audit`, `make sql` и т. д. (см. `Makefile`).
Полный набор транзитивных версий, проверенный в чистом окружении, — `requirements-lock.txt`
(`pip install -r requirements-lock.txt` вместо `requirements.txt`).

## Полный прогон на всём снимке

```bash
make acquire                     # скачивает food.parquet (7,5 ГиБ) закреплённой ревизии и пишет data/SNAPSHOT.json
make pipeline PROFILE=full       # ≈4 минуты на MacBook Air M4 / 24 ГБ (сумма замеров этапов)
make acquire-csv && make csv-audit PROFILE=full   # необязательная проверка CSV-выгрузки (20 МБ)
```

Пик RSS любого этапа полного прогона не превышает 3,6 ГБ (замеры — в
[docs/results](docs/results)). Данные, `outputs/` и SQLite в Git не попадают;
итоговые таблицы и JSON-отчёты полного прогона скопированы в `docs/results/`.

## Структура

| Путь | Назначение |
| --- | --- |
| `src/offna/acquire.py` | Загрузка снимка, выборки, фикстура, `SNAPSHOT.json` (URL, sha256, размер, строки, столбцы) |
| `src/offna/csv_reader.py`, `csv_audit.py` | Чтение TSV с проверкой числа полей и сравнение с наивным `pd.read_csv` |
| `src/offna/etl.py`, `categories.py` | Чанковый ETL: разворачивание `nutriments`, единицы, очистка, типы, партиционированный Parquet |
| `src/offna/audit.py` | Пропуски по полям/странам/группам, дубликаты, недопустимые значения, даты, выбросы |
| `src/offna/engines.py`, `benchmark.py`, `bench_worker.py` | Pandas default / Pandas chunked / Polars lazy в отдельных процессах |
| `src/offna/database.py`, `sql/` | Схема SQLite, потоковая загрузка, 10 SQL-запросов |
| `src/offna/nutriscore.py`, `model.py` | Правило Nutri-Score 2021/2023, Dummy, LogisticRegression, HistGradientBoosting |
| `src/offna/eda.py`, `hypotheses.py` | Описательная статистика, 5 графиков, проверка H1/H2 |
| `src/offna/aggregates.py`, `dashboard.py`, `app.py`, `menu.py` | Агрегаты для интерфейса, Streamlit, консольное меню |
| `tests/` | pytest: парсер, правило, равенство движков, SQL, дашборд, меню |
| `docs/` | Отчёт, слайды, ER-диаграмма, карта критериев, результаты |

## Документы

- [Отчёт](docs/REPORT.md) и [план презентации](docs/SLIDES.md)
- [Схема БД и запросы](docs/DATABASE.md)
- [Карта критериев оценки → код → подтверждение](docs/RUBRIC_MAP.md)
- [Критерии оценки](docs/ASSESSMENT.md), [описание проекта](docs/PROJECT_BRIEF.md), [источники](docs/SOURCES.md)
- [Руководство для подготовки к защите (English)](docs/DEFENSE_GUIDE.md)

## Данные и лицензия

Данные: [Open Food Facts](https://world.openfoodfacts.org), снимок
[openfoodfacts/product-database](https://huggingface.co/datasets/openfoodfacts/product-database)
`food.parquet`, ревизия `11cc007d7e6709c304405410e4fb23720c4a4aa2` (закреплена в `src/offna/config.py`),
получен 12.11.2026, sha256 `be58c2f3b3987e06c3cb0d87726c0da6c5242e7fb11e331f7e1dfcae8906707c`.
`make acquire` скачивает именно эту ревизию и сверяет sha256 с ETag хаба; другая ревизия —
`.venv/bin/python -I -m offna acquire --source parquet --revision <sha>`.
База распространяется по [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/),
содержимое — по Database Contents License. Фикстура `tests/fixtures/off_sample.parquet`
является производной базой и распространяется на тех же условиях ODbL с указанием
источника. Лицензия собственного кода проекта командой пока не выбрана.

## Открытые вопросы

- Название курса: в README указано «Programming for Data Analysis and Database»;
  в оценке задания встречается иной вариант. Сверить с Moodle.
- Утверждение темы преподавателем, дата экзамена, доступ преподавателя к приватному репозиторию.
- Распределение вклада участников (таблица в отчёте заполнена заглушками).
