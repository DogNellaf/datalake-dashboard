# DataLake

> 🇬🇧 English | [🇷🇺 Русский](README.ru.md)

A Django web application for uploading, processing, and visualising tabular retail/sales data. Files are passed through a four-layer data pipeline and exposed via an interactive chart builder and data-preview interface.

## Features

- User management — registration and login with staff-level access control
- CSV upload — configurable column separator, automatic encoding detection (UTF-8 / CP-1251)
- Four-layer ETL pipeline: Raw (original file), Ingest (UTF-8 normalised CSV), Table (Parquet with type-inferred columns), Distilled (deduplicated Parquet)
- Data quality checks — schema validation, duplicate detection, null detection, special-character scanning, numeric-conversion validation
- Interactive chart builder — drag-and-drop column selection, scatter / line / bar chart types, powered by Plotly
- Data preview — first 100 rows rendered as an HTML table
- Column statistics — count, null count, unique count, min / max / mean / std for numeric columns
- CSV export — streaming download of the ingested dataset
- Django admin integration — upload datasets and jump to chart / preview / export in one click

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Django 4.2 |
| Data processing | pandas, pyarrow |
| Visualisation | Plotly.js |
| UI | Bootstrap 5, jQuery UI |
| Database | SQLite (development) |

## Requirements

- Python 3.11+

## Installation

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

The application will be available at `http://127.0.0.1:8000/`.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django secret key — must be set in production | Insecure dev key |
| `DJANGO_DEBUG` | Enable debug mode (`True`/`False`) | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of allowed hostnames | `*` (when DEBUG=true) |

## Running Tests

```bash
python manage.py test main.tests
```

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

## License

[MIT](LICENSE)
