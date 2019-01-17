# Copyright (C) The Arvados Authors. All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from future import standard_library
standard_library.install_aliases()
from builtins import object
from builtins import str

import copy
import io
import functools
import hashlib
import json
import logging
import mock
import sys
import unittest

from io import BytesIO, StringIO

import arvados
import arvados.collection
import arvados_cwl
import arvados_cwl.executor
import arvados_cwl.runner
import arvados.keep

from .matcher import JsonDiffMatcher, StripYAMLComments
from .mock_discovery import get_rootDesc

import ruamel.yaml as yaml

_rootDesc = None

def stubs(func):
    @functools.wraps(func)
    @mock.patch("arvados.commands.keepdocker.list_images_in_arv")
    @mock.patch("arvados.collection.KeepClient")
    @mock.patch("arvados.keep.KeepClient")
    @mock.patch("arvados.events.subscribe")
    def wrapped(self, events, keep_client1, keep_client2, keepdocker, *args, **kwargs):
        class Stubs(object):
            pass
        stubs = Stubs()
        stubs.events = events
        stubs.keepdocker = keepdocker

        def putstub(p, **kwargs):
            return "%s+%i" % (hashlib.md5(p).hexdigest(), len(p))
        keep_client1().put.side_effect = putstub
        keep_client1.put.side_effect = putstub
        keep_client2().put.side_effect = putstub
        keep_client2.put.side_effect = putstub

        stubs.keep_client = keep_client2
        stubs.docker_images = {
            "arvados/jobs:"+arvados_cwl.__version__: [("zzzzz-4zz18-zzzzzzzzzzzzzd3", "")],
            "debian:8": [("zzzzz-4zz18-zzzzzzzzzzzzzd4", "")],
            "arvados/jobs:123": [("zzzzz-4zz18-zzzzzzzzzzzzzd5", "")],
            "arvados/jobs:latest": [("zzzzz-4zz18-zzzzzzzzzzzzzd6", "")],
        }
        def kd(a, b, image_name=None, image_tag=None):
            return stubs.docker_images.get("%s:%s" % (image_name, image_tag), [])
        stubs.keepdocker.side_effect = kd

        stubs.fake_user_uuid = "zzzzz-tpzed-zzzzzzzzzzzzzzz"
        stubs.fake_container_uuid = "zzzzz-dz642-zzzzzzzzzzzzzzz"

        if sys.version_info[0] < 3:
            stubs.capture_stdout = BytesIO()
        else:
            stubs.capture_stdout = StringIO()

        stubs.api = mock.MagicMock()
        stubs.api._rootDesc = get_rootDesc()

        stubs.api.users().current().execute.return_value = {
            "uuid": stubs.fake_user_uuid,
        }
        stubs.api.collections().list().execute.return_value = {"items": []}
        stubs.api.containers().current().execute.return_value = {
            "uuid": stubs.fake_container_uuid,
        }

        class CollectionExecute(object):
            def __init__(self, exe):
                self.exe = exe
            def execute(self, num_retries=None):
                return self.exe

        def collection_createstub(created_collections, body, ensure_unique_name=None):
            mt = body["manifest_text"].encode('utf-8')
            uuid = "zzzzz-4zz18-zzzzzzzzzzzzzx%d" % len(created_collections)
            pdh = "%s+%i" % (hashlib.md5(mt).hexdigest(), len(mt))
            created_collections[uuid] = {
                "uuid": uuid,
                "portable_data_hash": pdh,
                "manifest_text": mt.decode('utf-8')
            }
            return CollectionExecute(created_collections[uuid])

        def collection_getstub(created_collections, uuid):
            for v in created_collections.values():
                if uuid in (v["uuid"], v["portable_data_hash"]):
                    return CollectionExecute(v)

        created_collections = {
            "99999999999999999999999999999998+99": {
                "uuid": "",
                "portable_data_hash": "99999999999999999999999999999998+99",
                "manifest_text": ". 99999999999999999999999999999998+99 0:0:file1.txt"
            },
            "99999999999999999999999999999994+99": {
                "uuid": "",
                "portable_data_hash": "99999999999999999999999999999994+99",
                "manifest_text": ". 99999999999999999999999999999994+99 0:0:expect_arvworkflow.cwl"
            },
            "zzzzz-4zz18-zzzzzzzzzzzzzd3": {
                "uuid": "zzzzz-4zz18-zzzzzzzzzzzzzd3",
                "portable_data_hash": "999999999999999999999999999999d3+99",
                "manifest_text": ""
            },
            "zzzzz-4zz18-zzzzzzzzzzzzzd4": {
                "uuid": "zzzzz-4zz18-zzzzzzzzzzzzzd4",
                "portable_data_hash": "999999999999999999999999999999d4+99",
                "manifest_text": ""
            },
            "zzzzz-4zz18-zzzzzzzzzzzzzd5": {
                "uuid": "zzzzz-4zz18-zzzzzzzzzzzzzd5",
                "portable_data_hash": "999999999999999999999999999999d5+99",
                "manifest_text": ""
            },
            "zzzzz-4zz18-zzzzzzzzzzzzzd6": {
                "uuid": "zzzzz-4zz18-zzzzzzzzzzzzzd6",
                "portable_data_hash": "999999999999999999999999999999d6+99",
                "manifest_text": ""
            }
        }
        stubs.api.collections().create.side_effect = functools.partial(collection_createstub, created_collections)
        stubs.api.collections().get.side_effect = functools.partial(collection_getstub, created_collections)

        stubs.expect_job_uuid = "zzzzz-8i9sb-zzzzzzzzzzzzzzz"
        stubs.api.jobs().create().execute.return_value = {
            "uuid": stubs.expect_job_uuid,
            "state": "Queued",
        }

        stubs.expect_container_request_uuid = "zzzzz-xvhdp-zzzzzzzzzzzzzzz"
        stubs.api.container_requests().create().execute.return_value = {
            "uuid": stubs.expect_container_request_uuid,
            "container_uuid": "zzzzz-dz642-zzzzzzzzzzzzzzz",
            "state": "Queued"
        }

        stubs.expect_pipeline_template_uuid = "zzzzz-d1hrv-zzzzzzzzzzzzzzz"
        stubs.api.pipeline_templates().create().execute.return_value = {
            "uuid": stubs.expect_pipeline_template_uuid,
        }
        stubs.expect_job_spec = {
            'runtime_constraints': {
                'docker_image': '999999999999999999999999999999d3+99',
                'min_ram_mb_per_node': 1024
            },
            'script_parameters': {
                'x': {
                    'basename': 'blorp.txt',
                    'location': 'keep:169f39d466a5438ac4a90e779bf750c7+53/blorp.txt',
                    'class': 'File'
                },
                'y': {
                    'basename': '99999999999999999999999999999998+99',
                    'location': 'keep:99999999999999999999999999999998+99',
                    'class': 'Directory'
                },
                'z': {
                    'basename': 'anonymous',
                    "listing": [{
                        "basename": "renamed.txt",
                        "class": "File",
                        "location": "keep:99999999999999999999999999999998+99/file1.txt",
                        "size": 0
                    }],
                    'class': 'Directory'
                },
                'cwl:tool': '57ad063d64c60dbddc027791f0649211+60/workflow.cwl#main'
            },
            'repository': 'arvados',
            'script_version': 'master',
            'minimum_script_version': '570509ab4d2ef93d870fd2b1f2eab178afb1bad9',
            'script': 'cwl-runner'
        }
        stubs.pipeline_component = stubs.expect_job_spec.copy()
        stubs.expect_pipeline_instance = {
            'name': 'submit_wf.cwl',
            'state': 'RunningOnServer',
            'owner_uuid': None,
            "components": {
                "cwl-runner": {
                    'runtime_constraints': {'docker_image': '999999999999999999999999999999d3+99', 'min_ram_mb_per_node': 1024},
                    'script_parameters': {
                        'y': {"value": {'basename': '99999999999999999999999999999998+99', 'location': 'keep:99999999999999999999999999999998+99', 'class': 'Directory'}},
                        'x': {"value": {
                            'basename': 'blorp.txt',
                            'class': 'File',
                            'location': 'keep:169f39d466a5438ac4a90e779bf750c7+53/blorp.txt',
                            "size": 16
                        }},
                        'z': {"value": {'basename': 'anonymous', 'class': 'Directory',
                              'listing': [
                                  {
                                      'basename': 'renamed.txt',
                                      'class': 'File', 'location':
                                      'keep:99999999999999999999999999999998+99/file1.txt',
                                      'size': 0
                                  }
                              ]}},
                        'cwl:tool': '57ad063d64c60dbddc027791f0649211+60/workflow.cwl#main',
                        'arv:debug': True,
                        'arv:enable_reuse': True,
                        'arv:on_error': 'continue'
                    },
                    'repository': 'arvados',
                    'script_version': 'master',
                    'minimum_script_version': '570509ab4d2ef93d870fd2b1f2eab178afb1bad9',
                    'script': 'cwl-runner',
                    'job': {'state': 'Queued', 'uuid': 'zzzzz-8i9sb-zzzzzzzzzzzzzzz'}
                }
            }
        }
        stubs.pipeline_create = copy.deepcopy(stubs.expect_pipeline_instance)
        stubs.expect_pipeline_uuid = "zzzzz-d1hrv-zzzzzzzzzzzzzzz"
        stubs.pipeline_create["uuid"] = stubs.expect_pipeline_uuid
        stubs.pipeline_with_job = copy.deepcopy(stubs.pipeline_create)
        stubs.pipeline_with_job["components"]["cwl-runner"]["job"] = {
            "uuid": "zzzzz-8i9sb-zzzzzzzzzzzzzzz",
            "state": "Queued"
        }
        stubs.api.pipeline_instances().create().execute.return_value = stubs.pipeline_create
        stubs.api.pipeline_instances().get().execute.return_value = stubs.pipeline_with_job

        with open("tests/wf/submit_wf_packed.cwl") as f:
            expect_packed_workflow = yaml.round_trip_load(f)

        stubs.expect_container_spec = {
            'priority': 500,
            'mounts': {
                '/var/spool/cwl': {
                    'writable': True,
                    'kind': 'collection'
                },
                '/var/lib/cwl/workflow.json': {
                    'content': expect_packed_workflow,
                    'kind': 'json'
                },
                'stdout': {
                    'path': '/var/spool/cwl/cwl.output.json',
                    'kind': 'file'
                },
                '/var/lib/cwl/cwl.input.json': {
                    'kind': 'json',
                    'content': {
                        'y': {
                            'basename': '99999999999999999999999999999998+99',
                            'location': 'keep:99999999999999999999999999999998+99',
                            'class': 'Directory'},
                        'x': {
                            'basename': u'blorp.txt',
                            'class': 'File',
                            'location': u'keep:169f39d466a5438ac4a90e779bf750c7+53/blorp.txt',
                            "size": 16
                        },
                        'z': {'basename': 'anonymous', 'class': 'Directory', 'listing': [
                            {'basename': 'renamed.txt',
                             'class': 'File',
                             'location': 'keep:99999999999999999999999999999998+99/file1.txt',
                             'size': 0
                            }
                        ]}
                    },
                    'kind': 'json'
                }
            },
            'secret_mounts': {},
            'state': 'Committed',
            'command': ['arvados-cwl-runner', '--local', '--api=containers',
                        '--no-log-timestamps', '--disable-validate',
                        '--eval-timeout=20', '--thread-count=1',
                        '--enable-reuse', "--collection-cache-size=256", '--debug', '--on-error=continue',
                        '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json'],
            'name': 'submit_wf.cwl',
            'container_image': '999999999999999999999999999999d3+99',
            'output_path': '/var/spool/cwl',
            'cwd': '/var/spool/cwl',
            'runtime_constraints': {
                'API': True,
                'vcpus': 1,
                'ram': (1024+256)*1024*1024
            },
            'use_existing': True,
            'properties': {},
            'secret_mounts': {}
        }

        stubs.expect_workflow_uuid = "zzzzz-7fd4e-zzzzzzzzzzzzzzz"
        stubs.api.workflows().create().execute.return_value = {
            "uuid": stubs.expect_workflow_uuid,
        }
        def update_mock(**kwargs):
            stubs.updated_uuid = kwargs.get('uuid')
            return mock.DEFAULT
        stubs.api.workflows().update.side_effect = update_mock
        stubs.api.workflows().update().execute.side_effect = lambda **kwargs: {
            "uuid": stubs.updated_uuid,
        }

        return func(self, stubs, *args, **kwargs)
    return wrapped


class TestSubmit(unittest.TestCase):
    @mock.patch("arvados_cwl.arvdocker.arv_docker_get_image")
    @mock.patch("time.sleep")
    @stubs
    def test_submit(self, stubs, tm, arvdock):
        def get_image(api_client, dockerRequirement, pull_image, project_uuid):
            if dockerRequirement["dockerPull"] == 'arvados/jobs:'+arvados_cwl.__version__:
                return '999999999999999999999999999999d3+99'
            elif dockerRequirement["dockerPull"] == "debian:8":
                return '999999999999999999999999999999d4+99'
        arvdock.side_effect = get_image

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=jobs", "--debug",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.collections().create.assert_has_calls([
            mock.call(body=JsonDiffMatcher({
                'manifest_text':
                '. 5bcc9fe8f8d5992e6cf418dc7ce4dbb3+16 0:16:blub.txt\n',
                'replication_desired': None,
                'name': 'submit_tool.cwl dependencies (5d373e7629203ce39e7c22af98a0f881+52)',
            }), ensure_unique_name=False),
            mock.call(body=JsonDiffMatcher({
                'manifest_text':
                '. 979af1245a12a1fed634d4222473bfdc+16 0:16:blorp.txt\n',
                'replication_desired': None,
                'name': 'submit_wf.cwl input (169f39d466a5438ac4a90e779bf750c7+53)',
            }), ensure_unique_name=False),
            mock.call(body=JsonDiffMatcher({
                'manifest_text':
                ". 68089141fbf7e020ac90a9d6a575bc8f+1312 0:1312:workflow.cwl\n",
                'replication_desired': None,
                'name': 'submit_wf.cwl',
            }), ensure_unique_name=True)        ])

        arvdock.assert_has_calls([
            mock.call(stubs.api, {"class": "DockerRequirement", "dockerPull": "debian:8"}, True, None),
            mock.call(stubs.api, {"class": "DockerRequirement", "dockerPull": "debian:8", 'http://arvados.org/cwl#dockerCollectionPDH': '999999999999999999999999999999d4+99'}, True, None),
            mock.call(stubs.api, {'dockerPull': 'arvados/jobs:'+arvados_cwl.__version__}, True, None)
        ])

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_no_reuse(self, stubs, tm):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=jobs", "--debug", "--disable-reuse",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["arv:enable_reuse"] = {"value": False}
        expect_pipeline["properties"] = {"run_options": {"enable_job_reuse": False}}

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_error_when_multiple_storage_classes_specified(self, stubs):
        storage_classes = "foo,bar"
        exited = arvados_cwl.main(
                ["--debug", "--storage-classes", storage_classes,
                 "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
                sys.stdin, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 1)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_on_error(self, stubs, tm):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=jobs", "--debug", "--on-error=stop",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["arv:on_error"] = "stop"

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_runner_ram(self, stubs, tm):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug", "--submit-runner-ram=2048",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["runtime_constraints"]["min_ram_mb_per_node"] = 2048

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_invalid_runner_ram(self, stubs, tm):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug", "--submit-runner-ram=-2048",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 1)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_output_name(self, stubs, tm):
        output_name = "test_output_name"

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug", "--output-name", output_name,
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["arv:output_name"] = output_name

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_pipeline_name(self, stubs, tm):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug", "--name=hello job 123",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 0)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["name"] = "hello job 123"

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')

    @mock.patch("time.sleep")
    @stubs
    def test_submit_output_tags(self, stubs, tm):
        output_tags = "tag0,tag1,tag2"

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug", "--output-tags", output_tags,
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 0)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["arv:output_tags"] = output_tags

        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')

    @mock.patch("time.sleep")
    @stubs
    def test_submit_with_project_uuid(self, stubs, tm):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--debug",
             "--project-uuid", project_uuid,
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            sys.stdout, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 0)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["owner_uuid"] = project_uuid
        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))

    @stubs
    def test_submit_container(self, stubs):        
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        stubs.api.collections().create.assert_has_calls([
            mock.call(body=JsonDiffMatcher({
                'manifest_text':
                '. 5bcc9fe8f8d5992e6cf418dc7ce4dbb3+16 0:16:blub.txt\n',
                'replication_desired': None,
                'name': 'submit_tool.cwl dependencies (5d373e7629203ce39e7c22af98a0f881+52)',
            }), ensure_unique_name=False),
            mock.call(body=JsonDiffMatcher({
                'manifest_text':
                '. 979af1245a12a1fed634d4222473bfdc+16 0:16:blorp.txt\n',
                'replication_desired': None,
                'name': 'submit_wf.cwl input (169f39d466a5438ac4a90e779bf750c7+53)',
            }), ensure_unique_name=False)])

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_no_reuse(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--disable-reuse",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = [
            'arvados-cwl-runner', '--local', '--api=containers',
            '--no-log-timestamps', '--disable-validate',
            '--eval-timeout=20', '--thread-count=1',
            '--disable-reuse', "--collection-cache-size=256",
            '--debug', '--on-error=continue',
            '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']
        expect_container["use_existing"] = False

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n') 
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_reuse_disabled_by_workflow(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "tests/wf/submit_wf_no_reuse.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
        self.assertEqual(exited, 0)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = [
            'arvados-cwl-runner', '--local', '--api=containers',
            '--no-log-timestamps', '--disable-validate',
            '--eval-timeout=20', '--thread-count=1',
            '--disable-reuse', "--collection-cache-size=256", '--debug', '--on-error=continue',
            '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']
        expect_container["use_existing"] = False
        expect_container["name"] = "submit_wf_no_reuse.cwl"
        expect_container["mounts"]["/var/lib/cwl/workflow.json"]["content"]["$graph"][1]["hints"] = [
            {
                "class": "http://arvados.org/cwl#ReuseRequirement",
                "enableReuse": False,
            },
        ]
        expect_container["mounts"]["/var/lib/cwl/workflow.json"]["content"]["$graph"][0]["$namespaces"] = {
            "arv": "http://arvados.org/cwl#",
            "cwltool": "http://commonwl.org/cwltool#"
        }

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')


    @stubs
    def test_submit_container_on_error(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--on-error=stop",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
 
        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       '--debug', '--on-error=stop',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_output_name(self, stubs):
        output_name = "test_output_name"
  
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--output-name", output_name,
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       "--output-name="+output_name, '--debug', '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']
        expect_container["output_name"] = output_name

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_storage_classes(self, stubs):     
        exited = arvados_cwl.main(
            ["--debug", "--submit", "--no-wait", "--api=containers", "--storage-classes=foo",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256", "--debug",
                                       "--storage-classes=foo", '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("arvados_cwl.task_queue.TaskQueue")
    @mock.patch("arvados_cwl.arvworkflow.ArvadosWorkflow.job")
    @mock.patch("arvados_cwl.executor.ArvCwlExecutor.make_output_collection", return_value = (None, None))
    @stubs
    def test_storage_classes_correctly_propagate_to_make_output_collection(self, stubs, make_output, job, tq):
        def set_final_output(job_order, output_callback, runtimeContext):
            output_callback("zzzzz-4zz18-zzzzzzzzzzzzzzzz", "success")
            return []
        job.side_effect = set_final_output

        exited = arvados_cwl.main(
            ["--debug", "--local", "--storage-classes=foo",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            sys.stdin, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        make_output.assert_called_with(u'Output of submit_wf.cwl', ['foo'], '', 'zzzzz-4zz18-zzzzzzzzzzzzzzzz')
        self.assertEqual(exited, 0)

    @mock.patch("arvados_cwl.task_queue.TaskQueue")
    @mock.patch("arvados_cwl.arvworkflow.ArvadosWorkflow.job")
    @mock.patch("arvados_cwl.executor.ArvCwlExecutor.make_output_collection", return_value = (None, None))
    @stubs
    def test_default_storage_classes_correctly_propagate_to_make_output_collection(self, stubs, make_output, job, tq):
        def set_final_output(job_order, output_callback, runtimeContext):
            output_callback("zzzzz-4zz18-zzzzzzzzzzzzzzzz", "success")
            return []
        job.side_effect = set_final_output

        exited = arvados_cwl.main(
            ["--debug", "--local",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            sys.stdin, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        make_output.assert_called_with(u'Output of submit_wf.cwl', ['default'], '', 'zzzzz-4zz18-zzzzzzzzzzzzzzzz')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_output_ttl(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--intermediate-output-ttl", "3600",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256", '--debug',
                                       '--on-error=continue',
                                       "--intermediate-output-ttl=3600",
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_trash_intermediate(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--trash-intermediate",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
            

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       '--debug', '--on-error=continue',
                                       "--trash-intermediate",
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_output_tags(self, stubs):
        output_tags = "tag0,tag1,tag2"

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--output-tags", output_tags,
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       "--output-tags="+output_tags, '--debug', '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_runner_ram(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--submit-runner-ram=2048",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["runtime_constraints"]["ram"] = (2048+256)*1024*1024

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("arvados.collection.CollectionReader")
    @mock.patch("time.sleep")
    @stubs
    def test_submit_file_keepref(self, stubs, tm, collectionReader):
        collectionReader().find.return_value = arvados.arvfile.ArvadosFile(mock.MagicMock(), "blorp.txt")
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "tests/wf/submit_keepref_wf.cwl"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 0)

    @mock.patch("arvados.collection.CollectionReader")
    @mock.patch("time.sleep")
    @stubs
    def test_submit_keepref(self, stubs, tm, reader):
        with open("tests/wf/expect_arvworkflow.cwl") as f:
            reader().open().__enter__().read.return_value = f.read()

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "keep:99999999999999999999999999999994+99/expect_arvworkflow.cwl#main", "-x", "XxX"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_container = {
            'priority': 500,
            'mounts': {
                '/var/spool/cwl': {
                    'writable': True,
                    'kind': 'collection'
                },
                'stdout': {
                    'path': '/var/spool/cwl/cwl.output.json',
                    'kind': 'file'
                },
                '/var/lib/cwl/workflow': {
                    'portable_data_hash': '99999999999999999999999999999994+99',
                    'kind': 'collection'
                },
                '/var/lib/cwl/cwl.input.json': {
                    'content': {
                        'x': 'XxX'
                    },
                    'kind': 'json'
                }
            }, 'state': 'Committed',
            'output_path': '/var/spool/cwl',
            'name': 'expect_arvworkflow.cwl#main',
            'container_image': '999999999999999999999999999999d3+99',
            'command': ['arvados-cwl-runner', '--local', '--api=containers',
                        '--no-log-timestamps', '--disable-validate',
                        '--eval-timeout=20', '--thread-count=1',
                        '--enable-reuse', "--collection-cache-size=256", '--debug', '--on-error=continue',
                        '/var/lib/cwl/workflow/expect_arvworkflow.cwl#main', '/var/lib/cwl/cwl.input.json'],
            'cwd': '/var/spool/cwl',
            'runtime_constraints': {
                'API': True,
                'vcpus': 1,
                'ram': 1342177280
            },
            'use_existing': True,
            'properties': {},
            'secret_mounts': {}
        }

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @mock.patch("arvados.collection.CollectionReader")
    @mock.patch("time.sleep")
    @stubs
    def test_submit_jobs_keepref(self, stubs, tm, reader):
        with open("tests/wf/expect_arvworkflow.cwl") as f:
            reader().open().__enter__().read.return_value = f.read()

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=jobs", "--debug",
             "keep:99999999999999999999999999999994+99/expect_arvworkflow.cwl#main", "-x", "XxX"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["x"] = "XxX"
        del expect_pipeline["components"]["cwl-runner"]["script_parameters"]["y"]
        del expect_pipeline["components"]["cwl-runner"]["script_parameters"]["z"]
        expect_pipeline["components"]["cwl-runner"]["script_parameters"]["cwl:tool"] = "99999999999999999999999999999994+99/expect_arvworkflow.cwl#main"
        expect_pipeline["name"] = "expect_arvworkflow.cwl#main"
        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(exited, 0)

    @mock.patch("time.sleep")
    @stubs
    def test_submit_arvworkflow(self, stubs, tm):
        with open("tests/wf/expect_arvworkflow.cwl") as f:
            stubs.api.workflows().get().execute.return_value = {"definition": f.read(), "name": "a test workflow"}

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "962eh-7fd4e-gkbzl62qqtfig37", "-x", "XxX"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_container = {
            'priority': 500,
            'mounts': {
                '/var/spool/cwl': {
                    'writable': True,
                    'kind': 'collection'
                },
                'stdout': {
                    'path': '/var/spool/cwl/cwl.output.json',
                    'kind': 'file'
                },
                '/var/lib/cwl/workflow.json': {
                    'kind': 'json',
                    'content': {
                        'cwlVersion': 'v1.0',
                        '$graph': [
                            {
                                'id': '#main',
                                'inputs': [
                                    {'type': 'string', 'id': '#main/x'}
                                ],
                                'steps': [
                                    {'in': [{'source': '#main/x', 'id': '#main/step1/x'}],
                                     'run': '#submit_tool.cwl',
                                     'id': '#main/step1',
                                     'out': []}
                                ],
                                'class': 'Workflow',
                                'outputs': []
                            },
                            {
                                'inputs': [
                                    {
                                        'inputBinding': {'position': 1},
                                        'type': 'string',
                                        'id': '#submit_tool.cwl/x'}
                                ],
                                'requirements': [
                                    {
                                        'dockerPull': 'debian:8',
                                        'class': 'DockerRequirement',
                                        "http://arvados.org/cwl#dockerCollectionPDH": "999999999999999999999999999999d4+99"
                                    }
                                ],
                                'id': '#submit_tool.cwl',
                                'outputs': [],
                                'baseCommand': 'cat',
                                'class': 'CommandLineTool'
                            }
                        ]
                    }
                },
                '/var/lib/cwl/cwl.input.json': {
                    'content': {
                        'x': 'XxX'
                    },
                    'kind': 'json'
                }
            }, 'state': 'Committed',
            'output_path': '/var/spool/cwl',
            'name': 'a test workflow',
            'container_image': "999999999999999999999999999999d3+99",
            'command': ['arvados-cwl-runner', '--local', '--api=containers',
                        '--no-log-timestamps', '--disable-validate',
                        '--eval-timeout=20', '--thread-count=1',
                        '--enable-reuse', "--collection-cache-size=256", '--debug', '--on-error=continue',
                        '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json'],
            'cwd': '/var/spool/cwl',
            'runtime_constraints': {
                'API': True,
                'vcpus': 1,
                'ram': 1342177280
            },
            'use_existing': True,
            'properties': {
                "template_uuid": "962eh-7fd4e-gkbzl62qqtfig37"
            },
            'secret_mounts': {}
        }

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_name(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--name=hello container 123",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["name"] = "hello container 123"

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_missing_input(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
        self.assertEqual(exited, 0)

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job_missing.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
        self.assertEqual(exited, 1)

    @stubs
    def test_submit_container_project(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--project-uuid="+project_uuid,
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["owner_uuid"] = project_uuid
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       "--eval-timeout=20", "--thread-count=1",
                                       '--enable-reuse', "--collection-cache-size=256", '--debug',
                                       '--on-error=continue',
                                       '--project-uuid='+project_uuid,
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_eval_timeout(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--eval-timeout=60",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=60.0', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       '--debug', '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_collection_cache(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--collection-cache-size=500",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=1',
                                       '--enable-reuse', "--collection-cache-size=500",
                                       '--debug', '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']
        expect_container["runtime_constraints"]["ram"] = (1024+500)*1024*1024

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_thread_count(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--thread-count=20",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["command"] = ['arvados-cwl-runner', '--local', '--api=containers',
                                       '--no-log-timestamps', '--disable-validate',
                                       '--eval-timeout=20', '--thread-count=20',
                                       '--enable-reuse', "--collection-cache-size=256",
                                       '--debug', '--on-error=continue',
                                       '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_job_runner_image(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=jobs", "--debug", "--submit-runner-image=arvados/jobs:123",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        stubs.expect_pipeline_instance["components"]["cwl-runner"]["runtime_constraints"]["docker_image"] = "999999999999999999999999999999d5+99"

        expect_pipeline = copy.deepcopy(stubs.expect_pipeline_instance)
        stubs.api.pipeline_instances().create.assert_called_with(
            body=JsonDiffMatcher(expect_pipeline))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_runner_image(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--submit-runner-image=arvados/jobs:123",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        stubs.expect_container_spec["container_image"] = "999999999999999999999999999999d5+99"

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_priority(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--priority=669",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        stubs.expect_container_spec["priority"] = 669

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_wf_runner_resources(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
                "tests/wf/submit_wf_runner_resources.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)
        expect_container["runtime_constraints"] = {
            "API": True,
            "vcpus": 2,
            "ram": (2000+512) * 2**20
        }
        expect_container["name"] = "submit_wf_runner_resources.cwl"
        expect_container["mounts"]["/var/lib/cwl/workflow.json"]["content"]["$graph"][1]["hints"] = [
            {
                "class": "http://arvados.org/cwl#WorkflowRunnerResources",
                "coresMin": 2,
                "ramMin": 2000,
                "keep_cache": 512
            }
        ]
        expect_container["mounts"]["/var/lib/cwl/workflow.json"]["content"]["$graph"][0]["$namespaces"] = {
            "arv": "http://arvados.org/cwl#",
        }
        expect_container['command'] = ['arvados-cwl-runner', '--local', '--api=containers',
                        '--no-log-timestamps', '--disable-validate',
                        '--eval-timeout=20', '--thread-count=1',
                        '--enable-reuse', "--collection-cache-size=512", '--debug', '--on-error=continue',
                        '/var/lib/cwl/workflow.json#main', '/var/lib/cwl/cwl.input.json']

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    def tearDown(self):
        arvados_cwl.arvdocker.arv_docker_clear_cache()

    @mock.patch("arvados.commands.keepdocker.find_one_image_hash")
    @mock.patch("cwltool.docker.DockerCommandLineJob.get_image")
    @mock.patch("arvados.api")
    def test_arvados_jobs_image(self, api, get_image, find_one_image_hash):
        arvados_cwl.arvdocker.arv_docker_clear_cache()

        arvrunner = mock.MagicMock()
        arvrunner.project_uuid = ""
        api.return_value = mock.MagicMock()
        arvrunner.api = api.return_value
        arvrunner.api.links().list().execute.side_effect = ({"items": [{"created_at": "",
                                                                        "head_uuid": "zzzzz-4zz18-zzzzzzzzzzzzzzb",
                                                                        "link_class": "docker_image_repo+tag",
                                                                        "name": "arvados/jobs:"+arvados_cwl.__version__,
                                                                        "owner_uuid": "",
                                                                        "properties": {"image_timestamp": ""}}], "items_available": 1, "offset": 0},
                                                            {"items": [{"created_at": "",
                                                                        "head_uuid": "",
                                                                        "link_class": "docker_image_hash",
                                                                        "name": "123456",
                                                                        "owner_uuid": "",
                                                                        "properties": {"image_timestamp": ""}}], "items_available": 1, "offset": 0}
        )
        find_one_image_hash.return_value = "123456"

        arvrunner.api.collections().list().execute.side_effect = ({"items": [{"uuid": "zzzzz-4zz18-zzzzzzzzzzzzzzb",
                                                                              "owner_uuid": "",
                                                                              "manifest_text": "",
                                                                              "properties": ""
                                                                          }], "items_available": 1, "offset": 0},)
        arvrunner.api.collections().create().execute.return_value = {"uuid": ""}
        arvrunner.api.collections().get().execute.return_value = {"uuid": "zzzzz-4zz18-zzzzzzzzzzzzzzb",
                                                                  "portable_data_hash": "9999999999999999999999999999999b+99"}
        self.assertEqual("9999999999999999999999999999999b+99",
                         arvados_cwl.runner.arvados_jobs_image(arvrunner, "arvados/jobs:"+arvados_cwl.__version__))


    @stubs
    def test_submit_secrets(self, stubs):
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug",
                "tests/wf/secret_wf.cwl", "tests/secret_test_job.yml"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = {
            "command": [
                "arvados-cwl-runner",
                "--local",
                "--api=containers",
                "--no-log-timestamps",
                "--disable-validate",
                "--eval-timeout=20",
                '--thread-count=1',
                "--enable-reuse",
                "--collection-cache-size=256",
                '--debug',
                "--on-error=continue",
                "/var/lib/cwl/workflow.json#main",
                "/var/lib/cwl/cwl.input.json"
            ],
            "container_image": "999999999999999999999999999999d3+99",
            "cwd": "/var/spool/cwl",
            "mounts": {
                "/var/lib/cwl/cwl.input.json": {
                    "content": {
                        "pw": {
                            "$include": "/secrets/s0"
                        }
                    },
                    "kind": "json"
                },
                "/var/lib/cwl/workflow.json": {
                    "content": {
                        "$graph": [
                            {
                                "$namespaces": {
                                    "cwltool": "http://commonwl.org/cwltool#"
                                },
                                "arguments": [
                                    "md5sum",
                                    "example.conf"
                                ],
                                "class": "CommandLineTool",
                                "hints": [
                                    {
                                        "class": "http://commonwl.org/cwltool#Secrets",
                                        "secrets": [
                                            "#secret_job.cwl/pw"
                                        ]
                                    }
                                ],
                                "id": "#secret_job.cwl",
                                "inputs": [
                                    {
                                        "id": "#secret_job.cwl/pw",
                                        "type": "string"
                                    }
                                ],
                                "outputs": [
                                    {
                                        "id": "#secret_job.cwl/out",
                                        "type": "stdout"
                                    }
                                ],
                                "stdout": "hashed_example.txt",
                                "requirements": [
                                    {
                                        "class": "InitialWorkDirRequirement",
                                        "listing": [
                                            {
                                                "entry": "username: user\npassword: $(inputs.pw)\n",
                                                "entryname": "example.conf"
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "class": "Workflow",
                                "hints": [
                                    {
                                        "class": "DockerRequirement",
                                        "dockerPull": "debian:8",
                                        "http://arvados.org/cwl#dockerCollectionPDH": "999999999999999999999999999999d4+99"
                                    },
                                    {
                                        "class": "http://commonwl.org/cwltool#Secrets",
                                        "secrets": [
                                            "#main/pw"
                                        ]
                                    }
                                ],
                                "id": "#main",
                                "inputs": [
                                    {
                                        "id": "#main/pw",
                                        "type": "string"
                                    }
                                ],
                                "outputs": [
                                    {
                                        "id": "#main/out",
                                        "outputSource": "#main/step1/out",
                                        "type": "File"
                                    }
                                ],
                                "steps": [
                                    {
                                        "id": "#main/step1",
                                        "in": [
                                            {
                                                "id": "#main/step1/pw",
                                                "source": "#main/pw"
                                            }
                                        ],
                                        "out": [
                                            "#main/step1/out"
                                        ],
                                        "run": "#secret_job.cwl"
                                    }
                                ]
                            }
                        ],
                        "cwlVersion": "v1.0"
                    },
                    "kind": "json"
                },
                "/var/spool/cwl": {
                    "kind": "collection",
                    "writable": True
                },
                "stdout": {
                    "kind": "file",
                    "path": "/var/spool/cwl/cwl.output.json"
                }
            },
            "name": "secret_wf.cwl",
            "output_path": "/var/spool/cwl",
            "priority": 500,
            "properties": {},
            "runtime_constraints": {
                "API": True,
                "ram": 1342177280,
                "vcpus": 1
            },
            "secret_mounts": {
                "/secrets/s0": {
                    "content": "blorp",
                    "kind": "text"
                }
            },
            "state": "Committed",
            "use_existing": True
        }

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_request_uuid(self, stubs):
        stubs.expect_container_request_uuid = "zzzzz-xvhdp-yyyyyyyyyyyyyyy"

        stubs.api.container_requests().update().execute.return_value = {
            "uuid": stubs.expect_container_request_uuid,
            "container_uuid": "zzzzz-dz642-zzzzzzzzzzzzzzz",
            "state": "Queued"
        }

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--submit-request-uuid=zzzzz-xvhdp-yyyyyyyyyyyyyyy",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        stubs.api.container_requests().update.assert_called_with(
            uuid="zzzzz-xvhdp-yyyyyyyyyyyyyyy", body=JsonDiffMatcher(stubs.expect_container_spec), cluster_id="zzzzz")
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_container_cluster_id(self, stubs):
        stubs.api._rootDesc["remoteHosts"]["zbbbb"] = "123"

        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--submit-runner-cluster=zbbbb",
                "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)

        expect_container = copy.deepcopy(stubs.expect_container_spec)

        stubs.api.container_requests().create.assert_called_with(
            body=JsonDiffMatcher(expect_container), cluster_id="zbbbb")
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_container_request_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_submit_validate_cluster_id(self, stubs):
        stubs.api._rootDesc["remoteHosts"]["zbbbb"] = "123"
        exited = arvados_cwl.main(
            ["--submit", "--no-wait", "--api=containers", "--debug", "--submit-runner-cluster=zcccc",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api, keep_client=stubs.keep_client)
        self.assertEqual(exited, 1)


class TestCreateTemplate(unittest.TestCase):
    existing_template_uuid = "zzzzz-d1hrv-validworkfloyml"

    def _adjust_script_params(self, expect_component):
        expect_component['script_parameters']['x'] = {
            'dataclass': 'File',
            'required': True,
            'type': 'File',
            'value': '169f39d466a5438ac4a90e779bf750c7+53/blorp.txt',
        }
        expect_component['script_parameters']['y'] = {
            'dataclass': 'Collection',
            'required': True,
            'type': 'Directory',
            'value': '99999999999999999999999999999998+99',
        }
        expect_component['script_parameters']['z'] = {
            'dataclass': 'Collection',
            'required': True,
            'type': 'Directory',
        }

    @stubs
    def test_create(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--create-workflow", "--debug",
             "--api=jobs",
             "--project-uuid", project_uuid,
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_instances().create.refute_called()
        stubs.api.jobs().create.refute_called()

        expect_component = copy.deepcopy(stubs.expect_job_spec)
        self._adjust_script_params(expect_component)
        expect_template = {
            "components": {
                "submit_wf.cwl": expect_component,
            },
            "name": "submit_wf.cwl",
            "owner_uuid": project_uuid,
        }
        stubs.api.pipeline_templates().create.assert_called_with(
            body=JsonDiffMatcher(expect_template), ensure_unique_name=True)

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_template_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_create_name(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--create-workflow", "--debug",
             "--project-uuid", project_uuid,
             "--api=jobs",
             "--name", "testing 123",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_instances().create.refute_called()
        stubs.api.jobs().create.refute_called()

        expect_component = copy.deepcopy(stubs.expect_job_spec)
        self._adjust_script_params(expect_component)
        expect_template = {
            "components": {
                "testing 123": expect_component,
            },
            "name": "testing 123",
            "owner_uuid": project_uuid,
        }
        stubs.api.pipeline_templates().create.assert_called_with(
            body=JsonDiffMatcher(expect_template), ensure_unique_name=True)

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_pipeline_template_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_update_name(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--update-workflow", self.existing_template_uuid,
             "--debug",
             "--project-uuid", project_uuid,
             "--api=jobs",
             "--name", "testing 123",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_instances().create.refute_called()
        stubs.api.jobs().create.refute_called()

        expect_component = copy.deepcopy(stubs.expect_job_spec)
        self._adjust_script_params(expect_component)
        expect_template = {
            "components": {
                "testing 123": expect_component,
            },
            "name": "testing 123",
            "owner_uuid": project_uuid,
        }
        stubs.api.pipeline_templates().create.refute_called()
        stubs.api.pipeline_templates().update.assert_called_with(
            body=JsonDiffMatcher(expect_template), uuid=self.existing_template_uuid)

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         self.existing_template_uuid + '\n')
        self.assertEqual(exited, 0)
        

class TestCreateWorkflow(unittest.TestCase):
    existing_workflow_uuid = "zzzzz-7fd4e-validworkfloyml"
    expect_workflow = StripYAMLComments(
        open("tests/wf/expect_packed.cwl").read())

    @stubs
    def test_create(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--create-workflow", "--debug",
             "--api=containers",
             "--project-uuid", project_uuid,
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_templates().create.refute_called()
        stubs.api.container_requests().create.refute_called()

        body = {
            "workflow": {
                "owner_uuid": project_uuid,
                "name": "submit_wf.cwl",
                "description": "",
                "definition": self.expect_workflow,
            }
        }
        stubs.api.workflows().create.assert_called_with(
            body=JsonDiffMatcher(body))

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_workflow_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_create_name(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--create-workflow", "--debug",
             "--api=containers",
             "--project-uuid", project_uuid,
             "--name", "testing 123",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_templates().create.refute_called()
        stubs.api.container_requests().create.refute_called()

        body = {
            "workflow": {
                "owner_uuid": project_uuid,
                "name": "testing 123",
                "description": "",
                "definition": self.expect_workflow,
            }
        }
        stubs.api.workflows().create.assert_called_with(
            body=JsonDiffMatcher(body))

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_workflow_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_incompatible_api(self, stubs):
        capture_stderr = io.StringIO()
        acr_logger = logging.getLogger('arvados.cwl-runner')
        stderr_logger = logging.StreamHandler(capture_stderr)
        acr_logger.addHandler(stderr_logger)

        exited = arvados_cwl.main(
            ["--update-workflow", self.existing_workflow_uuid,
             "--api=jobs",
             "--debug",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            sys.stderr, sys.stderr, api_client=stubs.api)
        self.assertEqual(exited, 1)
        self.assertRegexpMatches(
            capture_stderr.getvalue(),
            "--update-workflow arg '{}' uses 'containers' API, but --api='jobs' specified".format(self.existing_workflow_uuid))
        acr_logger.removeHandler(stderr_logger)

    @stubs
    def test_update(self, stubs):
        exited = arvados_cwl.main(
            ["--update-workflow", self.existing_workflow_uuid,
             "--debug",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        body = {
            "workflow": {
                "name": "submit_wf.cwl",
                "description": "",
                "definition": self.expect_workflow,
            }
        }
        stubs.api.workflows().update.assert_called_with(
            uuid=self.existing_workflow_uuid,
            body=JsonDiffMatcher(body))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         self.existing_workflow_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_update_name(self, stubs):
        exited = arvados_cwl.main(
            ["--update-workflow", self.existing_workflow_uuid,
             "--debug", "--name", "testing 123",
             "tests/wf/submit_wf.cwl", "tests/submit_test_job.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        body = {
            "workflow": {
                "name": "testing 123",
                "description": "",
                "definition": self.expect_workflow,
            }
        }
        stubs.api.workflows().update.assert_called_with(
            uuid=self.existing_workflow_uuid,
            body=JsonDiffMatcher(body))
        self.assertEqual(stubs.capture_stdout.getvalue(),
                         self.existing_workflow_uuid + '\n')
        self.assertEqual(exited, 0)

    @stubs
    def test_create_collection_per_tool(self, stubs):
        project_uuid = 'zzzzz-j7d0g-zzzzzzzzzzzzzzz'

        exited = arvados_cwl.main(
            ["--create-workflow", "--debug",
             "--api=containers",
             "--project-uuid", project_uuid,
             "tests/collection_per_tool/collection_per_tool.cwl"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        toolfile = "tests/collection_per_tool/collection_per_tool_packed.cwl"
        expect_workflow = StripYAMLComments(open(toolfile).read())

        body = {
            "workflow": {
                "owner_uuid": project_uuid,
                "name": "collection_per_tool.cwl",
                "description": "",
                "definition": expect_workflow,
            }
        }
        stubs.api.workflows().create.assert_called_with(
            body=JsonDiffMatcher(body))

        self.assertEqual(stubs.capture_stdout.getvalue(),
                         stubs.expect_workflow_uuid + '\n')
        self.assertEqual(exited, 0)

class TestTemplateInputs(unittest.TestCase):
    expect_template = {
        "components": {
            "inputs_test.cwl": {
                'runtime_constraints': {
                    'docker_image': '999999999999999999999999999999d3+99',
                    'min_ram_mb_per_node': 1024
                },
                'script_parameters': {
                    'cwl:tool':
                    'a2de777156fb700f1363b1f2e370adca+60/workflow.cwl#main',
                    'optionalFloatInput': None,
                    'fileInput': {
                        'type': 'File',
                        'dataclass': 'File',
                        'required': True,
                        'title': "It's a file; we expect to find some characters in it.",
                        'description': 'If there were anything further to say, it would be said here,\nor here.'
                    },
                    'floatInput': {
                        'type': 'float',
                        'dataclass': 'number',
                        'required': True,
                        'title': 'Floats like a duck',
                        'default': 0.1,
                        'value': 0.1,
                    },
                    'optionalFloatInput': {
                        'type': ['null', 'float'],
                        'dataclass': 'number',
                        'required': False,
                    },
                    'boolInput': {
                        'type': 'boolean',
                        'dataclass': 'boolean',
                        'required': True,
                        'title': 'True or false?',
                    },
                },
                'repository': 'arvados',
                'script_version': 'master',
                'minimum_script_version': '570509ab4d2ef93d870fd2b1f2eab178afb1bad9',
                'script': 'cwl-runner',
            },
        },
        "name": "inputs_test.cwl",
    }

    @stubs
    def test_inputs_empty(self, stubs):
        exited = arvados_cwl.main(
            ["--create-template",
             "tests/wf/inputs_test.cwl", "tests/order/empty_order.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        stubs.api.pipeline_templates().create.assert_called_with(
            body=JsonDiffMatcher(self.expect_template), ensure_unique_name=True)

        self.assertEqual(exited, 0)

    @stubs
    def test_inputs(self, stubs):
        exited = arvados_cwl.main(
            ["--create-template",
             "tests/wf/inputs_test.cwl", "tests/order/inputs_test_order.json"],
            stubs.capture_stdout, sys.stderr, api_client=stubs.api)

        expect_template = copy.deepcopy(self.expect_template)
        params = expect_template[
            "components"]["inputs_test.cwl"]["script_parameters"]
        params["fileInput"]["value"] = '169f39d466a5438ac4a90e779bf750c7+53/blorp.txt'
        params["cwl:tool"] = 'a2de777156fb700f1363b1f2e370adca+60/workflow.cwl#main'
        params["floatInput"]["value"] = 1.234
        params["boolInput"]["value"] = True

        stubs.api.pipeline_templates().create.assert_called_with(
            body=JsonDiffMatcher(expect_template), ensure_unique_name=True)
        self.assertEqual(exited, 0)
