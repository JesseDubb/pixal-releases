"""Failure-case coverage: synthetic assets and owned temporary processes only."""
import copy
import hashlib
import io
import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "install"))
import pixal_install as pi


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    previous = copy.deepcopy(pi.STATE)
    monkeypatch.setattr(pi, "PIXAL", tmp_path)
    monkeypatch.setattr(pi, "HERE", tmp_path / "install")
    monkeypatch.setattr(pi, "WORK", tmp_path / "work")
    monkeypatch.setattr(pi, "log", lambda message: None)
    pi.CANCEL.clear()
    yield
    pi.CANCEL.clear()
    pi.STATE.clear()
    pi.STATE.update(previous)


@pytest.mark.parametrize("payload", [b'{"secret":"test-only",', b'[]', b'\xff'])
def test_bad_config_is_preserved(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_bytes(payload)
    with pytest.raises(RuntimeError, match="preserved"):
        pi.write_config({"setup_done": True})
    assert path.read_bytes() == payload


def test_config_merge_preserves_credentials_and_extensions(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"api_key": "test-only", "custom": 3},
                               "extension": {"x": 1}}), encoding="utf-8-sig")
    result = pi.write_config({"llm": {"model": "local"}})
    assert result["llm"] == {"api_key": "test-only", "custom": 3, "model": "local"}
    assert result["extension"] == {"x": 1}
    assert json.loads(path.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("boundary", ["replace", "fsync"])
def test_failed_atomic_write_preserves_original(tmp_path, boundary):
    path = tmp_path / "config.json"
    path.write_bytes(b'{"original":true}')
    with mock.patch.object(pi.os, boundary, side_effect=PermissionError("injected")):
        with pytest.raises(PermissionError):
            pi.write_config({"setup_done": True})
    assert path.read_bytes() == b'{"original":true}'
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("version,bits,expected", [((3, 10), 64, False),
    ((3, 11), 64, False), ((3, 12), 32, False), ((3, 12), 64, True),
    ((3, 13), 64, True), ((3, 14), 64, False)])
def test_runtime_probe_contract(version, bits, expected, monkeypatch):
    def fake_run(cmd, timeout):
        # Execute the actual probe under synthetic sys/struct modules.
        import types
        fake_sys = types.SimpleNamespace(version_info=version)
        fake_struct = types.SimpleNamespace(calcsize=lambda _: bits // 8)
        with mock.patch.dict(sys.modules, sys=fake_sys, struct=fake_struct):
            try:
                exec(cmd[2], {})
            except AssertionError:
                return 1, ""
        return 0, ""
    monkeypatch.setattr(pi, "run_out", fake_run)
    assert pi.compatible_python("candidate.exe") is expected


def test_old_venv_preserved_and_private_runtime_selected(tmp_path, monkeypatch):
    old = tmp_path / ".venv" / "Scripts" / "python.exe"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old environment")
    bundled = tmp_path / "install" / "runtime" / "python.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"private runtime")
    monkeypatch.setattr(pi, "compatible_python", lambda p, **k: Path(p) == bundled)
    monkeypatch.setattr(pi, "system_python", lambda: None)
    assert pi.choose_python(tmp_path / "ComfyUI") == (bundled, "bundled")
    assert not old.exists()
    assert list(tmp_path.glob(".venv.backup-*/Scripts/python.exe"))[0].read_bytes() == b"old environment"


def test_unknown_runtime_refused_before_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "system_python", lambda: None)
    with pytest.raises(RuntimeError, match="3.12"):
        pi.runtime_preflight(tmp_path)


def test_prerequisite_closure_in_actual_plan(tmp_path):
    lanes, _, _, _ = pi.build_plan({"lanes": ["anima_turbo"],
                                  "comfy": {"mode": "install", "path": str(tmp_path)}})
    assert {l["id"] for l in lanes} == {"anima", "anima_turbo"}
    assert len(list(pi.pending_files(lanes, set()))) == 4


def test_unknown_and_cyclic_components_rejected(monkeypatch):
    with pytest.raises(ValueError, match="Unknown"):
        pi.resolve_lanes(["not-a-lane"])
    monkeypatch.setattr(pi, "CATALOG", {"lanes": [
        {"id": "a", "requires": ["b"]}, {"id": "b", "requires": ["a"]}]})
    with pytest.raises(ValueError, match="Cyclic"):
        pi.resolve_lanes(["a"])


def test_external_model_identity_preserves_subfolder_and_case(tmp_path):
    model = tmp_path / "SharedModels" / "diffusion_models" / "Edits" / "Model-Q4.gguf"
    value = pi.model_config_value({"at": "diffusion_models/edits/model-q4.gguf", "full": str(model)})
    assert value == str(Path("Edits") / "Model-Q4.gguf")


class Response(io.BytesIO):
    def __init__(self, payload, status=200, **headers):
        super().__init__(payload)
        self.status = status
        self.headers = headers


def test_short_body_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "urlopen", lambda *a, **k: Response(b"x" * 9995, **{"Content-Length": "10000"}))
    monkeypatch.setattr(pi.time, "sleep", lambda _: None)
    dest = tmp_path / "model.safetensors"
    with pytest.raises(RuntimeError, match="gave up"):
        pi.download("https://fixture.invalid/file", dest, 10000)
    assert not dest.exists()


def test_complete_partial_verified_without_http(tmp_path, monkeypatch):
    dest = tmp_path / "model.bin"
    dest.with_suffix(".bin.part").write_bytes(b"complete")
    monkeypatch.setattr(pi, "urlopen", mock.Mock(side_effect=AssertionError("no request")))
    digest = hashlib.sha256(b"complete").hexdigest()
    assert pi.download("unused", dest, 8, sha256=digest).read_bytes() == b"complete"


def test_bad_hash_restarts_and_repairs_same_size_file(tmp_path, monkeypatch):
    dest = tmp_path / "model.bin"
    dest.write_bytes(b"bad!")
    dest.with_suffix(".bin.part").write_bytes(b"bad!")
    monkeypatch.setattr(pi, "urlopen", lambda *a, **k: Response(b"good", **{"Content-Length": "4"}))
    pi.download("https://fixture.invalid/file", dest, 4, sha256=hashlib.sha256(b"good").hexdigest())
    assert dest.read_bytes() == b"good"


@pytest.mark.parametrize("content_range", ["", "bytes 1-3/4", "bytes 2-2/4", "bytes 2-3/5"])
def test_bad_resume_range_never_appends(tmp_path, monkeypatch, content_range):
    part = tmp_path / "model.part"
    part.write_bytes(b"ab")
    monkeypatch.setattr(pi, "urlopen", lambda *a, **k: Response(b"cd", 206,
        **{"Content-Length": "2", "Content-Range": content_range}))
    with pytest.raises(IOError):
        pi._stream("https://fixture.invalid/file", part, 2, 4, None, "")
    assert part.read_bytes() == b"ab"


@pytest.mark.parametrize("status", [200, 206])
def test_valid_resume_or_ignored_range(tmp_path, monkeypatch, status):
    part = tmp_path / "model.part"
    part.write_bytes(b"ab")
    body = b"abcd" if status == 200 else b"cd"
    monkeypatch.setattr(pi, "urlopen", lambda *a, **k: Response(body, status,
        **{"Content-Length": str(len(body)), "Content-Range": "bytes 2-3/4"}))
    pi._stream("https://fixture.invalid/file", part, 2, 4, None, "")
    assert part.read_bytes() == b"abcd"


def test_existing_pack_retries_failed_requirements_without_deleting_files(tmp_path, monkeypatch):
    name = next(iter(pi.CATALOG["packs"]))
    target = tmp_path / "custom_nodes" / name
    target.mkdir(parents=True)
    (target / "requirements.txt").write_text("test-dependency")
    (target / "user-edit.py").write_text("preserve me")
    install = mock.Mock(side_effect=[RuntimeError("pip failed"), None])
    monkeypatch.setattr(pi, "pip", install)
    with pytest.raises(RuntimeError, match="pip failed"):
        pi.install_pack(name, tmp_path, "engine-python", None)
    pi.install_pack(name, tmp_path, "engine-python", None)
    assert install.call_count == 2
    assert (target / "user-edit.py").read_text() == "preserve me"


def fake_extract(archive, stage, sid):
    (stage / "ComfyUI").mkdir(parents=True, exist_ok=True)
    (stage / "ComfyUI" / "main.py").write_text("# synthetic engine")
    (stage / "python_embeded").mkdir(exist_ok=True)
    (stage / "python_embeded" / "python.exe").write_bytes(b"synthetic runtime")


def test_interrupted_extraction_can_retry(tmp_path, monkeypatch):
    root = tmp_path / "portable"
    def interrupted(archive, stage, sid):
        (stage / "ComfyUI" / "models").mkdir(parents=True)
        raise pi.Cancelled()
    monkeypatch.setattr(pi, "extract_7z", interrupted)
    with pytest.raises(pi.Cancelled):
        pi.install_portable(Path("fixture.7z"), root, None)
    assert pi.portable_receipt(root)
    monkeypatch.setattr(pi, "extract_7z", fake_extract)
    assert pi.install_portable(Path("fixture.7z"), root, None) == root.resolve()
    assert pi.portable_receipt(root) is None
    assert (root / "ComfyUI" / "main.py").exists()


def test_interrupted_publication_can_retry(tmp_path, monkeypatch):
    root = tmp_path / "portable"
    monkeypatch.setattr(pi, "extract_7z", fake_extract)
    rename = Path.rename
    count = 0
    def fail_second(source, target):
        nonlocal count
        count += 1
        if count == 2:
            raise PermissionError("locked fixture")
        return rename(source, target)
    with mock.patch.object(Path, "rename", fail_second):
        with pytest.raises(PermissionError):
            pi.install_portable(Path("fixture.7z"), root, None)
    pi.install_portable(Path("fixture.7z"), root, None)
    assert (root / "ComfyUI" / "main.py").exists()
    assert (root / "python_embeded" / "python.exe").exists()


def test_existing_comfy_is_never_paved(tmp_path):
    (tmp_path / "ComfyUI" / "models").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Refusing"):
        pi.install_portable(Path("unused"), tmp_path, None)
    assert not (tmp_path / ".pixal-portable-install.json").exists()


def test_cancel_silent_owned_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            creationflags=pi.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    timer = threading.Timer(0.1, pi.CANCEL.set)
    timer.start()
    try:
        with pytest.raises(pi.Cancelled):
            list(pi.process_lines(proc))
        assert proc.poll() is not None
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


@pytest.mark.parametrize("phase,expected", [("done", 0), ("error", 1), ("running", 1)])
def test_unicode_headless_handoff_and_terminal_status(tmp_path, monkeypatch, phase, expected):
    choices = tmp_path / "choices.json"
    choices.write_text(json.dumps({"home": "C:/Jos\u00e9/\u753b\u50cf space"}, ensure_ascii=False), encoding="utf-8")
    seen = []
    def worker(value):
        seen.append(value)
        with pi.LOCK:
            pi.STATE["phase"] = phase
    monkeypatch.setattr(pi, "worker", worker)
    monkeypatch.setattr(pi, "ui_watchdog", lambda **k: None)
    progress = tmp_path / "progress.txt"
    assert pi.headless(choices, progress) == expected
    assert seen[0]["home"] == "C:/Jos\u00e9/\u753b\u50cf space"
    assert f"phase={phase}" in progress.read_text(encoding="utf-8-sig")
    assert not progress.with_suffix(".tmp").exists()


def test_native_wizard_requires_exit_and_done():
    script = (Path(__file__).resolve().parents[1] / "install" / "pixal.iss").read_text(encoding="utf-8")
    assert "Utf8Encode(Json)" in script
    assert "ewWaitUntilTerminated, Code, @EngineOutput" in script
    assert "EngineOK := (Code = 0) and (Phase = 'done')" in script
    assert "Check: EngineSucceeded" in script
    assert "Setup needs attention" in script


def test_truncated_existing_catalog_file_is_not_surveyed_as_installed(tmp_path):
    entry = pi.CATALOG["lanes"][0]["files"][0]
    target = tmp_path / "models" / entry["dest"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"truncated fixture")
    row = pi.survey(tmp_path)["lanes"][pi.CATALOG["lanes"][0]["id"]]["files"][0]
    assert row["state"] == "missing"


def test_private_embedded_runtime_can_import_application_modules(tmp_path, monkeypatch):
    import os
    import shutil
    import zipfile
    archive = Path(__file__).resolve().parents[1] / "install/_build/python-3.12.10-embed-amd64.zip"
    if sys.platform != "win32" or not archive.is_file():
        pytest.skip("Windows embedded-runtime cache not available")
    app = tmp_path / "Jos\u00e9 \u753b\u50cf"
    monkeypatch.setattr(pi, "PIXAL", app)
    runtime = app / "install" / "runtime"
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as payload:
        payload.extractall(runtime)
    (app / "pixal_fixture_module.py").write_text("VALUE = 42\n")
    monkeypatch.setattr(pi, "system_python", lambda: None)
    executable, kind = pi.choose_python(tmp_path / "ComfyUI")
    assert kind == "bundled"
    rc, out = pi.run_out([str(executable), "-c", "import pixal_fixture_module;print(pixal_fixture_module.VALUE)"])
    assert rc == 0, out
    assert out.strip() == "42"
    pi.write_python_choice(executable)
    assert (app / ".pixal_python").read_text().strip() == str(Path("install/runtime/python.exe"))
    shutil.copy2(Path(__file__).resolve().parents[1] / "run.bat", app / "run.bat")
    (app / "server.py").write_text("import pixal_fixture_module;print(pixal_fixture_module.VALUE)\n")
    environment = dict(os.environ)
    environment.pop("PIXAL_PYTHON", None)
    result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(app / "run.bat")],
                            cwd=tmp_path, env=environment, capture_output=True, text=True,
                            creationflags=pi.CREATE_NO_WINDOW, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"


def test_subprocess_deadline_reaps_silent_child():
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            creationflags=pi.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        with pytest.raises(TimeoutError):
            list(pi.process_lines(proc, timeout=0.1))
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def test_config_failure_prevents_worker_downloads(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_bytes(b"broken settings")
    download = mock.Mock()
    monkeypatch.setattr(pi, "download", download)
    pi.worker({"lanes": [], "home": str(tmp_path),
               "comfy": {"mode": "install", "path": str(tmp_path / "Comfy")}})
    assert pi.STATE["phase"] == "error"
    download.assert_not_called()


def test_disk_check_charges_absolute_model_destination(tmp_path, monkeypatch):
    # On POSIX the existing directory acts as the volume key; on Windows use
    # free_bytes' probe argument to ensure the external destination is inspected.
    primary, shared = tmp_path / "primary", tmp_path / "shared"
    primary.mkdir()
    shared.mkdir()
    seen = []
    monkeypatch.setattr(pi, "free_bytes", lambda p: seen.append(Path(p)) or 100 * (1 << 30))
    monkeypatch.setattr(pi, "pending_files", lambda *a: iter([({"bytes": 1000}, str(shared / "mmproj.gguf"))]))
    pi.disk_preflight({"home": str(shared), "comfy": {"mode": "use", "path": str(primary)}}, [], set())
    assert shared in seen


def test_generated_components_resolve_dependencies_and_do_not_charge_models_to_app(tmp_path, monkeypatch):
    import build_installer as build
    monkeypatch.setattr(build, "BUILD", tmp_path)
    build.gen_components()
    script = (tmp_path / "components.iss").read_text(encoding="utf-8")
    assert "ResolveLaneSelection" in script
    assert "anima_turbo" in script and "Selection + ',anima'" in script
    assert "ExtraDiskSpaceRequired" not in script
