import logging
import os
import shutil
from datetime import datetime as dt

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models

from main.utils import DataQualityTester

logger = logging.getLogger(__name__)


class Data(models.Model):
    path = models.FileField(verbose_name='Файл')
    sep = models.CharField(
        verbose_name='Разделитель',
        max_length=1,
        null=False,
        default=';',
    )
    timestamp = models.CharField(
        verbose_name='Время загрузки',
        editable=False,
        default='',
        max_length=20,
    )

    class Meta:
        verbose_name = 'Неструктурированные данные'
        verbose_name_plural = 'Неструктурированные данные'

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs):
        self.timestamp = dt.now().strftime('%Y%m%d%H%M%S')
        super().save(*args, **kwargs)

        file_path = self.path.path
        basename = os.path.join(self.timestamp, os.path.basename(file_path))
        raw_data_path = os.path.join(settings.RAW_LAYER_DIR, basename)

        os.makedirs(os.path.join(settings.RAW_LAYER_DIR, self.timestamp), exist_ok=True)
        with self.path.open('rb') as src:
            with open(raw_data_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)

        try:
            raw_data = self._read_csv(raw_data_path, self.sep)
        except Exception as exc:
            self._cleanup_layers(self.timestamp)
            raise ValidationError(f'Ошибка чтения файла: {exc}') from exc

        tester = DataQualityTester(raw_data)
        errors = tester.run_all()
        if errors:
            self._cleanup_layers(self.timestamp)
            raise ValidationError(errors)

        os.makedirs(os.path.join(settings.INGEST_LAYER_DIR, self.timestamp), exist_ok=True)
        os.makedirs(os.path.join(settings.TABLE_LAYER_DIR, self.timestamp), exist_ok=True)
        os.makedirs(os.path.join(settings.DISTILLED_LAYER_DIR, self.timestamp), exist_ok=True)

        ingest_file_path = os.path.join(settings.INGEST_LAYER_DIR, basename)
        raw_data.to_csv(ingest_file_path, index=False, encoding='utf-8')

        parquet_basename = basename.replace('.csv', '.parquet')
        table_file_path = os.path.join(settings.TABLE_LAYER_DIR, parquet_basename)
        table_data = self._normalize_columns(raw_data.copy())
        self._write_parquet(table_data, table_file_path)

        distilled_file_path = os.path.join(settings.DISTILLED_LAYER_DIR, parquet_basename)
        self._write_parquet(table_data.drop_duplicates(), distilled_file_path)

        logger.info('Dataset %s processed successfully', self.timestamp)

    def delete(self, *args, **kwargs):
        self._cleanup_layers(self.timestamp)
        super().delete(*args, **kwargs)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_ingest_path(self) -> str:
        basename = os.path.join(self.timestamp, os.path.basename(self.path.name))
        return os.path.join(settings.INGEST_LAYER_DIR, basename)

    def get_table_path(self) -> str:
        basename = os.path.join(
            self.timestamp,
            os.path.basename(self.path.name).replace('.csv', '.parquet'),
        )
        return os.path.join(settings.TABLE_LAYER_DIR, basename)

    def get_distilled_path(self) -> str:
        basename = os.path.join(
            self.timestamp,
            os.path.basename(self.path.name).replace('.csv', '.parquet'),
        )
        return os.path.join(settings.DISTILLED_LAYER_DIR, basename)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_csv(path: str, sep: str) -> pd.DataFrame:
        for encoding in ('utf-8', 'utf-8-sig', 'cp1251'):
            try:
                return pd.read_csv(path, sep=sep, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f'Unable to decode {path} with utf-8, utf-8-sig or cp1251')

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        df.columns = [
            col.encode('ascii', 'ignore').decode('ascii').strip()
            for col in df.columns
        ]
        for col in df.columns:
            if df[col].dtype == object:
                numeric = pd.to_numeric(
                    df[col].astype(str).str.replace(',', '.', regex=False),
                    errors='coerce',
                )
                if numeric.notna().sum() / max(len(df), 1) >= 0.8:
                    df[col] = numeric
        return df

    @staticmethod
    def _write_parquet(df: pd.DataFrame, path: str) -> None:
        try:
            pq.write_table(pa.Table.from_pandas(df), path)
        except Exception:
            renamed = df.copy()
            renamed.columns = [str(i) for i in range(len(df.columns))]
            pq.write_table(pa.Table.from_pandas(renamed), path)

    @staticmethod
    def _cleanup_layers(timestamp: str) -> None:
        for layer_dir in [
            settings.RAW_LAYER_DIR,
            settings.INGEST_LAYER_DIR,
            settings.TABLE_LAYER_DIR,
            settings.DISTILLED_LAYER_DIR,
        ]:
            layer_path = os.path.join(layer_dir, timestamp)
            if os.path.exists(layer_path):
                shutil.rmtree(layer_path)

    def __str__(self) -> str:
        return f'{self.timestamp} {os.path.basename(self.path.name)}'
