# DataLake

[Русский](README.ru.md)

A Django web application for uploading, processing, and visualising tabular retail/sales data.  Files are passed through a four-layer data pipeline and exposed via an interactive chart builder and data-preview interface.

---

## Features

- **User management** — registration and login with staff-level access control
- **CSV upload** — configurable column separator, automatic encoding detection (UTF-8 / CP-1251)
- **Four-layer ETL pipeline**
  - **Raw** — original file stored verbatim
  - **Ingest** — UTF-8 normalised CSV
  - **Table** — Parquet with type-inferred columns
  - **Distilled** — deduplicated Parquet
- **Data quality checks** — schema validation, duplicate detection, null detection, special-character scanning, numeric-conversion validation
- **Interactive chart builder** — drag-and-drop column selection, scatter / line / bar chart types, powered by Plotly
- **Data preview** — first 100 rows rendered as an HTML table
- **Column statistics** — count, null count, unique count, min / max / mean / std for numeric columns
- **CSV export** — streaming download of the ingested dataset
- **Django admin integration** — upload datasets and jump to chart / preview / export in one click

---

## Architecture

```
Browser upload
      │
      ▼
┌─────────────┐
│  Raw Layer  │  Original file copy
└──────┬──────┘
       ▼
┌──────────────┐
│ Ingest Layer │  UTF-8 CSV, unchanged schema
└──────┬───────┘
       ▼
┌─────────────┐
│ Table Layer │  Parquet, ASCII column names, numeric columns cast
└──────┬──────┘
       ▼
┌──────────────────┐
│ Distilled Layer  │  Parquet, duplicate rows removed
└──────────────────┘
```

All layers are stored under `media/` in timestamp-named subdirectories (`YYYYMMDDHHMMSS`), enabling multiple concurrent datasets.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Web framework | Django 4.2 |
| Data processing | pandas, pyarrow |
| Visualisation | Plotly.js |
| UI | Bootstrap 5, jQuery UI |
| Database | SQLite (development) |

---

## Installation

**Requirements:** Python 3.11+

```bash
# Clone the repository
git clone <repository-url>
cd app

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Apply database migrations
python manage.py migrate

# Run the development server
python manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Insecure dev key | Django secret key — **must be set in production** |
| `DJANGO_DEBUG` | `true` | Set to `false` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` (when DEBUG=true) | Comma-separated list of allowed hostnames |

---

## Usage

1. **Register** a new account at `/register/`.
2. **Log in** and navigate to the **Django admin** panel (`/admin/`).
3. Click **Добавить** (Add) under *Неструктурированные данные* to upload a CSV file.  Set the column separator to match your file (default: `;`).
4. After a successful upload the record appears in the list with three action buttons:
   - **График** — open the interactive chart builder
   - **Предпросмотр** — preview the first 100 rows
   - **Экспорт CSV** — download the processed file
5. In the chart builder, drag columns from the left panel onto the **X** and **Y** drop zones, select a chart type, and click **Построить график**.

### Supported CSV formats

- Separator: any single character (default `;`)
- Encoding: UTF-8, UTF-8-BOM, or CP-1251 (auto-detected)
- Headers: required in the first row
- Decimal separator: `.` or `,` (commas are converted automatically)

---

## Running Tests

```bash
python manage.py test main.tests
```

The test suite covers data-quality checks, model helpers, forms, and all HTTP endpoints (80 tests).

---

## Project Structure

```
app/
├── app/                  # Django project settings and URL routing
│   ├── settings.py
│   └── urls.py
├── main/                 # Core application
│   ├── models.py         # Data model and ETL pipeline
│   ├── views.py          # Views and API endpoints
│   ├── forms.py          # Auth forms
│   ├── admin.py          # Admin configuration
│   ├── utils.py          # DataQualityTester, ErrorsAlerting
│   ├── tests.py          # Test suite (80 tests)
│   ├── storage/
│   │   └── dfs.py        # PySpark/Delta Lake reference implementation
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── register.html
│       ├── graph.html
│       └── preview.html
├── media/                # Data lake layers (auto-created)
│   ├── raw/
│   ├── ingest/
│   ├── table/
│   └── destilled/
└── requirements.txt
```

---

## License

MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
