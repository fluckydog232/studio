# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2016-08-24 17:18
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contentcuration', '0007_merge'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='published',
            field=models.BooleanField(default=False),
        ),
    ]
