import re
from datetime import datetime

import pandas as pd
import requests


class DataQualityTester:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.errors: list[str] = []

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def has_errors(self) -> bool:
        return bool(self.errors)

    def raise_if_errors(self) -> None:
        if self.errors:
            raise ValueError("Data quality checks failed:\n" + "\n".join(self.errors))

    def check_unexpected_columns(self, expected_columns: list[str]) -> str | None:
        current = set(self.df.columns)
        expected = set(expected_columns)
        extra = sorted(current - expected)
        missing = sorted(expected - current)
        parts = []
        if extra:
            parts.append(f"Unexpected columns: {extra}")
        if missing:
            parts.append(f"Missing required columns: {missing}")
        return "\n".join(parts) if parts else None

    def check_duplicates(self, primary_key: list[str] | None = None) -> str | None:
        subset = primary_key or None
        count = int(self.df.duplicated(subset=subset).sum())
        if count > 0:
            key_desc = f" on key {primary_key}" if primary_key else ""
            return f"Found {count} duplicate row(s){key_desc}"
        return None

    def check_nulls(self, columns: list[str] | None = None) -> str | None:
        cols = columns if columns is not None else self.df.columns.tolist()
        null_cols = [c for c in cols if c in self.df.columns and self.df[c].isnull().any()]
        if null_cols:
            return f"Null values found in columns: {null_cols}"
        return None

    def check_special_characters(
        self,
        columns: list[str],
        pattern: str = r'[<>&\'\\"\\\\]',
    ) -> str | None:
        cols_with_special = []
        for col in columns:
            if col not in self.df.columns:
                continue
            if self.df[col].astype(str).str.contains(pattern, regex=True, na=False).any():
                cols_with_special.append(col)
        if cols_with_special:
            return f"Special characters found in columns: {cols_with_special}"
        return None

    def check_numeric_columns(self, columns: list[str]) -> str | None:
        failed = []
        for col in columns:
            if col not in self.df.columns:
                continue
            converted = pd.to_numeric(
                self.df[col].astype(str).str.replace(',', '.', regex=False),
                errors='coerce',
            )
            if converted.isnull().any():
                failed.append(col)
        if failed:
            return f"Columns that cannot be converted to numeric: {failed}"
        return None

    def run_all(
        self,
        expected_columns: list[str] | None = None,
        primary_key: list[str] | None = None,
        check_null_columns: list[str] | None = None,
        check_special_char_columns: list[str] | None = None,
        numeric_columns: list[str] | None = None,
    ) -> list[str]:
        if expected_columns is not None:
            result = self.check_unexpected_columns(expected_columns)
            if result:
                self.add_error(result)

        result = self.check_duplicates(primary_key)
        if result:
            self.add_error(result)

        result = self.check_nulls(check_null_columns)
        if result:
            self.add_error(result)

        if check_special_char_columns:
            result = self.check_special_characters(check_special_char_columns)
            if result:
                self.add_error(result)

        if numeric_columns:
            result = self.check_numeric_columns(numeric_columns)
            if result:
                self.add_error(result)

        return self.errors

    def get_column_stats(self, column: str) -> dict:
        if column not in self.df.columns:
            return {}
        series = self.df[column]
        stats: dict = {
            'count': int(series.count()),
            'null_count': int(series.isnull().sum()),
            'unique_count': int(series.nunique()),
        }
        numeric = pd.to_numeric(series, errors='coerce')
        if numeric.notna().sum() > 0:
            stats.update({
                'min': float(numeric.min()),
                'max': float(numeric.max()),
                'mean': float(numeric.mean()),
                'std': float(numeric.std()),
            })
        return stats


class ErrorsAlerting:
    def __init__(self, df: pd.DataFrame, webhook_url: str):
        self.df = df
        self.webhook_url = webhook_url

    def df_to_markdown_table(self) -> str:
        max_widths = [len(str(col)) for col in self.df.columns]
        for _, row in self.df.iterrows():
            for i, value in enumerate(row):
                max_widths[i] = max(max_widths[i], len(str(value)))

        lines = []
        lines.append(
            "| " + " | ".join(col.ljust(w) for col, w in zip(self.df.columns, max_widths)) + " |"
        )
        lines.append("| " + " | ".join("-" * w for w in max_widths) + " |")
        for _, row in self.df.iterrows():
            lines.append(
                "| " + " | ".join(str(v).ljust(w) for v, w in zip(row, max_widths)) + " |"
            )
        return "\n".join(lines)

    def send_errors_to_webhook(self, markdown_table: str) -> bool:
        message = (
            "<font color='red'>**!PIPELINE FAILED!**</font>\n\n"
            f"Run date: {datetime.now().isoformat()}\n\n"
            "**Data quality errors:**\n\n"
            + markdown_table
        )
        payload = {"text": message}
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False
