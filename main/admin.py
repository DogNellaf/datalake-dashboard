from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from main.models import Data


@admin.register(Data)
class DataAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'path', 'sep', 'data_actions')
    readonly_fields = ('timestamp',)
    list_per_page = 25

    def data_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">График</a>&nbsp;'
            '<a class="button" href="{}">Предпросмотр</a>&nbsp;'
            '<a class="button" href="{}">Экспорт CSV</a>',
            reverse('graph', args=[obj.timestamp]),
            reverse('preview', args=[obj.timestamp]),
            reverse('export_csv', args=[obj.timestamp]),
        )

    data_actions.short_description = 'Действия'

    def has_change_permission(self, request, obj=None):
        return False
