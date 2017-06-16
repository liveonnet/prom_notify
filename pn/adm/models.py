# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from __future__ import unicode_literals

from django.db import models


class Item(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    source = models.CharField('来源', max_length=32)
    sid = models.CharField('来源id', max_length=64)
    show_title = models.CharField('标题', max_length=1024)
    item_url = models.CharField('介绍', max_length=1024, blank=True)
    real_url = models.CharField('商品', max_length=1024, blank=True)
    pic_url = models.CharField(max_length=1024, blank=True)
    get_time = models.CharField(max_length=64, blank=True)
    ctime = models.DateTimeField('入库时间', auto_now_add=True, blank=True)

    def __str__(self):
        return self.show_title

    class Meta:
        managed = False
        db_table = 'item'
        verbose_name = '优惠信息'
        verbose_name_plural = '优惠信息'
