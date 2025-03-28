#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import json
import logging

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from beeswax.data_export import DOWNLOAD_COOKIE_AGE
from beeswax.management.commands import beeswax_install_examples
from desktop.auth.decorators import admin_required
from desktop.conf import ENABLE_DOWNLOAD, ENABLE_HUE_5, USE_NEW_EDITOR
from desktop.lib import export_csvxls
from desktop.lib.connectors.models import Connector
from desktop.lib.django_util import JsonResponse, render
from desktop.lib.exceptions_renderable import PopupException
from desktop.models import Document, Document2, FilesystemException, _get_gist_document
from desktop.views import serve_403_error
from metadata.conf import has_catalog, has_optimizer, has_workload_analytics
from notebook.conf import EXAMPLES, SHOW_NOTEBOOKS, get_ordered_interpreters
from notebook.connectors.base import Notebook, _get_snippet_name, get_interpreter
from notebook.connectors.spark_shell import SparkApi
from notebook.decorators import check_document_access_permission, check_document_modify_permission, check_editor_access_permission
from notebook.management.commands.notebook_setup import Command
from notebook.models import _get_dialect_example, _get_editor_type, get_api, make_notebook

LOG = logging.getLogger()


@check_document_access_permission
def notebook(request, is_embeddable=False):
  if not SHOW_NOTEBOOKS.get() or not request.user.has_hue_permission(action="access", app='notebook'):
    return serve_403_error(request)

  notebook_id = request.GET.get('notebook', request.GET.get('editor'))

  is_yarn_mode = False
  try:
    from spark.conf import LIVY_SERVER_SESSION_KIND
    is_yarn_mode = LIVY_SERVER_SESSION_KIND.get()
  except Exception:
    LOG.exception('Spark is not enabled')

  return render('notebook.mako', request, {
      'is_embeddable': request.GET.get('is_embeddable', False),
      'options_json': json.dumps({
          'languages': get_ordered_interpreters(request.user),
          'session_properties': SparkApi.to_properties(),
          'is_optimizer_enabled': has_optimizer(),
          'is_wa_enabled': has_workload_analytics(),
          'is_navigator_enabled': has_catalog(request.user),
          'editor_type': 'notebook'
      }),
      'is_yarn_mode': is_yarn_mode,
  })


@check_document_access_permission
def notebook_embeddable(request):
  return notebook(request, True)


@check_editor_access_permission()
@check_document_access_permission
def editor(request, is_mobile=False, is_embeddable=False):
  editor_id = request.GET.get('editor')
  editor_type = request.GET.get('type', 'hive')
  gist_id = request.GET.get('gist')

  if editor_type == 'notebook' or request.GET.get('notebook'):
    return notebook(request)

  if editor_type == 'gist':
    gist_doc = _get_gist_document(uuid=gist_id)
    editor_type = gist_doc.extra

  if EXAMPLES.AUTO_OPEN.get() and not editor_id:
    sample_query = _get_dialect_example(dialect=editor_type)
    if sample_query:
      editor_id = sample_query.id

  if editor_id and not gist_id:  # Open existing saved editor document
    editor_type = _get_editor_type(editor_id)

  template = 'editor.mako'
  if ENABLE_HUE_5.get():
    template = 'editor2.mako'
  elif is_mobile:
    template = 'editor_m.mako'

  return render(template, request, {
      'is_embeddable': request.GET.get('is_embeddable', False),
      'editor_type': editor_type,
      'options_json': json.dumps({
        'languages': get_ordered_interpreters(request.user),
        'mode': 'editor',
        'is_optimizer_enabled': has_optimizer(),
        'is_wa_enabled': has_workload_analytics(),
        'is_navigator_enabled': has_catalog(request.user),
        'editor_type': editor_type,
        'mobile': is_mobile
      })
  })


@check_document_access_permission
def editor_embeddable(request):
  return editor(request, False, True)


@check_document_access_permission
def editor_m(request):
  return editor(request, True)


def new(request):
  return notebook(request)


def browse(request, database, table, partition_spec=None):
  snippet = {'type': request.POST.get('sourceType', 'hive')}

  statement = get_api(request, snippet).get_browse_query(snippet, database, table, partition_spec)
  editor_type = snippet['type']
  namespace = request.POST.get('namespace', 'default')
  compute = json.loads(request.POST.get('cluster', '{}'))

  if request.method == 'POST':
    notebook = make_notebook(
        name='Execute and watch',
        editor_type=editor_type,
        statement=statement,
        database=database,
        status='ready-execute',
        is_task=True,
        namespace=namespace,
        compute=compute
    )
    return JsonResponse(notebook.execute(request, batch=False))
  else:
    editor = make_notebook(
        name='Browse',
        editor_type=editor_type,
        statement=statement,
        status='ready-execute',
        namespace=namespace,
        compute=compute
    )
    return render('editor2.mako' if ENABLE_HUE_5.get() else 'editor.mako', request, {
        'options_json': json.dumps({
            'languages': get_ordered_interpreters(request.user),
            'mode': 'editor',
            'editor_type': editor_type
        }),
        'editor_type': editor_type,
    })


# Deprecated in Hue 4
@check_document_access_permission
def execute_and_watch(request):
  notebook_id = request.GET.get('editor', request.GET.get('notebook'))
  snippet_id = int(request.GET['snippet'])
  action = request.GET['action']
  destination = request.GET['destination']

  notebook = Notebook(document=Document2.objects.get(id=notebook_id)).get_data()
  snippet = notebook['snippets'][snippet_id]
  editor_type = snippet['type']

  api = get_api(request, snippet)

  if action == 'save_as_table':
    sql, success_url = api.export_data_as_table(notebook, snippet, destination)
    editor = make_notebook(
        name='Execute and watch',
        editor_type=editor_type,
        statement=sql,
        status='ready-execute',
        database=snippet['database']
    )
  elif action == 'insert_as_query':
    # TODO: checks/workarounds in case of non impersonation or Sentry
    # TODO: keep older simpler way in case of known not many rows?
    sql, success_url = api.export_large_data_to_hdfs(notebook, snippet, destination)
    editor = make_notebook(
        name='Execute and watch',
        editor_type=editor_type,
        statement=sql,
        status='ready-execute',
        database=snippet['database'],
        on_success_url=success_url
    )
  elif action == 'index_query':
    if destination == '__hue__':
      destination = _get_snippet_name(notebook, unique=True, table_format=True)
      live_indexing = True
    else:
      live_indexing = False

    sql, success_url = api.export_data_as_table(notebook, snippet, destination, is_temporary=True, location='')
    editor = make_notebook(name='Execute and watch', editor_type=editor_type, statement=sql, status='ready-execute')

    sample = get_api(request, snippet).fetch_result(notebook, snippet, 0, start_over=True)

    from indexer.api3 import _index  # Will ve moved to the lib
    from indexer.fields import Field
    from indexer.file_format import HiveFormat

    file_format = {
        'name': 'col',
        'inputFormat': 'query',
        'format': {'quoteChar': '"', 'recordSeparator': '\n', 'type': 'csv', 'hasHeader': False, 'fieldSeparator': '\u0001'},
        "sample": '',
        "columns": [
            Field(col['name'].rsplit('.')[-1], HiveFormat.FIELD_TYPE_TRANSLATE.get(col['type'], 'string')).to_dict()
            for col in sample['meta']
        ]
    }

    if live_indexing:
      file_format['inputFormat'] = 'hs2_handle'
      file_format['fetch_handle'] = lambda rows, start_over: get_api(
          request, snippet).fetch_result(notebook, snippet, rows=rows, start_over=start_over)

    job_handle = _index(request, file_format, destination, query=notebook['uuid'])

    if live_indexing:
      return redirect(reverse('search:browse', kwargs={'name': destination}))
    else:
      return redirect(reverse('oozie:list_oozie_workflow', kwargs={'job_id': job_handle['handle']['id']}))
  else:
    raise PopupException(_('Action %s is unknown') % action)

  return render('editor2.mako' if ENABLE_HUE_5.get() else 'editor.mako', request, {
      'options_json': json.dumps({
          'languages': [{"name": "%s SQL" % editor_type.title(), "type": editor_type}],
          'mode': 'editor',
          'editor_type': editor_type,
          'success_url': success_url
      }),
      'editor_type': editor_type,
  })


@check_document_modify_permission()
def delete(request):
  response = {'status': -1}

  notebooks = json.loads(request.POST.get('notebooks', '[]'))

  if not notebooks:
    response['message'] = _('No notebooks have been selected for deletion.')
  else:
    ctr = 0
    failures = []
    for notebook in notebooks:
      try:
        doc2 = Document2.objects.get_by_uuid(user=request.user, uuid=notebook['uuid'], perm_type='write')
        doc = doc2._get_doc1()
        doc.can_write_or_exception(request.user)
        doc2.trash()
        ctr += 1
      except FilesystemException as e:
        failures.append(notebook['uuid'])
        LOG.exception("Failed to delete document with UUID %s that is writable by user %s, skipping." % (
            notebook['uuid'], request.user.username))

    response['status'] = 0
    if failures:
      response['errors'] = failures
      response['message'] = _('Trashed %d notebook(s) and failed to delete %d notebook(s).') % (ctr, len(failures))
    else:
      response['message'] = _('Trashed %d notebook(s)') % ctr

  return JsonResponse(response)


@check_document_access_permission
def copy(request):
  response = {'status': -1}

  notebooks = json.loads(request.POST.get('notebooks', '[]'))

  if not notebooks:
    response['message'] = _('No notebooks have been selected for copying.')
  else:
    ctr = 0
    failures = []
    for notebook in notebooks:
      try:
        doc2 = Document2.objects.get_by_uuid(user=request.user, uuid=notebook['uuid'])
        doc = doc2._get_doc1()
        name = doc2.name + '-copy'
        doc2 = doc2.copy(name=name, owner=request.user)

        doc.copy(content_object=doc2, name=name, owner=request.user)
      except FilesystemException as e:
        failures.append(notebook['uuid'])
        LOG.exception("Failed to copy document with UUID %s accessible by user %s, skipping." % (notebook['uuid'], request.user.username))

    response['status'] = 0
    if failures:
      response['errors'] = failures
      response['message'] = _('Copied %d notebook(s) and failed to copy %d notebook(s).') % (ctr, len(failures))
    else:
      response['message'] = _('Copied %d notebook(s)') % ctr

  return JsonResponse(response)


@check_document_access_permission
def download(request):
  if not ENABLE_DOWNLOAD.get():
    return serve_403_error(request)

  notebook = json.loads(request.POST.get('notebook', '{}'))
  snippet = json.loads(request.POST.get('snippet', '{}'))
  file_format = request.POST.get('format', 'csv')
  user_agent = request.META.get('HTTP_USER_AGENT')
  file_name = _get_snippet_name(notebook)

  content_generator = get_api(request, snippet).download(notebook, snippet, file_format=file_format)
  response = export_csvxls.make_response(content_generator, file_format, file_name, user_agent=user_agent)

  if snippet['id']:
    response.set_cookie(
      'download-%s' % snippet['id'],
      json.dumps({
        'truncated': 'false',
        'row_counter': '0'
      }),
      max_age=DOWNLOAD_COOKIE_AGE
    )
  if response:
    request.audit = {
      'operation': 'DOWNLOAD',
      'operationText': 'User %s downloaded results from %s as %s' % (request.user.username, _get_snippet_name(notebook), file_format),
      'allowed': True
    }

  return response


@require_POST
@admin_required
def install_examples(request):
  response = {'status': -1, 'message': '', 'errorMessage': ''}

  try:
    connector = Connector.objects.get(id=request.POST.get('connector'))
    if connector:
      dialect = connector.dialect
      db_name = request.POST.get('db_name', 'default')
      interpreter = get_interpreter(connector_type=connector.to_dict()['type'], user=request.user)

      successes, errors = beeswax_install_examples.Command().handle(
          dialect=dialect, db_name=db_name, user=request.user, interpreter=interpreter, request=request
      )
      response['message'] = ' '.join(successes)
      response['errorMessage'] = ' '.join(errors)
      response['status'] = len(errors)
    else:
      Command().handle(user=request.user, dialect=request.POST.get('dialect', 'hive'))
      response['status'] = 0
      response['message'] = _('Examples refreshed')
  except Exception as e:
    msg = 'Error during Editor samples installation'
    LOG.exception(msg)
    response['errorMessage'] = msg + ': ' + str(e)

  return JsonResponse(response)
