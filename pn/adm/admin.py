from django.utils import timezone
from django.utils.timezone import timedelta
from django.utils.datetime_safe import datetime
from django.contrib import admin
from django.http import HttpResponse
from django.core import serializers
from django import forms
from django.shortcuts import render
import logging

from .models import Item

#-#from django.db import models
from django.utils.html import format_html

logger = logging.getLogger('my.admin')
info, debug, error = logger.info, logger.debug, logger.error


class CTimeListFilter(admin.SimpleListFilter):
    """自定义时间过滤
    """
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
                ('48h', '过去48小时'),
                ('72h', '过去72小时'),
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
        elif self.value() == '48h':
            param = timedelta(hours=-48)
        elif self.value() == '72h':
            param = timedelta(hours=-72)

        print('param ', param)
        if param:
            return queryset.filter(ctime__gte=now + param)
        else:
            return queryset


class CustomSendToForm(forms.Form):
    item_id = forms.CharField(widget=forms.Textarea)
    remark = forms.CharField(max_length=100)


# Register your models here.
class ItemAdmin(admin.ModelAdmin):
    list_filter = ('source', CTimeListFilter)
    list_display = ('id', 'pic_url_show', 'show_title', 'item_url_click', 'real_url_click', 'ctime_show')
    list_display_links = ('show_title', )
    list_select_related = True
    list_per_page = 20  # 每页显示item数

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

    def pic_url_show(self, obj):
        return format_html('<a target="_blank" href="{real_url}"><img src="{pic_url}" width="80" height="80"></img></a>', pic_url=obj.pic_url, real_url=obj.real_url)
    pic_url_show.short_description = '配图'

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
        if 'do_action' in request.POST:
            form = CustomSendToForm(request.POST)
            if form.is_valid():
                ids = form.cleaned_data['item_id']
                l_id = ids.split()
                input_count = len(l_id)
                total_count = Item.objects.filter(id__in=l_id).count()
                remark = form.cleaned_data['remark']
                self.message_user(request, '输入 {0} 条记录，其中 {1} 条记录有效且被选定. 备注: {2}'.format(input_count, total_count, remark))
                return
        else:
            form = CustomSendToForm()

        return render(request, 'adm/action_send_to.html', {'title': '发送选定的记录', 'objects': queryset, 'form': form})
    send_to.short_description = '发送选定记录'
    send_to.allow_select_none = True  # 允许不选择任何内容

    def changelist_view(self, request, extra_context=None):
        if request.POST and 'action' in request.POST:
            try:
                action = self.get_actions(request)[request.POST['action']][0]
                allow_select_none = getattr(action, 'allow_select_none', False)
            except:
                error('got except', exc_info=True)
            else:
                if allow_select_none:
                    info('orig %s', request.POST)
                    if not request.POST.getlist(admin.ACTION_CHECKBOX_NAME):
                        info('no select ??? %s', action)
                        post = request.POST.copy()
                        post.update({admin.ACTION_CHECKBOX_NAME: '0'})
                        request._set_post(post)
                        info('now %s', request.POST)
        return super().changelist_view(request, extra_context)


def export_as_json(modeladmin, request, queryset):
    resp = HttpResponse(content_type='application/json')
    serializers.serialize('json', queryset, stream=resp)
    return resp


admin.site.register(Item, ItemAdmin)
admin.site.add_action(export_as_json, '导出json数据')  # 添加全局action
admin.site.disable_action('delete_selected')  # 去掉全局默认的删除action
