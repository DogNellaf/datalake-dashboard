import csv
import io
import os

import pandas as pd
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from main.forms import CustomAuthenticationForm, CustomUserCreationForm
from main.models import Data
from main.utils import DataQualityTester


def index(request):
    return redirect('login')


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = True
            user.save()
            group, _ = Group.objects.get_or_create(name='Пользователи')
            group.user_set.add(user)
            authenticated = authenticate(
                request,
                username=user.username,
                password=form.cleaned_data['password1'],
            )
            if authenticated:
                login(request, authenticated)
            return redirect('admin:index')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = CustomAuthenticationForm(data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('admin:index')
    else:
        form = CustomAuthenticationForm()
    return render(request, 'login.html', {'form': form})


@login_required
def graph_building_view(request, timestamp):
    dataset = get_object_or_404(Data, timestamp=timestamp)
    columns = []
    path = dataset.get_ingest_path()
    if os.path.exists(path):
        df = pd.read_csv(path, nrows=0)
        columns = df.columns.tolist()
    return render(request, 'graph.html', {'columns': columns, 'timestamp': timestamp})


@login_required
def get_plot_data(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    x_column = request.POST.get('x_column')
    y_column = request.POST.get('y_column')
    timestamp = request.POST.get('timestamp')

    if not all([x_column, y_column, timestamp]):
        return JsonResponse({'error': 'Отсутствуют обязательные параметры.'}, status=400)

    dataset = Data.objects.filter(timestamp=timestamp).first()
    if not dataset:
        return JsonResponse({'error': 'Данные не найдены.'}, status=404)

    path = dataset.get_ingest_path()
    if not os.path.exists(path):
        return JsonResponse({'error': 'Файл не найден.'}, status=404)

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if x_column not in df.columns or y_column not in df.columns:
        return JsonResponse({'error': 'Указанный столбец не существует.'}, status=400)

    return JsonResponse({
        'x_data': df[x_column].tolist(),
        'y_data': df[y_column].tolist(),
    })


@login_required
def data_preview(request, timestamp):
    dataset = get_object_or_404(Data, timestamp=timestamp)
    path = dataset.get_ingest_path()
    columns: list = []
    rows: list = []
    total_rows = 0

    if os.path.exists(path):
        df = pd.read_csv(path, nrows=100)
        columns = df.columns.tolist()
        rows = df.values.tolist()
        total_rows = sum(1 for _ in open(path)) - 1

    return render(request, 'preview.html', {
        'dataset': dataset,
        'columns': columns,
        'rows': rows,
        'timestamp': timestamp,
        'total_rows': total_rows,
        'preview_limit': 100,
    })


@login_required
def get_column_stats(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    column = request.POST.get('column')
    timestamp = request.POST.get('timestamp')

    if not all([column, timestamp]):
        return JsonResponse({'error': 'Отсутствуют обязательные параметры.'}, status=400)

    dataset = Data.objects.filter(timestamp=timestamp).first()
    if not dataset:
        return JsonResponse({'error': 'Данные не найдены.'}, status=404)

    path = dataset.get_ingest_path()
    if not os.path.exists(path):
        return JsonResponse({'error': 'Файл не найден.'}, status=404)

    try:
        df = pd.read_csv(path)
        tester = DataQualityTester(df)
        stats = tester.get_column_stats(column)
        if not stats:
            return JsonResponse({'error': f'Столбец "{column}" не найден.'}, status=400)
        return JsonResponse(stats)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required
def export_csv(request, timestamp):
    dataset = get_object_or_404(Data, timestamp=timestamp)
    path = dataset.get_ingest_path()

    if not os.path.exists(path):
        return JsonResponse({'error': 'Файл не найден.'}, status=404)

    df = pd.read_csv(path)

    def _rows():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(df.columns.tolist())
        yield buf.getvalue()
        for _, row in df.iterrows():
            buf.seek(0)
            buf.truncate(0)
            writer.writerow(row.tolist())
            yield buf.getvalue()

    response = StreamingHttpResponse(_rows(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="data_{timestamp}.csv"'
    return response
