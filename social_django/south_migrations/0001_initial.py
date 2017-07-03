# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'UserSocialAuth'
        db.create_table('social_auth_usersocialauth', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('user', self.gf('django.db.models.fields.related.ForeignKey')(related_name='social_auth', to=orm['auth.User'])),
            ('provider', self.gf('django.db.models.fields.CharField')(max_length=32)),
            ('uid', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('extra_data', self.gf('social_django.fields.JSONField')(default={})),
        ))
        db.send_create_signal('social_django', ['UserSocialAuth'])

        # Adding unique constraint on 'UserSocialAuth', fields ['provider', 'uid']
        db.create_unique('social_auth_usersocialauth', ['provider', 'uid'])

        # Adding model 'Nonce'
        db.create_table('social_auth_nonce', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('server_url', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('timestamp', self.gf('django.db.models.fields.IntegerField')()),
            ('salt', self.gf('django.db.models.fields.CharField')(max_length=65)),
        ))
        db.send_create_signal('social_django', ['Nonce'])

        # Adding unique constraint on 'Nonce', fields ['server_url', 'timestamp', 'salt']
        db.create_unique('social_auth_nonce', ['server_url', 'timestamp', 'salt'])

        # Adding model 'Association'
        db.create_table('social_auth_association', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('server_url', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('handle', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('secret', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('issued', self.gf('django.db.models.fields.IntegerField')()),
            ('lifetime', self.gf('django.db.models.fields.IntegerField')()),
            ('assoc_type', self.gf('django.db.models.fields.CharField')(max_length=64)),
        ))
        db.send_create_signal('social_django', ['Association'])

        # Adding unique constraint on 'Association', fields ['server_url', 'handle']
        db.create_unique('social_auth_association', ['server_url', 'handle'])

        # Adding model 'Code'
        db.create_table('social_auth_code', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email', self.gf('django.db.models.fields.EmailField')(max_length=254)),
            ('code', self.gf('django.db.models.fields.CharField')(max_length=32, db_index=True)),
            ('verified', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal('social_django', ['Code'])

        # Adding unique constraint on 'Code', fields ['email', 'code']
        db.create_unique('social_auth_code', ['email', 'code'])

        # Adding model 'Partial'
        db.create_table('social_auth_partial', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('token', self.gf('django.db.models.fields.CharField')(max_length=32, db_index=True)),
            ('next_step', self.gf('django.db.models.fields.PositiveSmallIntegerField')(default=0)),
            ('backend', self.gf('django.db.models.fields.CharField')(max_length=32)),
            ('data', self.gf('social_django.fields.JSONField')(default={})),
        ))
        db.send_create_signal('social_django', ['Partial'])


    def backwards(self, orm):
        # Removing unique constraint on 'Code', fields ['email', 'code']
        db.delete_unique('social_auth_code', ['email', 'code'])

        # Removing unique constraint on 'Association', fields ['server_url', 'handle']
        db.delete_unique('social_auth_association', ['server_url', 'handle'])

        # Removing unique constraint on 'Nonce', fields ['server_url', 'timestamp', 'salt']
        db.delete_unique('social_auth_nonce', ['server_url', 'timestamp', 'salt'])

        # Removing unique constraint on 'UserSocialAuth', fields ['provider', 'uid']
        db.delete_unique('social_auth_usersocialauth', ['provider', 'uid'])

        # Deleting model 'UserSocialAuth'
        db.delete_table('social_auth_usersocialauth')

        # Deleting model 'Nonce'
        db.delete_table('social_auth_nonce')

        # Deleting model 'Association'
        db.delete_table('social_auth_association')

        # Deleting model 'Code'
        db.delete_table('social_auth_code')

        # Deleting model 'Partial'
        db.delete_table('social_auth_partial')


    models = {
        'auth.group': {
            'Meta': {'object_name': 'Group'},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '80'}),
            'permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'})
        },
        'auth.permission': {
            'Meta': {'ordering': "('content_type__app_label', 'content_type__model', 'codename')", 'unique_together': "(('content_type', 'codename'),)", 'object_name': 'Permission'},
            'codename': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['contenttypes.ContentType']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '50'})
        },
        'auth.user': {
            'Meta': {'object_name': 'User'},
            'date_joined': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'blank': 'True'}),
            'first_name': ('django.db.models.fields.CharField', [], {'max_length': '30', 'blank': 'True'}),
            'groups': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Group']", 'symmetrical': 'False', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'is_staff': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'is_superuser': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'last_login': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'last_name': ('django.db.models.fields.CharField', [], {'max_length': '30', 'blank': 'True'}),
            'password': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'user_permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'}),
            'username': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '30'})
        },
        'contenttypes.contenttype': {
            'Meta': {'ordering': "('name',)", 'unique_together': "(('app_label', 'model'),)", 'object_name': 'ContentType', 'db_table': "'django_content_type'"},
            'app_label': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'})
        },
        'social_django.association': {
            'Meta': {'unique_together': "(('server_url', 'handle'),)", 'object_name': 'Association', 'db_table': "'social_auth_association'"},
            'assoc_type': ('django.db.models.fields.CharField', [], {'max_length': '64'}),
            'handle': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'issued': ('django.db.models.fields.IntegerField', [], {}),
            'lifetime': ('django.db.models.fields.IntegerField', [], {}),
            'secret': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'server_url': ('django.db.models.fields.CharField', [], {'max_length': '255'})
        },
        'social_django.code': {
            'Meta': {'unique_together': "(('email', 'code'),)", 'object_name': 'Code', 'db_table': "'social_auth_code'"},
            'code': ('django.db.models.fields.CharField', [], {'max_length': '32', 'db_index': 'True'}),
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '254'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'verified': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        'social_django.nonce': {
            'Meta': {'unique_together': "(('server_url', 'timestamp', 'salt'),)", 'object_name': 'Nonce', 'db_table': "'social_auth_nonce'"},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'salt': ('django.db.models.fields.CharField', [], {'max_length': '65'}),
            'server_url': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'timestamp': ('django.db.models.fields.IntegerField', [], {})
        },
        'social_django.partial': {
            'Meta': {'object_name': 'Partial', 'db_table': "'social_auth_partial'"},
            'backend': ('django.db.models.fields.CharField', [], {'max_length': '32'}),
            'data': ('social_django.fields.JSONField', [], {'default': '{}'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'next_step': ('django.db.models.fields.PositiveSmallIntegerField', [], {'default': '0'}),
            'token': ('django.db.models.fields.CharField', [], {'max_length': '32', 'db_index': 'True'})
        },
        'social_django.usersocialauth': {
            'Meta': {'unique_together': "(('provider', 'uid'),)", 'object_name': 'UserSocialAuth', 'db_table': "'social_auth_usersocialauth'"},
            'extra_data': ('social_django.fields.JSONField', [], {'default': '{}'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'provider': ('django.db.models.fields.CharField', [], {'max_length': '32'}),
            'uid': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'user': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'social_auth'", 'to': "orm['auth.User']"})
        }
    }

    complete_apps = ['social_django']