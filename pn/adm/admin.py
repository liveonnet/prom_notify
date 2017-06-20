from django.utils import timezone
from django.utils.timezone import timedelta
from django.utils.datetime_safe import datetime
from django.contrib import admin
from django.http import HttpResponse
from django.core import serializers

from .models import Item

#-#from django.db import models
from django.utils.html import format_html


class CTimeListFilter(admin.SimpleListFilter):
    title = '入库时间'
    parameter_name = 'ctime'

    def lookups(self, request, model_admin):
        return (('5m', '过去5分钟'),
                ('10m', '过去10分钟'),
                ('30m', '过去30分钟'),
                ('1h', '过去1小时'),
                ('4h', '过去4小时'),
                ('6h', '过去6小时'),
                ('12h', '过去12小时'),
                ('today', '今天'),
                ('24h', '过去24小时'),
                )

    def queryset(self, request, queryset):
        param = None
        now = timezone.now()
        print('now ', now)
        if self.value() == '5m':
            param = timedelta(minutes=-5)
        elif self.value() == '10m':
            param = timedelta(minutes=-10)
        elif self.value() == '30m':
            param = timedelta(minutes=-30)
        elif self.value() == '1h':
            param = timedelta(hours=-1)
        elif self.value() == '4h':
            param = timedelta(hours=-4)
        elif self.value() == '6h':
            param = timedelta(hours=-6)
        elif self.value() == '12h':
            param = timedelta(hours=-12)
        elif self.value() == 'today':
            param = datetime(year=now.year, month=now.month, day=now.day) - now
        elif self.value() == '24h':
            param = timedelta(hours=-24)

        print('param ', param)
        if param:
            return queryset.filter(ctime__gte=now + param)
        else:
            return queryset


# Register your models here.
class ItemAdmin(admin.ModelAdmin):
    list_filter = ('source', CTimeListFilter)
    list_display = ('id', 'show_title', 'item_url_click', 'real_url_click', 'ctime_show')
    list_display_links = ('show_title', )
    list_select_related = True
    list_per_page = 20

    search_fields = ('show_title', )
    readonly_fields = ('id', 'sid', 'source', 'ctime', 'show_title', 'item_url', 'real_url', 'pic_url')
    fieldsets = [(None, {'fields': ('id', 'source', 'sid')}),
                 (None, {'fields': ('show_title', )}),
                 ('url', {'fields': ('item_url', 'real_url', 'pic_url')}),
                 ('time', {'fields': ('ctime', )}),
                 ]

    actions = ('send_to', )

    ordering = ('-id', )

#-#    date_hierarchy = 'ctime'

    def get_readonly_display(self, request, obj=None):
        if obj:
            return ('ctime', )
        else:
            return ()

#-#    class Media:
#-#        # prefix: django/contrib/admin/static/admin/ + {STATIC_URL}
#-#        css = {'all': ('admin/css/my_styles.css', ),  # /home/kevin/data_bk/work/p3_project/lib/python3.5/site-packages/django/contrib/admin/static/
#-#               }

    def item_url_click(self, obj):
        return format_html('<a href="{url}">{url}</a>', url=obj.item_url)
    item_url_click.short_description = '介绍'

    def real_url_click(self, obj):
        return format_html('<a href="%s">%s</a>' % (obj.real_url, obj.real_url))
    real_url_click.short_description = '商品'

    def ctime_show(self, obj):
        s = None
        try:
            s = obj.ctime.strftime('%Y-%m-%d %H:%M:%S')
        except:
            s = obj.ctime
        return s
    ctime_show.short_description = '入库时间'

    def send_to(self, request, queryset):
        self.message_user(request, '{0} 条记录被选定'.format(queryset.count()))
    send_to.short_description = '发送选定记录'


def export_as_json(modeladmin, request, queryset):
    resp = HttpResponse(content_type='application/json')
    serializers.serialize('json', queryset, stream=resp)
    return resp


admin.site.register(Item, ItemAdmin)
admin.site.add_action(export_as_json, '导出json数据')
admin.site.disable_action('delete_selected')
