from django.contrib import admin
from django.urls import path

from main.views import (
    export_csv,
    get_column_stats,
    get_plot_data,
    graph_building_view,
    data_preview,
    index,
    login_view,
    register,
)

urlpatterns = [
    path('', index, name='index'),
    path('admin/', admin.site.urls),
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('graph/<str:timestamp>/', graph_building_view, name='graph'),
    path('preview/<str:timestamp>/', data_preview, name='preview'),
    path('export/<str:timestamp>/', export_csv, name='export_csv'),
    path('api/plot-data/', get_plot_data, name='get_plot_data'),
    path('api/column-stats/', get_column_stats, name='get_column_stats'),
]
