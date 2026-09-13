"""Independent CLI boundary checks; synthetic exchange, real parsing/SQLite."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

import pytest

from kir import __main__ as cli
from kir.project_store import ProjectStore, CREATE_STORE_SCHEMA, TASK_STORE_SCHEMA
from kir.tests.test_project_cli_lifecycle import _call, _fresh
from kir.tests.test_selected_project_submission import source_project


SECRET = "cli-sensitive-value-must-not-appear"


def setup(tmp_path, schema=CREATE_STORE_SCHEMA):
    tmp_path.mkdir(parents=True,exist_ok=True)
    project = source_project()
    store = ProjectStore.create(tmp_path / "project.sqlite", project, schema=schema)
    target = {"journal_id":str(uuid4()), "instance_id":str(uuid4()), "revit_version":"2023"}
    session = str(uuid4())
    declaration = {"protocol":"kir-revit-connector/4", "target":target, "session_id":session,
        "token":SECRET, "pipe_name":"not-a-live-pipe", "process_id":123,
        "expires_utc":(datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")+"0Z"}
    directory = tmp_path / "discovery"
    instance = directory / target["instance_id"]
    instance.mkdir(parents=True)
    (instance / (session + ".json")).write_text(json.dumps(declaration),encoding="utf-8")
    client=tmp_path/"not-invoked-client";client.write_text("fixture only",encoding="utf-8")
    operation=str(uuid4())
    flags=["--directory",str(directory),"--journal-id",target["journal_id"],"--instance-id",target["instance_id"],
        "--revit-version","2023","--session-id",session,"--client",str(client)]
    publish=["project","create-publish",str(store.path),*flags,"--expected",project.revision_id,
        "--instance","section","--operation-id",operation,"--document-key","fixture-doc",
        "--bind-view","no","--bind-selection","no","--confirm-create"]
    return store, project, declaration, flags, publish, operation


def wire_exchange(store, calls, *, lost=False, document="fixture-doc"):
    def exchange(advertisement, raw, **kwargs):
        request=json.loads(raw)
        calls.append(request["kind"])
        assert request["token"] == SECRET
        response={"protocol":request["protocol"],"target":request["target"],"session_id":request["session_id"],
            "request_id":request["request_id"],"ok":True,"status":"ready","error":None,"context":None,"receipt":None}
        if request["kind"] == "context":
            response.update(status="context",context={"has_document":True,"document_key":document,"document_title":SECRET,
                "revit_version":request["target"]["revit_version"],"revision":8,"active_view_id":42,"selection_digest":hashlib.sha256(b"").hexdigest(),"selection_count":0,
                "is_family_document":False,"is_read_only":False,"is_modifiable":False,"complete":True})
        elif request["kind"] in ("execute","receipt","recover_receipt"):
            journal=request.get("recovery_target",request["target"])["journal_id"]
            record=store.find_create_publication(journal_id=journal,operation_id=request["operation_id"]).record
            if request["kind"] == "execute" and lost:
                from kir.revit_transport import ConnectorTransportError
                raise ConnectorTransportError("exchange_failed","response_read",delivery="unknown")
            result={"ok":True,**{op["payload"]["id"]:{"id":str(700+i)} for i,op in enumerate(record.to_dict()["plan_evidence"]["ops"])}}
            response.update(status="receipt",receipt={**record.binding_dict(),"document_key":record.binding_dict()["precondition"]["document_key"],
                "state":"invocation_completed","started":True,"may_retry":False,"transaction_evidence":"changes_observed",
                "semantic_evidence":"unverified","result_json":json.dumps(result),"result_truncated":False,"result_error":None,"error":None,
                "changes":{"added":list(range(700,700+len(result)-1)),"modified":[],"deleted":[],"transaction_names":["KIR"],"truncated":False},
                "timestamp_utc":"2026-09-06T15:00:00Z"})
        return json.dumps(response).encode()
    return exchange


def test_upgrade_keeps_publication_envelope_schema(tmp_path):
    store, project, *_ = setup(tmp_path,TASK_STORE_SCHEMA)
    code,raw,error=_fresh(["project","create-upgrade",str(store.path),"--expected",project.revision_id])
    assert code == cli.ANSWERED,error
    assert json.loads(raw)["schema"] == "kir-project-publication-cli/1"
    assert ProjectStore.open(store.path).schema == CREATE_STORE_SCHEMA


@pytest.mark.parametrize("remove", ["--confirm-create","--document-key","--instance","--bind-view","--bind-selection","--session-id"])
def test_required_publication_choices_fail_before_store_or_discovery(tmp_path,remove):
    store, _, _, _, command, _=setup(tmp_path)
    before=store.path.read_bytes()
    index=command.index(remove)
    del command[index:index+(1 if remove=="--confirm-create" else 2)]
    code,raw,error=_fresh(command)
    assert code==cli.NOT_DONE and json.loads(raw)["diagnostic_code"]=="invalid_publication_arguments"
    assert error=="" and SECRET not in raw and store.path.read_bytes()==before


@pytest.mark.parametrize("tail", [["--timeout-ms",SECRET],["--bind-view",SECRET],["--isolation",SECRET],["--token",SECRET],["--all-instances"]])
def test_parser_errors_never_echo_secret_values(tmp_path,tail):
    _,_,_,_,command,_=setup(tmp_path)
    code,raw,error=_fresh([*command,*tail])
    assert code==cli.NOT_DONE and SECRET not in raw+error and error==""
    assert json.loads(raw)["diagnostic_code"]=="invalid_publication_arguments"


def test_no_implicit_upgrade_or_missing_database_creation(tmp_path):
    store,_,_,_,command,_=setup(tmp_path,TASK_STORE_SCHEMA)
    before=store.path.read_bytes()
    code,raw,error=_fresh(command)
    assert code==cli.REFUSED and json.loads(raw)["diagnostic_code"]=="explicit_create_upgrade_required"
    assert store.path.read_bytes()==before and not error
    missing=tmp_path/"absent.sqlite"
    command[2]=str(missing)
    code,raw,error=_fresh(command)
    assert code!=0 and not missing.exists() and SECRET not in raw+error


def test_stale_source_and_wrong_selected_runtime_do_not_send(tmp_path,monkeypatch):
    import kir.standalone_publish as publisher
    store,project,_,_,command,_=setup(tmp_path)
    def forbidden(*args,**kwargs): pytest.fail("invalid target/source reached transport")
    monkeypatch.setattr(publisher,"exchange",forbidden)
    bad=list(command);bad[bad.index("--instance-id")+1]=str(uuid4())
    code,raw,_=_call(bad)
    assert code==cli.REFUSED and json.loads(raw)["diagnostic_code"]=="selection_not_unique"
    changed=project.revise(expected_revision=project.revision_id,metadata={"concurrent":True})
    store.commit(changed,expected_revision=project.revision_id)
    code,raw,_=_call(command)
    assert code==cli.REFUSED and json.loads(raw)["diagnostic_code"]=="store_conflict"


def test_wrong_document_stops_before_reservation_and_execute(tmp_path,monkeypatch):
    import kir.standalone_publish as publisher
    store,_,_,_,command,_=setup(tmp_path)
    calls=[]
    monkeypatch.setattr(publisher,"exchange",wire_exchange(store,calls,document="other-document"))
    before=store.path.read_bytes()
    code,raw,error=_call(command)
    assert code==cli.REFUSED and json.loads(raw)["diagnostic_code"]=="unexpected_document"
    assert calls==["context"] and store.path.read_bytes()==before
    assert SECRET not in raw+error


def test_lost_response_status_then_lookup_cannot_hide_resend(tmp_path,monkeypatch):
    import kir.standalone_publish as publisher
    store,_,declaration,flags,command,operation=setup(tmp_path)
    calls=[]
    monkeypatch.setattr(publisher,"exchange",wire_exchange(store,calls,lost=True))
    code,raw,error=_call(command)
    assert code==cli.NOT_DONE and json.loads(raw)["delivery"]=="unknown"
    assert calls==["context","ping","execute"] and SECRET not in raw+error
    code,status,error=_fresh(["project","create-status",str(store.path),"--journal-id",declaration["target"]["journal_id"],"--operation-id",operation])
    assert code==cli.ANSWERED,error
    retained=json.loads(status)
    assert retained["native_request"]=="none" and retained["receipt_count"]==0
    monkeypatch.setattr(publisher,"exchange",wire_exchange(store,calls))
    code,_,_=_call(command)
    assert code!=0 and calls.count("execute")==1
    lookup=["project","create-receipt",str(store.path),*flags,"--archive",retained["archive_digest"]]
    code,raw,error=_call(lookup)
    assert code==cli.ANSWERED,error
    assert json.loads(raw)["native_request"]=="lookup_only" and calls[-1]=="receipt" and calls.count("execute")==1
    assert SECRET not in raw+error


def test_selected_body_lookup_does_not_require_or_derive_unselected_body(tmp_path,monkeypatch):
    from kir.tests.test_selected_project_submission import body_source
    from kir import project_publication_cli as adapter
    source,body,other=body_source()
    source=replace(source,parent_revision=None)
    store=ProjectStore.create(tmp_path/"bodies.sqlite",source,schema=CREATE_STORE_SCHEMA,assets=[body,other])
    parser=cli.build_parser()
    _,_,_,_,command,_=setup(tmp_path/"cli")
    command[2]=str(store.path);command[command.index("--instance")+1]="body"
    args=parser.parse_args(command)
    actual=ProjectStore.get_asset
    requested=[]
    def selected_asset(self,digest):
        requested.append(digest)
        assert digest!=other.digest,"unselected body asset read"
        return actual(self,digest)
    monkeypatch.setattr(ProjectStore,"get_asset",selected_asset)
    materialized=adapter._selection_materialization(store,source,args)
    assert requested==[body.digest] and materialized.selection.output_ids==(body.op_id,)
    assert materialized.project.revision_id==source.revision_id


@pytest.mark.parametrize("bulk,per_op", [(False,False),(True,False),(False,True),(True,True)])
def test_budget_and_isolation_flags_have_independent_compiled_semantics(tmp_path,monkeypatch,bulk,per_op):
    import kir.standalone_publish as publisher
    store,_,declaration,_,command,operation=setup(tmp_path)
    calls=[]
    monkeypatch.setattr(publisher,"exchange",wire_exchange(store,calls))
    flags=(["--bulk"] if bulk else [])+(["--isolation","per_op"] if per_op else [])
    code,raw,error=_call([*command,*flags])
    assert code==cli.ANSWERED,error+raw
    record=store.find_create_publication(journal_id=declaration["target"]["journal_id"],operation_id=operation).record
    assert record.to_dict()["plan_evidence"]["bulk"] is bulk
    assert ("new SubTransaction(doc)" in record.to_dict()["source"]) is per_op


@pytest.mark.parametrize("isolation", ["atomic","per_op"])
def test_actual_2021_compiler_refusal_is_localized_without_native_effects(tmp_path,monkeypatch,isolation):
    import kir.standalone_publish as publisher
    from kir.project import ModuleInstance, output_id
    from kir.project_store import StoreNotFound
    store,project,declaration,_,command,operation=setup(tmp_path)
    floor={"op":"create_floor", "outline":[[0,0],[5000,0],[5000,5000],[0,5000]],
        "holes":[[[1000,1000],[2000,1000],[2000,2000],[1000,2000]]],
        "level":{"by":"ref","value":output_id(project.project_id,"datums","level")},
        "type":{"by":"element_id","value":400}}
    candidate=project.replace_instance(ModuleInstance("section","m",{"floor":floor}),expected_revision=project.revision_id)
    store.commit(candidate,expected_revision=project.revision_id)
    command[command.index("--expected")+1]=candidate.revision_id
    command[command.index("--revit-version")+1]="2021"
    declaration["target"]["revit_version"]="2021"
    directory=command[command.index("--directory")+1]
    from pathlib import Path
    path=Path(directory)/declaration["target"]["instance_id"]/(declaration["session_id"]+".json")
    path.write_text(json.dumps(declaration),encoding="utf-8")
    calls=[]
    monkeypatch.setattr(publisher,"exchange",wire_exchange(store,calls))
    before=store.path.read_bytes()
    code,raw,error=_call([*command,"--isolation",isolation])
    data=json.loads(raw)
    assert code==cli.REFUSED and data["diagnostic_code"]=="compile_refused"
    # This emitter supplies op_id, but no op_index. The CLI must not invent an
    # index or leak the op_id outside its narrowly approved whitelist.
    assert data["compiler_diagnostics"]==[{"code":"KIR-E003","stage":"local_compile"}]
    assert data["diagnostics_truncated"] is False
    assert calls==["context"] and store.path.read_bytes()==before
    assert SECRET not in raw+error and error==""
    with pytest.raises(StoreNotFound):
        store.find_create_publication(journal_id=declaration["target"]["journal_id"],operation_id=operation)


def inject_preparation_error(tmp_path,monkeypatch,diagnostics):
    import kir.standalone_publish as publisher
    from kir.revit_connector import ConnectorPreparationError
    store,_,_,_,command,_=setup(tmp_path)
    def reject(*args,**kwargs):
        raise ConnectorPreparationError("compile_refused",SECRET,diagnostics=diagnostics)
    monkeypatch.setattr(publisher,"publish_stored_project",reject)
    before=store.path.read_bytes()
    code,raw,error=_call(command)
    assert code==cli.REFUSED and SECRET not in raw+error and error==""
    assert store.path.read_bytes()==before
    return json.loads(raw)


def test_diagnostic_whitelist_never_serializes_free_form_fields(tmp_path,monkeypatch):
    from kir.diag import Diagnostic
    diagnostic=Diagnostic("KIR-E003",SECRET,op_index=0,op_id=SECRET,field_name=SECRET,
        expected=SECRET,got=SECRET,candidates=[SECRET],suggested_replacement=SECRET,incident_id=SECRET)
    data=inject_preparation_error(tmp_path,monkeypatch,[diagnostic])
    assert data["compiler_diagnostics"]==[{"code":"KIR-E003","stage":"local_compile","compiled_op_index":0}]
    assert data["diagnostics_truncated"] is False


def test_diagnostic_list_has_hard_twenty_row_boundary(tmp_path,monkeypatch):
    from kir.diag import Diagnostic
    data=inject_preparation_error(tmp_path,monkeypatch,[Diagnostic("KIR-E003",SECRET,op_index=i) for i in range(25)])
    assert len(data["compiler_diagnostics"])==20 and data["diagnostics_truncated"] is True
    assert [row["compiled_op_index"] for row in data["compiler_diagnostics"]]==list(range(20))


@pytest.mark.parametrize("bad", [True,-1,1.5,"private-index",10**10000], ids=["bool","negative","float","text","huge-integer"])
def test_malformed_or_nonrepresentable_index_is_not_echoed(tmp_path,monkeypatch,bad):
    from kir.diag import Diagnostic
    data=inject_preparation_error(tmp_path,monkeypatch,[Diagnostic("KIR-E003",SECRET,op_index=bad)])
    assert data["compiler_diagnostics"]==[{"code":"KIR-E003","stage":"local_compile"}]


def test_unregistered_and_non_diagnostic_objects_are_withheld(tmp_path,monkeypatch):
    from kir.diag import Diagnostic
    class Hostile:
        def __str__(self): raise AssertionError("arbitrary diagnostic stringified")
    diagnostic=Diagnostic("KIR-E003",SECRET)
    diagnostic.code=SECRET
    data=inject_preparation_error(tmp_path,monkeypatch,[Hostile(),{"code":SECRET},diagnostic])
    assert data["compiler_diagnostics"]==[] and data["diagnostics_truncated"] is True


def test_native_exception_diagnostic_attribute_is_never_forwarded(tmp_path,monkeypatch):
    import kir.standalone_publish as publisher
    from kir.diag import Diagnostic
    store,_,_,_,command,_=setup(tmp_path)
    def reject(*args,**kwargs):
        error=OSError(SECRET)
        error.diagnostics=(Diagnostic("KIR-E003",SECRET,op_index=0),)
        raise error
    monkeypatch.setattr(publisher,"publish_stored_project",reject)
    before=store.path.read_bytes()
    code,raw,error=_call(command)
    data=json.loads(raw)
    assert code==cli.NOT_DONE and data["diagnostic_code"]=="publication_unavailable"
    assert "compiler_diagnostics" not in data and SECRET not in raw+error
    assert store.path.read_bytes()==before
