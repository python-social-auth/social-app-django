# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-01-02 11:54
from __future__ import unicode_literals

from django.db import migrations, models
import social_django.fields
import social_django.storage


class Migration(migrations.Migration):
    
    replaces = [
        ('default', '0006_partial'),
        ('social_auth', '0006_partial'),
    ]

    dependencies = [
        ('social_django', '0005_auto_20160727_2333'),
    ]

    operations = [
        migrations.CreateModel(
            name='Partial',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=32)),
                ('next_step', models.PositiveSmallIntegerField(default=0)),
                ('backend', models.CharField(max_length=32)),
                ('data', social_django.fields.JSONField(default=dict)),
            ],
            options={
                'db_table': 'social_auth_partial',
            },
            bases=(models.Model, social_django.storage.DjangoPartialMixin),
        ),
    ]
