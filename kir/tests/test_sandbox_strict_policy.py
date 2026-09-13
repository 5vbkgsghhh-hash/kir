"""Strict sandbox policy/input controls; benign scripts and no network probes.

Child fault injection affects only the child process, before author execution.
All temporary directories belong to pytest's explicitly selected .work basetemp.
"""
from dataclasses import fields, replace
import json
import os
import errno
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from kir import sandbox


SOURCE = "ops = [{'op': 'create_level', 'id': 'level', 'elev_mm': 0}]\n"
REPO = str(Path(__file__).resolve().parents[2])


def safe_policy(**changes):
    return replace(sandbox.SandboxPolicy(dsl_module="kir.dsl", probe_network=False), **changes)


@pytest.mark.parametrize("name,value", [
    ("network", "requred"), ("network", "REQUIRED"), ("network", None),
    ("cpu_seconds", 0), ("cpu_seconds", -1), ("cpu_seconds", True), ("cpu_seconds", float("nan")),
    ("wall_seconds", float("inf")), ("wall_seconds", "5"), ("wall_seconds", False),
    ("memory_mb", 0), ("memory_mb", 1.5), ("max_ops", 0), ("max_ops", True),
    ("max_result_bytes", -1), ("max_source_bytes", 0), ("max_stdout_chars", False),
    ("recursion_limit", 0), ("nofile", 0), ("memory_mb", 2**100),
    ("filesystem_isolation", "false"), ("probe_network", 1), ("replay_check", "yes"),
    ("allowed_imports", ["math"]), ("allowed_imports", ("math", 1)),
    ("allowed_imports", ("../os",)), ("dsl_module", ""), ("dsl_module", None),
    ("extra_sys_path", "directory"), ("extra_sys_path", ("bad\0path",)), ("python_exe", None),
])
def test_invalid_policy_refuses_before_child_allocation(name, value, monkeypatch):
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid policy spawned a child"))
    with pytest.raises(ValueError):
        sandbox.SandboxPolicy(**{name: value})


def test_policy_dataclass_has_an_explicit_roundtrippable_field_set():
    original = safe_policy()
    names = {item.name for item in fields(sandbox.SandboxPolicy)}
    assert names == {"cpu_seconds", "wall_seconds", "memory_mb", "max_ops", "max_result_bytes", "max_source_bytes",
        "max_stdout_chars", "recursion_limit", "nofile", "allowed_imports", "network", "filesystem_isolation",
        "probe_network", "replay_check", "dsl_module", "extra_sys_path", "python_exe"}
    values = {name: getattr(original, name) for name in names}
    assert sandbox.SandboxPolicy(**values) == original
    for mode in ("required", "best_effort", "off"):
        assert replace(original, network=mode).network == mode


def test_tampered_policy_is_rechecked_at_public_entry(monkeypatch):
    policy = safe_policy()
    object.__setattr__(policy, "network", "requred")
    monkeypatch.setattr(sandbox.os, "pipe", lambda: pytest.fail("invalid policy allocated descriptors"))
    result = sandbox.execute_author_script(SOURCE, policy=policy)
    assert not result.ok and result.refusal.kind == "InvalidPolicy"


@pytest.mark.parametrize("source", [None, b"ops=[]", 1, "\ud800"])
def test_bad_source_returns_refusal_not_host_exception(source, monkeypatch):
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid source spawned a child"))
    result = sandbox.execute_author_script(source, policy=safe_policy())
    assert not result.ok and result.refusal.blame == "caller"


@pytest.mark.parametrize("field,value", [
    ("params", []), ("params", "height=10"), ("params", {"height": float("nan")}),
    ("params", {"height": float("inf")}), ("params", {1: "wrong key"}),
    ("building", []), ("model", "not a catalog"), ("params", {"value": "\ud800"}),
])
def test_invalid_inputs_never_silently_become_defaults_or_strings(field, value, monkeypatch):
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid input spawned a child"))
    result = sandbox.execute_author_script(SOURCE, policy=safe_policy(), **{field: value})
    assert not result.ok and result.refusal.kind == "InvalidInput"
    assert result.refusal.detail["input"] == field


def test_cyclic_and_arbitrary_object_inputs_do_not_escape_or_call_str(monkeypatch):
    class NotJSON:
        def __str__(self):
            pytest.fail("arbitrary input was coerced with str")
    cyclic = {}
    cyclic["self"] = cyclic
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *a, **k: pytest.fail("invalid input spawned a child"))
    for value in (cyclic, {"value": NotJSON()}):
        result = sandbox.execute_author_script(SOURCE, policy=safe_policy(), params=value)
        assert not result.ok and result.refusal.kind == "InvalidInput"


def test_setup_failure_returns_typed_refusal_and_closes_allocated_descriptors(monkeypatch):
    actual_pipe, allocated = os.pipe, []
    def pipe():
        pair = actual_pipe()
        allocated.extend(pair)
        return pair
    monkeypatch.setattr(sandbox.os, "pipe", pipe)
    monkeypatch.setattr(sandbox.tempfile, "mkdtemp", lambda **_: (_ for _ in ()).throw(OSError("fixture failure")))
    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *a, **k: pytest.fail("setup failure spawned a child"))
    result = sandbox.execute_author_script(SOURCE, policy=safe_policy())
    assert not result.ok and result.refusal.kind == "HostFailure"
    assert len(allocated) == 2
    for descriptor in allocated:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_post_spawn_setup_failure_cleans_up_the_waiting_child(monkeypatch):
    actual_popen, children = subprocess.Popen, []
    def popen(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(sandbox.subprocess, "Popen", popen)
    monkeypatch.setattr(sandbox.threading.Thread, "start", lambda _: (_ for _ in ()).throw(RuntimeError("reader setup failed")))
    result = sandbox.execute_author_script(SOURCE, policy=safe_policy())
    assert not result.ok and result.refusal.kind == "HostFailure"
    assert len(children) == 1 and children[0].poll() is not None


def injected_child(tmp_path, mode):
    policy = safe_policy()
    jail = tmp_path / "empty-jail"
    jail.mkdir()
    read_fd, write_fd = os.pipe()
    env = {"PYTHONPATH": REPO, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "KIR_SANDBOX_RESULT_FD": str(write_fd), "KIR_SANDBOX_JAIL": str(jail),
        "KIR_SANDBOX_CFG": json.dumps(policy.child_config()), "LC_ALL": "C.UTF-8", "PATH": ""}
    code = """
import os, resource, sys
import threading, warnings
import kir.sandbox as sandbox
def no_probe():
    raise AssertionError('test must not make a network probe')
sandbox._probe_network = no_probe
if sys.argv[1] == 'chroot':
    def failed_chroot(path):
        raise PermissionError('injected chroot refusal')
    os.chroot = failed_chroot
elif sys.argv[1].startswith('RLIMIT_'):
    original = resource.setrlimit
    selected = getattr(resource, sys.argv[1])
    def failed_limit(name, value):
        if name == selected:
            raise OSError('injected rlimit refusal')
        return original(name, value)
    resource.setrlimit = failed_limit
elif sys.argv[1] == 'missing_process_library':
    def missing_library():
        raise OSError('injected unavailable libseccomp')
    sandbox._load_process_creation_guard = missing_library
elif sys.argv[1] == 'failed_process_filter':
    def failed_filter(library):
        raise RuntimeError('injected filter installation failure')
    sandbox._install_process_creation_guard = failed_filter
elif sys.argv[1] == 'fork_control':
    actual_install = sandbox._install_process_creation_guard
    warnings.simplefilter('ignore', DeprecationWarning)
    def attempt_fork():
        try:
            child = os.fork()
        except OSError as error:
            return {'result': 'refused', 'errno': error.errno}
        if child == 0:
            os._exit(0)
        waited, status = os.waitpid(child, 0)
        return {'result': 'created', 'reaped': waited == child, 'status': status}
    def checked_install(library):
        # Trusted bounded control, not authored code or a builtins escape.
        # The single counterfactual child exits immediately and is reaped.
        control = {'nproc': resource.getrlimit(resource.RLIMIT_NPROC), 'before': attempt_fork()}
        ready, proceed = threading.Event(), threading.Event()
        def preexisting_worker():
            ready.set()
            if not proceed.wait(5):
                return
            control['preexisting_thread_fork'] = attempt_fork()
        worker = threading.Thread(target=preexisting_worker)
        worker.start()
        if not ready.wait(5):
            raise RuntimeError('preexisting test worker did not start')
        try:
            facts = actual_install(library)
        finally:
            proceed.set()
            worker.join(5)
        if worker.is_alive():
            raise RuntimeError('preexisting test worker did not stop')
        control['after'] = attempt_fork()
        thread = threading.Thread(target=lambda: None)
        try:
            thread.start()
        except RuntimeError:
            control['new_thread'] = 'refused'
        else:
            thread.join(5)
            control['new_thread'] = 'created'
        facts['test_control'] = control
        return facts
    sandbox._install_process_creation_guard = checked_install
sandbox._child_main()
"""
    frame = sandbox.FRAME_MARKER + b"\n0\n0\n0\n" + ("print('AUTHOR_EXECUTED')\n" + SOURCE).encode()
    try:
        completed = subprocess.run([sys.executable, "-B", "-c", code, mode], env=env, cwd=REPO,
            input=frame, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(write_fd,), timeout=15)
        os.close(write_fd)
        write_fd = -1
        chunks = []
        while chunk := os.read(read_fd, 65536):
            chunks.append(chunk)
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        return json.loads(b"".join(chunks))
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.parametrize("mode", ["chroot", "RLIMIT_FSIZE", "RLIMIT_CORE", "RLIMIT_NPROC",
                                  "RLIMIT_NOFILE", "RLIMIT_AS", "RLIMIT_CPU"])
def test_requested_isolation_and_each_resource_limit_must_precede_author_exec(tmp_path, mode):
    result = injected_child(tmp_path, mode)
    assert result["ok"] is False
    assert result["refusal"]["kind"] == ("FilesystemIsolationUnavailable" if mode == "chroot" else "ResourceLimitUnavailable")
    assert "AUTHOR_EXECUTED" not in result.get("stdout", "")
    assert result["isolation"]["namespaces"] == "user+mount+net"
    assert result["isolation"]["network_probe"] == "not probed"


@pytest.mark.parametrize("mode", ["missing_process_library", "failed_process_filter"])
def test_unavailable_process_creation_guard_stops_before_author(tmp_path, mode):
    result = injected_child(tmp_path, mode)
    assert result["ok"] is False and result["refusal"]["kind"] == "ProcessCreationGuardUnavailable"
    assert result["isolation"]["process_creation"]["state"] == "unavailable"
    assert "AUTHOR_EXECUTED" not in result.get("stdout", "")


def test_process_guard_blocks_root_exempt_fork_and_preexisting_threads(tmp_path):
    if os.getuid() != 0:
        pytest.skip("the counterfactual root RLIMIT_NPROC exemption requires a root-started test process")
    result = injected_child(tmp_path, "fork_control")
    assert result["ok"] is True, result
    facts = result["isolation"]["process_creation"]
    assert facts["state"] == "denied" and facts["mechanism"] == "libseccomp"
    assert facts["syscalls"] == ["fork", "vfork", "clone", "clone3"]
    assert facts["thread_synchronization"] and facts["no_new_privileges"]
    control = facts["test_control"]
    assert control["nproc"] == [0, 0]
    assert control["before"] == {"result": "created", "reaped": True, "status": 0}
    assert control["after"] == {"result": "refused", "errno": errno.EAGAIN}
    assert control["preexisting_thread_fork"] == {"result": "refused", "errno": errno.EAGAIN}
    assert control["new_thread"] == "refused"
    assert "AUTHOR_EXECUTED" in result["stdout"]


@pytest.mark.parametrize("failure", ["init", "nnp", "tsync", "resolve", "rule", "load"])
def test_no_partial_or_unsupported_filter_is_reported_as_applied(failure):
    class FakeLibrary:
        released = False
        resolved = []

        def seccomp_init(self, action):
            assert action == sandbox._SCMP_ACT_ALLOW
            return None if failure == "init" else 1

        def seccomp_attr_set(self, context, attribute, value):
            assert context == 1 and value == 1
            return -1 if ((failure == "nnp" and attribute == sandbox._SCMP_FLTATR_CTL_NNP)
                          or (failure == "tsync" and attribute == sandbox._SCMP_FLTATR_CTL_TSYNC)) else 0

        def seccomp_syscall_resolve_name(self, name):
            self.resolved.append(name)
            return -1 if failure == "resolve" else 999  # Fake library token, not a real syscall.

        def seccomp_rule_add_array(self, context, action, number, count, arguments):
            assert context == 1 and action == sandbox._SCMP_ACT_ERRNO | errno.EAGAIN
            assert number == 999 and count == 0 and arguments is None
            return -1 if failure == "rule" else 0

        def seccomp_load(self, context):
            assert context == 1 and self.resolved == [b"fork", b"vfork", b"clone", b"clone3"]
            return -1

        def seccomp_release(self, context):
            assert context == 1
            self.released = True

    library = FakeLibrary()
    with pytest.raises(RuntimeError):
        sandbox._install_process_creation_guard(library)
    assert library.released is (failure != "init")


def test_required_isolation_keeps_full_program_and_exact_normalized_input_digests():
    source = """
height = param('height', 1)
result = {'intent': 'preserve envelope', 'defaults': {'level': {'by': 'element_id', 'value': 1}},
          'ops': [{'op': 'create_level', 'id': 'l', 'elev_mm': height}]}
"""
    result = sandbox.execute_author_script(source, policy=safe_policy(), params={"height": 3800},
        model={"levels": [{"id": 1, "name": "Level", "point": (1, 2)}]}, building={"elements": []})
    assert result.ok, result.refusal
    assert result.to_program()["defaults"] == {"level": {"by": "element_id", "value": 1}}
    assert result.to_program()["ops"][0]["elev_mm"] == 3800
    assert result.isolation["filesystem"] == "chroot" and result.isolation["namespaces"] == "user+mount+net"
    assert result.isolation["process_creation"]["state"] == "denied"
    assert result.env_digest and result.params_digest == sandbox.params_digest({"height": 3800})
    assert result.model_digest == sandbox.model_catalog_digest({"levels": [{"id": 1, "name": "Level", "point": [1, 2]}]})
    assert result.building_digest == sandbox.building_catalog_digest({"elements": []})


def test_empty_allowed_imports_does_not_restore_the_default_allowlist():
    result = sandbox.execute_author_script("import math\n" + SOURCE, policy=safe_policy(allowed_imports=()))
    assert not result.ok and result.refusal.code == sandbox.SANDBOX_FORBIDDEN_IMPORT


def test_replay_failure_preserves_all_input_signatures(monkeypatch):
    first = sandbox.SandboxResult(ok=True, ops=[{"op": "create_level", "id": "l", "elev_mm": 1}])
    second = sandbox.SandboxResult(ok=False, refusal=sandbox._refuse(sandbox.SANDBOX_RUNTIME, "fixture", kind="Fixture"))
    with patch.object(sandbox, "_run_once", side_effect=[first, second]) as run:
        result = sandbox.execute_author_script(SOURCE, policy=safe_policy(replay_check=True),
            model={"levels": []}, building={"elements": []}, params={"height": 1})
    assert run.call_count == 2 and result is second and not result.ok
    assert result.author_digest and result.params_digest and result.model_digest and result.building_digest


def test_real_replay_still_compares_two_benign_isolated_runs():
    result = sandbox.execute_author_script(SOURCE, policy=safe_policy(replay_check=True))
    assert result.ok, result.refusal
    assert result.isolation["replay_checked"] is True and result.isolation["environment_replay"] == "same"
    assert result.to_program()["ops"][0]["id"] == "level"
