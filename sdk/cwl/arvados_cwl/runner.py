import os
import urlparse
from functools import partial
import logging
import json
import re
from cStringIO import StringIO

import cwltool.draft2tool
from cwltool.draft2tool import CommandLineTool
import cwltool.workflow
from cwltool.process import get_feature, scandeps, UnsupportedRequirement, normalizeFilesDirs
from cwltool.load_tool import fetch_document
from cwltool.pathmapper import adjustFileObjs, adjustDirObjs

import arvados.collection
import ruamel.yaml as yaml

from .arvdocker import arv_docker_get_image
from .pathmapper import ArvPathMapper

logger = logging.getLogger('arvados.cwl-runner')

cwltool.draft2tool.ACCEPTLIST_RE = re.compile(r"^[a-zA-Z0-9._+-]+$")

def del_listing(obj):
    if obj.get("location", "").startswith("keep:") and "listing" in obj:
        del obj["listing"]

def upload_dependencies(arvrunner, name, document_loader,
                        workflowobj, uri, loadref_run):
    """Upload the dependencies of the workflowobj document to Keep.

    Returns a pathmapper object mapping local paths to keep references.  Also
    does an in-place update of references in "workflowobj".

    Use scandeps to find $import, $include, $schemas, run, File and Directory
    fields that represent external references.

    If workflowobj has an "id" field, this will reload the document to ensure
    it is scanning the raw document prior to preprocessing.
    """

    loaded = set()
    def loadref(b, u):
        joined = urlparse.urljoin(b, u)
        defrg, _ = urlparse.urldefrag(joined)
        if defrg not in loaded:
            loaded.add(defrg)
            # Use fetch_text to get raw file (before preprocessing).
            text = document_loader.fetch_text(defrg)
            if isinstance(text, bytes):
                textIO = StringIO(text.decode('utf-8'))
            else:
                textIO = StringIO(text)
            return yaml.safe_load(textIO)
        else:
            return {}

    if loadref_run:
        loadref_fields = set(("$import", "run"))
    else:
        loadref_fields = set(("$import",))

    scanobj = workflowobj
    if "id" in workflowobj:
        # Need raw file content (before preprocessing) to ensure
        # that external references in $include and $mixin are captured.
        scanobj = loadref("", workflowobj["id"])

    sc = scandeps(uri, scanobj,
                  loadref_fields,
                  set(("$include", "$schemas", "location")),
                  loadref)

    normalizeFilesDirs(sc)

    if "id" in workflowobj:
        sc.append({"class": "File", "location": workflowobj["id"]})

    mapper = ArvPathMapper(arvrunner, sc, "",
                           "keep:%s",
                           "keep:%s/%s",
                           name=name)

    def setloc(p):
        if not p["location"].startswith("_:") and not p["location"].startswith("keep:"):
            p["location"] = mapper.mapper(p["location"]).target
    adjustFileObjs(workflowobj, setloc)
    adjustDirObjs(workflowobj, setloc)

    return mapper


def upload_docker(arvrunner, tool):
    if isinstance(tool, CommandLineTool):
        (docker_req, docker_is_req) = get_feature(tool, "DockerRequirement")
        if docker_req:
            arv_docker_get_image(arvrunner.api, docker_req, True, arvrunner.project_uuid)
    elif isinstance(tool, cwltool.workflow.Workflow):
        for s in tool.steps:
            upload_docker(arvrunner, s.embedded_tool)


class Runner(object):
    def __init__(self, runner, tool, job_order, enable_reuse):
        self.arvrunner = runner
        self.tool = tool
        self.job_order = job_order
        self.running = False
        self.enable_reuse = enable_reuse
        self.uuid = None

    def update_pipeline_component(self, record):
        pass

    def arvados_job_spec(self, *args, **kwargs):
        upload_docker(self.arvrunner, self.tool)

        self.name = os.path.basename(self.tool.tool["id"])

        workflowmapper = upload_dependencies(self.arvrunner,
                                             self.name,
                                             self.tool.doc_loader,
                                             self.tool.tool,
                                             self.tool.tool["id"],
                                             True)

        jobmapper = upload_dependencies(self.arvrunner,
                                        os.path.basename(self.job_order.get("id", "#")),
                                        self.tool.doc_loader,
                                        self.job_order,
                                        self.job_order.get("id", "#"),
                                        False)

        adjustDirObjs(self.job_order, del_listing)

        if "id" in self.job_order:
            del self.job_order["id"]

        return workflowmapper


    def done(self, record):
        if record["state"] == "Complete":
            if record.get("exit_code") is not None:
                if record["exit_code"] == 33:
                    processStatus = "UnsupportedRequirement"
                elif record["exit_code"] == 0:
                    processStatus = "success"
                else:
                    processStatus = "permanentFail"
            else:
                processStatus = "success"
        else:
            processStatus = "permanentFail"

        outputs = None
        try:
            try:
                outc = arvados.collection.Collection(record["output"])
                with outc.open("cwl.output.json") as f:
                    outputs = json.load(f)
                def keepify(fileobj):
                    path = fileobj["location"]
                    if not path.startswith("keep:"):
                        fileobj["location"] = "keep:%s/%s" % (record["output"], path)
                adjustFileObjs(outputs, keepify)
                adjustDirObjs(outputs, keepify)
            except Exception as e:
                logger.error("While getting final output object: %s", e)
            self.arvrunner.output_callback(outputs, processStatus)
        finally:
            del self.arvrunner.processes[record["uuid"]]
