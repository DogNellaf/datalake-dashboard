"""
Multi-layer data-lake storage classes.

This module provides the conceptual blueprint for the raw → ingest → table → distilled
data pipeline.  The PySpark/Delta Lake implementations below are intended for use in
Spark-capable environments (e.g. Databricks).  They are imported lazily so the module
can be imported in non-Spark environments without crashing.
"""

import os

try:
    from pyspark.sql import SparkSession, Window
    from pyspark.sql.functions import col, expr, lit, regexp_extract, row_number, to_timestamp
    from delta.tables import DeltaTable

    _SPARK_AVAILABLE = True
except ImportError:
    _SPARK_AVAILABLE = False


def _require_spark():
    if not _SPARK_AVAILABLE:
        raise RuntimeError(
            'PySpark and delta-spark are required for this class. '
            'Install them with: pip install pyspark delta-spark'
        )


class BlobContainer:
    def __init__(self, base_dir: str, layer_title: str, columns_list: list | None = None):
        self.path = os.path.join(base_dir, layer_title)
        self.columns_list = columns_list or []

    def get_dir_content(self) -> list[str]:
        for _, _, files in os.walk(self.path):
            return files
        return []


class RawDF(BlobContainer):
    """Reads a delimited CSV file into a Spark DataFrame."""

    def __init__(self, path: str, columns_list: list | None = None):
        super().__init__(path, 'RAW', columns_list)
        self.has_headers = True
        self.separator = '|'

    def read_file(self) -> bool:
        _require_spark()
        spark = SparkSession.builder.getOrCreate()
        try:
            self.df = (
                spark.read
                .option('header', self.has_headers)
                .option('sep', self.separator)
                .csv(self.path)
            )
            self.columns_list = self.df.columns
            return True
        except Exception as exc:
            print(f'Error reading file: {exc}')
            return False


class TableDF(BlobContainer):
    """Renames and casts columns, then writes Parquet."""

    def __init__(
        self,
        base_dir: str,
        layer_title: str,
        columns_list: list,
        columns_mapping: dict,
        data_types_mapping: dict,
        df,
    ):
        super().__init__(base_dir, layer_title, columns_list)
        self.columns_mapping = columns_mapping
        self.data_types_mapping = data_types_mapping
        self.df = df

    def rename_and_cast_columns(self):
        _require_spark()
        df = self.df
        for init_col, new_col in self.columns_mapping.items():
            if init_col in df.columns:
                df = df.withColumnRenamed(init_col, new_col)
                data_type = self.data_types_mapping.get(new_col)
                if data_type:
                    df = df.withColumn(new_col, df[new_col].cast(data_type))
        return df

    def append_parquet(self, target_path: str) -> None:
        _require_spark()
        self.df.write.mode('append').parquet(target_path)

    @staticmethod
    def add_timestamp_and_source_file(df, time_stamp: str, source_file: str):
        _require_spark()
        return df.withColumn('time_stamp', lit(time_stamp)).withColumn('source_file', lit(source_file))


class DistilledDF(BlobContainer):
    """Deduplicates data from the table layer using a window function."""

    def __init__(
        self,
        base_dir: str,
        layer_title: str,
        columns_list: list,
        table_layer_path: str,
        distilled_layer_pk: list,
        df,
    ):
        super().__init__(base_dir, layer_title, columns_list)
        self.distilled_layer_pk = distilled_layer_pk
        self.df = df
        self.table_layer_path = table_layer_path

    def read_table_layer_parquet(self):
        _require_spark()
        spark = SparkSession.builder.getOrCreate()
        return spark.read.parquet(self.table_layer_path)

    def overwrite_distilled_layer(self, target_path: str) -> None:
        _require_spark()
        self.df.write.mode('overwrite').parquet(target_path)

    def get_deduplicated_df(self):
        _require_spark()
        spark = SparkSession.builder.getOrCreate()
        window = Window.partitionBy(self.distilled_layer_pk).orderBy(col('time_stamp').desc())
        return (
            spark.read.parquet(self.table_layer_path)
            .select(self.columns_list)
            .withColumn('row_number', row_number().over(window))
            .where(col('row_number') == 1)
            .drop('row_number', 'time_stamp')
        )


class DataMartDF(BlobContainer):
    """Manages a Delta Lake data-mart table with upsert support."""

    def __init__(
        self,
        base_dir: str,
        layer_title: str,
        columns_list: list,
        delta_path: str,
        table_name: str,
        columns_and_types: dict,
        df,
    ):
        super().__init__(base_dir, layer_title, columns_list)
        self.delta_path = delta_path
        self.df = df
        self.table_name = table_name
        self.columns_and_types = columns_and_types

    def create_delta_table(self) -> None:
        _require_spark()
        spark = SparkSession.builder.getOrCreate()
        builder = DeltaTable.createIfNotExists(spark).tableName(self.table_name)
        for column, data_type in self.columns_and_types.items():
            builder = builder.addColumn(column, data_type)
        builder.location(self.delta_path).execute()

    def upsert(self, updates_df, primary_keys: list[str]) -> None:
        _require_spark()
        spark = SparkSession.builder.getOrCreate()
        delta_table = DeltaTable.forPath(spark, self.delta_path)
        merge_condition = ' AND '.join(
            f'initial.{c} = updates.{c}' for c in primary_keys
        )
        set_clause = {
            f'initial.{c}': f'updates.{c}'
            for c in updates_df.columns
            if c not in primary_keys
        }
        (
            delta_table.alias('initial')
            .merge(updates_df.alias('updates'), merge_condition)
            .whenMatchedUpdate(set=set_clause)
            .whenNotMatchedInsertAll()
            .execute()
        )
