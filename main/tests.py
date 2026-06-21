import io
import os
import shutil
import tempfile

import pandas as pd
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from main.forms import CustomAuthenticationForm, CustomUserCreationForm
from main.models import Data
from main.utils import DataQualityTester, ErrorsAlerting

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

GOOD_CSV = b"col_a,col_b,col_c\n1,2,3\n4,5,6\n7,8,9\n"
DUPS_CSV = b"col_a,col_b\n1,2\n1,2\n3,4\n"
NULLS_CSV = b"col_a,col_b\n1,\n,4\n"
SEMICOLON_CSV = b"col_a;col_b;col_c\n1;2;3\n4;5;6\n"


def _tmp_layer_dirs():
    """Create a temporary directory tree for all data-lake layers."""
    tmp = tempfile.mkdtemp()
    dirs = dict(
        RAW_LAYER_DIR=os.path.join(tmp, 'raw'),
        INGEST_LAYER_DIR=os.path.join(tmp, 'ingest'),
        TABLE_LAYER_DIR=os.path.join(tmp, 'table'),
        DISTILLED_LAYER_DIR=os.path.join(tmp, 'destilled'),
        MEDIA_ROOT=os.path.join(tmp, 'uploads'),
    )
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return tmp, dirs


# ---------------------------------------------------------------------------
# DataQualityTester — column schema checks
# ---------------------------------------------------------------------------

class CheckColumnsTests(TestCase):
    def setUp(self):
        self.df = pd.read_csv(io.StringIO("a,b,c\n1,2,3\n4,5,6\n"))

    def test_exact_match_returns_none(self):
        self.assertIsNone(DataQualityTester(self.df).check_unexpected_columns(['a', 'b', 'c']))

    def test_extra_column_detected(self):
        result = DataQualityTester(self.df).check_unexpected_columns(['a', 'b'])
        self.assertIn('c', result)

    def test_missing_column_detected(self):
        result = DataQualityTester(self.df).check_unexpected_columns(['a', 'b', 'c', 'd'])
        self.assertIn('d', result)

    def test_both_extra_and_missing_reported(self):
        result = DataQualityTester(self.df).check_unexpected_columns(['a', 'b', 'z'])
        self.assertIn('c', result)
        self.assertIn('z', result)


# ---------------------------------------------------------------------------
# DataQualityTester — duplicate checks
# ---------------------------------------------------------------------------

class CheckDuplicatesTests(TestCase):
    def test_clean_data_returns_none(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n3,4\n"))
        self.assertIsNone(DataQualityTester(df).check_duplicates())

    def test_full_row_duplicates_detected(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n1,2\n3,4\n"))
        result = DataQualityTester(df).check_duplicates()
        self.assertIsNotNone(result)

    def test_primary_key_duplicates_detected(self):
        df = pd.read_csv(io.StringIO("id,val\n1,x\n1,y\n2,z\n"))
        result = DataQualityTester(df).check_duplicates(primary_key=['id'])
        self.assertIsNotNone(result)

    def test_no_pk_duplicates_returns_none(self):
        df = pd.read_csv(io.StringIO("id,val\n1,x\n2,x\n"))
        self.assertIsNone(DataQualityTester(df).check_duplicates(primary_key=['id']))


# ---------------------------------------------------------------------------
# DataQualityTester — null checks
# ---------------------------------------------------------------------------

class CheckNullsTests(TestCase):
    def test_no_nulls_returns_none(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n3,4\n"))
        self.assertIsNone(DataQualityTester(df).check_nulls())

    def test_null_detected(self):
        df = pd.read_csv(io.StringIO("a,b\n1,\n3,4\n"))
        result = DataQualityTester(df).check_nulls()
        self.assertIsNotNone(result)
        self.assertIn('b', result)

    def test_subset_columns_ok(self):
        df = pd.read_csv(io.StringIO("a,b\n1,\n3,4\n"))
        self.assertIsNone(DataQualityTester(df).check_nulls(columns=['a']))

    def test_nonexistent_column_ignored(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n"))
        self.assertIsNone(DataQualityTester(df).check_nulls(columns=['z']))


# ---------------------------------------------------------------------------
# DataQualityTester — special characters
# ---------------------------------------------------------------------------

class CheckSpecialCharsTests(TestCase):
    def test_clean_column_returns_none(self):
        df = pd.DataFrame({'name': ['Alice', 'Bob']})
        self.assertIsNone(DataQualityTester(df).check_special_characters(['name']))

    def test_special_char_detected(self):
        df = pd.DataFrame({'name': ['Alice', '<script>alert(1)</script>']})
        result = DataQualityTester(df).check_special_characters(['name'])
        self.assertIsNotNone(result)
        self.assertIn('name', result)

    def test_missing_column_skipped(self):
        df = pd.read_csv(io.StringIO("a\n1\n2\n"))
        self.assertIsNone(DataQualityTester(df).check_special_characters(['z']))


# ---------------------------------------------------------------------------
# DataQualityTester — numeric conversion
# ---------------------------------------------------------------------------

class CheckNumericColumnsTests(TestCase):
    def test_all_numeric_returns_none(self):
        df = pd.DataFrame({'val': ['1', '2', '3.5']})
        self.assertIsNone(DataQualityTester(df).check_numeric_columns(['val']))

    def test_comma_decimal_accepted(self):
        df = pd.DataFrame({'val': ['1,5', '2,0']})
        self.assertIsNone(DataQualityTester(df).check_numeric_columns(['val']))

    def test_non_numeric_detected(self):
        df = pd.DataFrame({'val': ['1', 'abc', '3']})
        result = DataQualityTester(df).check_numeric_columns(['val'])
        self.assertIsNotNone(result)
        self.assertIn('val', result)

    def test_missing_column_skipped(self):
        df = pd.DataFrame({'a': [1]})
        self.assertIsNone(DataQualityTester(df).check_numeric_columns(['z']))


# ---------------------------------------------------------------------------
# DataQualityTester — run_all and helpers
# ---------------------------------------------------------------------------

class RunAllTests(TestCase):
    def test_clean_data_no_errors(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n3,4\n"))
        self.assertEqual(DataQualityTester(df).run_all(), [])

    def test_duplicates_produce_error(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n1,2\n"))
        errors = DataQualityTester(df).run_all()
        self.assertEqual(len(errors), 1)

    def test_nulls_produce_error(self):
        df = pd.read_csv(io.StringIO("a,b\n1,\n3,4\n"))
        errors = DataQualityTester(df).run_all()
        self.assertGreater(len(errors), 0)

    def test_schema_and_dup_errors_accumulate(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n1,2\n"))
        tester = DataQualityTester(df)
        tester.run_all(expected_columns=['a', 'b', 'missing_col'])
        self.assertGreater(len(tester.errors), 1)

    def test_has_errors_true(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n1,2\n"))
        tester = DataQualityTester(df)
        tester.run_all()
        self.assertTrue(tester.has_errors())

    def test_has_errors_false(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n"))
        tester = DataQualityTester(df)
        tester.run_all()
        self.assertFalse(tester.has_errors())

    def test_raise_if_errors(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n1,2\n"))
        tester = DataQualityTester(df)
        tester.run_all()
        with self.assertRaises(ValueError):
            tester.raise_if_errors()

    def test_raise_if_no_errors_does_nothing(self):
        df = pd.read_csv(io.StringIO("a,b\n1,2\n"))
        tester = DataQualityTester(df)
        tester.run_all()
        tester.raise_if_errors()  # Should not raise


# ---------------------------------------------------------------------------
# DataQualityTester — column stats
# ---------------------------------------------------------------------------

class ColumnStatsTests(TestCase):
    def test_numeric_column_stats(self):
        df = pd.DataFrame({'val': [1.0, 2.0, 3.0, None]})
        stats = DataQualityTester(df).get_column_stats('val')
        self.assertEqual(stats['count'], 3)
        self.assertEqual(stats['null_count'], 1)
        self.assertAlmostEqual(stats['mean'], 2.0)
        self.assertAlmostEqual(stats['min'], 1.0)
        self.assertAlmostEqual(stats['max'], 3.0)

    def test_string_column_has_no_numeric_stats(self):
        df = pd.DataFrame({'name': ['Alice', 'Bob', None]})
        stats = DataQualityTester(df).get_column_stats('name')
        self.assertEqual(stats['count'], 2)
        self.assertEqual(stats['null_count'], 1)
        self.assertNotIn('mean', stats)

    def test_missing_column_returns_empty(self):
        df = pd.DataFrame({'a': [1]})
        self.assertEqual(DataQualityTester(df).get_column_stats('z'), {})


# ---------------------------------------------------------------------------
# ErrorsAlerting — markdown formatting
# ---------------------------------------------------------------------------

class ErrorsAlertingTests(TestCase):
    def setUp(self):
        self.df = pd.DataFrame({'File': ['a.csv'], 'Error': ['Duplicate']})
        self.alerter = ErrorsAlerting(self.df, 'http://example.com/webhook')

    def test_markdown_contains_column_headers(self):
        md = self.alerter.df_to_markdown_table()
        self.assertIn('File', md)
        self.assertIn('Error', md)

    def test_markdown_contains_data(self):
        md = self.alerter.df_to_markdown_table()
        self.assertIn('a.csv', md)
        self.assertIn('Duplicate', md)

    def test_markdown_has_separator_row(self):
        md = self.alerter.df_to_markdown_table()
        self.assertIn('---', md)


# ---------------------------------------------------------------------------
# Data model — static helpers
# ---------------------------------------------------------------------------

class DataNormalizeColumnsTests(TestCase):
    def test_strips_surrounding_spaces(self):
        df = pd.DataFrame({' col_a ': [1], 'col_b': [2]})
        result = Data._normalize_columns(df)
        self.assertIn('col_a', result.columns)

    def test_strips_non_ascii(self):
        df = pd.DataFrame({'Колонка': [1, 2]})
        result = Data._normalize_columns(df)
        for col in result.columns:
            self.assertTrue(col.isascii())

    def test_numeric_string_column_converted(self):
        df = pd.DataFrame({'val': ['1,5', '2,0', '3,0']})
        result = Data._normalize_columns(df)
        self.assertTrue(pd.api.types.is_numeric_dtype(result['val']))

    def test_mostly_non_numeric_column_stays_object(self):
        df = pd.DataFrame({'mixed': ['1', 'abc', 'xyz', 'foo', 'bar']})
        result = Data._normalize_columns(df)
        self.assertEqual(result['mixed'].dtype, object)


class DataWriteParquetTests(TestCase):
    def test_writes_valid_parquet(self):
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.parquet')
            df = pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})
            Data._write_parquet(df, path)
            result = pq.read_table(path).to_pandas()
            self.assertEqual(list(result['a']), [1, 2])

    def test_fallback_renames_columns_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.parquet')
            df = pd.DataFrame({'Колонка': [1, 2]})
            Data._write_parquet(df, path)
            self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# Data model — full save / delete (isolated temp dirs)
# ---------------------------------------------------------------------------

class DataModelSaveDeleteTests(TestCase):
    def _run_with_tmp(self, fn):
        tmp, dirs = _tmp_layer_dirs()
        try:
            with self.settings(**dirs):
                fn(tmp, dirs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _instance(self, csv_content=GOOD_CSV, sep=','):
        uploaded = SimpleUploadedFile('data.csv', csv_content, content_type='text/csv')
        return Data(path=uploaded, sep=sep)

    def test_save_creates_ingest_file(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            self.assertTrue(os.path.exists(inst.get_ingest_path()))
        self._run_with_tmp(check)

    def test_save_creates_table_file(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            self.assertTrue(os.path.exists(inst.get_table_path()))
        self._run_with_tmp(check)

    def test_save_creates_distilled_file(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            self.assertTrue(os.path.exists(inst.get_distilled_path()))
        self._run_with_tmp(check)

    def test_save_semicolon_csv(self):
        def check(tmp, dirs):
            inst = self._instance(csv_content=SEMICOLON_CSV, sep=';')
            inst.save()
            self.assertTrue(os.path.exists(inst.get_ingest_path()))
        self._run_with_tmp(check)

    def test_timestamp_is_14_digits(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            self.assertEqual(len(inst.timestamp), 14)
            self.assertTrue(inst.timestamp.isdigit())
        self._run_with_tmp(check)

    def test_delete_removes_layer_dirs(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            ts = inst.timestamp
            inst.delete()
            for key, layer_dir in dirs.items():
                if key == 'MEDIA_ROOT':
                    continue
                self.assertFalse(
                    os.path.exists(os.path.join(layer_dir, ts)),
                    f"Directory for layer {key} was not removed",
                )
        self._run_with_tmp(check)

    def test_str_contains_filename(self):
        def check(tmp, dirs):
            inst = self._instance()
            inst.save()
            self.assertIn('data.csv', str(inst))
        self._run_with_tmp(check)

    def test_distilled_parquet_is_readable(self):
        def check(tmp, dirs):
            inst = self._instance(csv_content=GOOD_CSV)
            inst.save()
            import pyarrow.parquet as pq
            df = pq.read_table(inst.get_distilled_path()).to_pandas()
            self.assertGreater(len(df), 0)
            self.assertFalse(df.duplicated().any())
        self._run_with_tmp(check)


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

class CustomUserCreationFormTests(TestCase):
    def _data(self, **overrides):
        base = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password1': 'Str0ng!Pass#2024',
            'password2': 'Str0ng!Pass#2024',
        }
        base.update(overrides)
        return base

    def test_valid_form(self):
        form = CustomUserCreationForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_email_invalid(self):
        form = CustomUserCreationForm(data=self._data(email=''))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_invalid_email_invalid(self):
        form = CustomUserCreationForm(data=self._data(email='not-an-email'))
        self.assertFalse(form.is_valid())

    def test_password_mismatch_invalid(self):
        form = CustomUserCreationForm(data=self._data(password2='Different!123'))
        self.assertFalse(form.is_valid())

    def test_fields_have_bootstrap_class(self):
        form = CustomUserCreationForm()
        for field_name in ['username', 'email', 'password1', 'password2']:
            attrs = form.fields[field_name].widget.attrs
            self.assertIn('form-control', attrs.get('class', ''), field_name)

    def test_save_persists_email(self):
        form = CustomUserCreationForm(data=self._data())
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.email, 'test@example.com')

    def test_no_verbose_help_text(self):
        form = CustomUserCreationForm()
        for field_name in ['username', 'password1', 'password2']:
            self.assertEqual(form.fields[field_name].help_text, '')


class CustomAuthenticationFormTests(TestCase):
    def test_fields_have_bootstrap_class(self):
        form = CustomAuthenticationForm()
        for field_name in ['username', 'password']:
            attrs = form.fields[field_name].widget.attrs
            self.assertIn('form-control', attrs.get('class', ''), field_name)

    def test_fields_have_placeholder(self):
        form = CustomAuthenticationForm()
        for field_name in ['username', 'password']:
            self.assertIn('placeholder', form.fields[field_name].widget.attrs)


# ---------------------------------------------------------------------------
# Views — public
# ---------------------------------------------------------------------------

class IndexViewTests(TestCase):
    def test_redirects_to_login(self):
        response = self.client.get(reverse('index'))
        self.assertRedirects(response, reverse('login'))


class RegisterViewTests(TestCase):
    def _post(self, **overrides):
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'Str0ng!Pass#2024',
            'password2': 'Str0ng!Pass#2024',
        }
        data.update(overrides)
        return self.client.post(reverse('register'), data)

    def test_get_renders_template(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')

    def test_post_valid_redirects(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/', response['Location'])

    def test_post_creates_user(self):
        self._post()
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_post_user_is_staff(self):
        self._post()
        self.assertTrue(User.objects.get(username='newuser').is_staff)

    def test_post_invalid_stays_on_page(self):
        response = self.client.post(reverse('register'), {'username': ''})
        self.assertEqual(response.status_code, 200)

    def test_group_created_if_missing(self):
        Group.objects.filter(name='Пользователи').delete()
        self._post()
        self.assertTrue(Group.objects.filter(name='Пользователи').exists())


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='ValidPass!1')

    def test_get_renders_template(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')

    def test_valid_credentials_redirect(self):
        response = self.client.post(reverse('login'), {'username': 'u', 'password': 'ValidPass!1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/', response['Location'])

    def test_invalid_credentials_stay(self):
        response = self.client.post(reverse('login'), {'username': 'u', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Views — protected (login required)
# ---------------------------------------------------------------------------

class ProtectedViewsLoginRequiredTests(TestCase):
    def test_graph_requires_login(self):
        r = self.client.get(reverse('graph', args=['20240101120000']))
        self.assertRedirects(r, '/login/?next=/graph/20240101120000/')

    def test_preview_requires_login(self):
        r = self.client.get(reverse('preview', args=['20240101120000']))
        self.assertEqual(r.status_code, 302)

    def test_export_csv_requires_login(self):
        r = self.client.get(reverse('export_csv', args=['20240101120000']))
        self.assertEqual(r.status_code, 302)

    def test_get_plot_data_requires_login(self):
        r = self.client.post(reverse('get_plot_data'))
        self.assertEqual(r.status_code, 302)

    def test_get_column_stats_requires_login(self):
        r = self.client.post(reverse('get_column_stats'))
        self.assertEqual(r.status_code, 302)


class ProtectedViewsWith404Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pass', is_staff=True)
        self.client.login(username='u', password='pass')

    def test_graph_404_for_unknown_timestamp(self):
        r = self.client.get(reverse('graph', args=['00000000000000']))
        self.assertEqual(r.status_code, 404)

    def test_preview_404_for_unknown_timestamp(self):
        r = self.client.get(reverse('preview', args=['00000000000000']))
        self.assertEqual(r.status_code, 404)

    def test_export_csv_404_for_unknown_timestamp(self):
        r = self.client.get(reverse('export_csv', args=['00000000000000']))
        self.assertEqual(r.status_code, 404)


class GetPlotDataViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pass', is_staff=True)
        self.client.login(username='u', password='pass')

    def test_get_returns_405(self):
        r = self.client.get(reverse('get_plot_data'))
        self.assertEqual(r.status_code, 405)

    def test_missing_params_returns_400(self):
        r = self.client.post(reverse('get_plot_data'), {})
        self.assertEqual(r.status_code, 400)

    def test_unknown_timestamp_returns_404(self):
        r = self.client.post(reverse('get_plot_data'), {
            'x_column': 'a',
            'y_column': 'b',
            'timestamp': '00000000000000',
        })
        self.assertEqual(r.status_code, 404)


class GetColumnStatsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pass', is_staff=True)
        self.client.login(username='u', password='pass')

    def test_get_returns_405(self):
        r = self.client.get(reverse('get_column_stats'))
        self.assertEqual(r.status_code, 405)

    def test_missing_params_returns_400(self):
        r = self.client.post(reverse('get_column_stats'), {})
        self.assertEqual(r.status_code, 400)

    def test_unknown_timestamp_returns_404(self):
        r = self.client.post(reverse('get_column_stats'), {
            'column': 'a',
            'timestamp': '00000000000000',
        })
        self.assertEqual(r.status_code, 404)
