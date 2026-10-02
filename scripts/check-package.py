"""Exercise the frozen helper from an arbitrary directory with only system PATH."""
import json
import hashlib
import os
import select
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

app = Path(sys.argv[1]).resolve()
helper = app / "Contents/Resources/keytrack-runtime/keytrack-helper"
with tempfile.TemporaryDirectory(prefix="keytrack-package-check-") as temporary:
    root = Path(temporary)
    home = root / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin", PYTHONHOME="/nonexistent", PYTHONPATH="/nonexistent")
    process = subprocess.Popen([str(helper), "console-native", "--demo"], cwd=root, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    def request(value, ok=True):
        process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        process.stdin.flush()
        if not select.select([process.stdout], [], [], 15)[0]:
            raise RuntimeError("Package helper did not respond")
        reply = json.loads(process.stdout.readline())
        assert reply["ok"] == ok, reply
        return reply.get("data", reply)
    try:
        state = request({"action": "state"})
        assert state["status"]["demo"]
        themes = state["appearance_themes"]
        assert len(themes) == 9
        assert {item["id"] for item in themes} == {"green", "blue", "slate", "forest", "mint", "mist", "navy", "sand", "paper"}
        assert all(item["name"] and item["description"] and item["light"] and item["dark"] for item in themes)
        assert state["prediction"]["enabled"] is False
        assert state["settings"]["gloss_language"] == "off"
        assert state["glossary"]["count"] == 120
        assert all("EN:" in item["en_comment"] and "日:" in item["ja_comment"] for item in state["glossary"]["examples"])
        assert state["prediction"]["max_candidates"] == 3
        request({"action": "prediction", "enabled": True, "max_candidates": 4})
        prediction = request({"action": "state"})
        assert prediction["prediction"]["enabled"] is True
        assert prediction["prediction"]["max_candidates"] == 4
        assert prediction["status"]["kev_enabled"] == state["status"]["kev_enabled"]
        request({"action": "prediction", "enabled": False, "max_candidates": 3})
        state = request({"action": "state"})
        original_phrases = state["phrases"]
        original_theme = state["settings"]["theme"]
        original_prediction = state["prediction"]
        original_kev = state["status"]["kev_enabled"]
        assert request({"action": "report", "day": state["today"]})["segments"] is None
        phrases = [{"code": "qpackage", "category": "测试", "text": '独立安装\n多行 "内容"'}]
        saved = request({"action": "phrases", "phrases": phrases, "revision": state["revision"]})
        state = request({"action": "state"})
        assert state["phrases"] == phrases
        preferences = dict(state["settings"], theme="mist", font_size=17, layout="vertical")
        request({"action": "settings", "settings": preferences, "revision": state["revision"]})
        state = request({"action": "state"})
        assert state["settings"]["theme"] == "mist"
        assert state["appearance_themes"] == themes
        assert state["phrases"] == phrases
        assert state["prediction"] == original_prediction
        assert state["status"]["kev_enabled"] == original_kev
        request({"action": "restore", "id": saved["backup"], "revision": state["revision"]})
        restored = request({"action": "state"})
        assert restored["phrases"] == original_phrases
        assert restored["settings"]["theme"] == original_theme
        assert restored["prediction"] == original_prediction
        assert restored["status"]["kev_enabled"] == original_kev
        discovery = request({"action": "phrase_discovery", "days": 30})
        assert discovery["revision"] == restored["revision"]
        assert discovery["candidates"]
        assert any(item["duplicate"] for item in discovery["candidates"])
        candidate = next(item for item in discovery["candidates"] if not item["duplicate"])
        rejection = request({"action": "phrase_discovery_reject", "ids": [candidate["id"]]})
        assert rejection["revision"] == restored["revision"]
        again = request({"action": "phrase_discovery", "days": 30})
        assert candidate["id"] not in {item["id"] for item in again["candidates"]}
        assert request({"action": "state"})["phrases"] == original_phrases
        request({"action": "install"}, ok=False)
        assert len(request({"action": "backups"})["backups"]) == 3
        current = request({"action": "state"})
        saved_gloss = request({"action": "settings", "settings": dict(current["settings"], gloss_language="en"), "revision": current["revision"]})
        current = request({"action": "state"})
        assert current["settings"]["gloss_language"] == "en"
        assert current["prediction"] == original_prediction
        request({"action": "settings", "settings": dict(current["settings"], gloss_language="ja"), "revision": current["revision"]})
        current = request({"action": "state"})
        assert current["settings"]["gloss_language"] == "ja"
        request({"action": "restore", "id": saved_gloss["backup"], "revision": current["revision"]})
        assert request({"action": "state"})["settings"]["gloss_language"] == "off"
        assert request({"action": "doctor"})["checks"]
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        errors = process.stderr.read()
        assert process.returncode == 0, errors
    # Install the bundled prediction resources without touching the real Rime
    # configuration or reloading the desktop input method.
    rime = home / "Library/Rime"
    (rime / "build").mkdir(parents=True)
    daily = rime / "build/rime_ice.schema.yaml"
    daily.write_text('schema:\n  schema_id: rime_ice\n  name: "包内安装测试"\n'
                     'engine:\n  processors:\n    - lua_processor@*keytrack_logger\n    - lua_processor@*kev_hotkey\n'
                     '    - ascii_composer\n    - key_binder\n'
                     '  translators:\n    - table_translator\n'
                     '  filters:\n    - uniquifier\n'
                     'switches:\n  - name: ascii_mode\n    reset: 0')
    daily_custom = rime / "rime_ice.custom.yaml"
    daily_custom.write_text("# original daily configuration\npatch:\n  unrelated: true\n")
    before_daily = daily.read_bytes(), daily_custom.read_bytes()
    data = home / ".keytrack"
    enabled = data / "kev-rime/enabled"
    enabled.parent.mkdir(parents=True)
    enabled.write_text("1\n")
    def install_prediction(*options):
        outcome = subprocess.run([str(helper), "setup-prediction", "--no-deploy", *options],
                                 cwd=root, env=env, capture_output=True, text=True, timeout=15)
        assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    install_prediction()
    assert before_daily == (daily.read_bytes(), daily_custom.read_bytes())
    source_db = helper.parent / "_internal/data/prediction/keytrack-predict.db"
    assert (rime / "keytrack-predict.db").read_bytes() == source_db.read_bytes()
    assert (data / "prediction/control").read_text() == "enabled=0\nmax_candidates=3\nmax_iterations=1\n"
    assert enabled.read_text() == "1\n"
    assert not (data / "annotations/control").exists()
    assert (rime / "lua/keytrack_comments.lua").is_file()
    assert (rime / "lua/keytrack_glossary.lua").is_file()
    managed = [rime / "default.custom.yaml", rime / "rime_ice_predict.schema.yaml", rime / "keytrack-predict.db",
               rime / "lua/prediction_guard.lua", rime / "lua/prediction_filter.lua"]
    before_managed = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in managed}
    before_backups = sorted(str(path.relative_to(data)) for path in (data / "prediction/backups").rglob("*") if path.is_file())
    install_prediction()
    assert before_managed == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in managed}
    assert before_backups == sorted(str(path.relative_to(data)) for path in (data / "prediction/backups").rglob("*") if path.is_file())
    fixture_db = helper.parent / "_internal/data/prediction/keytrack-predict-fixture.db"
    install_prediction("--db-file", str(fixture_db))
    assert (rime / "keytrack-predict.db").read_bytes() == fixture_db.read_bytes()
    custom_installed = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in managed}
    custom_backups = sorted(str(path.relative_to(data)) for path in (data / "prediction/backups").rglob("*") if path.is_file())
    install_prediction()
    assert custom_installed == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in managed}
    assert custom_backups == sorted(str(path.relative_to(data)) for path in (data / "prediction/backups").rglob("*") if path.is_file())
    assert (rime / "keytrack-predict.db").read_bytes() == fixture_db.read_bytes()
    assert enabled.read_text() == "1\n"
    # The ordinary recorder must ingest using bundled PyObjC and SQLite, too.
    data.mkdir(exist_ok=True)
    import datetime
    now = datetime.datetime.now().timestamp()
    recorder = subprocess.Popen([str(helper), "record"], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    import time
    import sqlite3
    # Attribute live input after the native sampler has initialized.
    time.sleep(3)
    (data / "ime_commits.jsonl").write_text(json.dumps({"ts": time.time(), "text": "独立包测试"}) + "\n")
    ingested = False
    for _ in range(40):
        if recorder.poll() is not None:
            break
        db = data / "keytrack.db"
        if db.exists():
            try:
                with sqlite3.connect(db) as connection:
                    ingested = connection.execute("SELECT count(*) FROM segments").fetchone()[0] > 0
            except sqlite3.OperationalError:
                pass
        if ingested:
            break
        time.sleep(0.1)
    recorder.send_signal(signal.SIGINT)
    stdout, stderr = recorder.communicate(timeout=10)
    with sqlite3.connect(data / "keytrack.db") as connection:
        ingested = connection.execute("SELECT count(*) FROM segments WHERE text = ?", ("独立包测试",)).fetchone()[0] == 1
    assert ingested, f"Recorder did not ingest synthetic input: {stderr} {stdout}"
    assert recorder.returncode == 0, stderr
    with sqlite3.connect(data / "keytrack.db") as connection:
        attributed = connection.execute("SELECT app FROM segments WHERE text = ?", ("独立包测试",)).fetchone()[0]
    print("Bundled native app attribution:", "available" if attributed != "Unknown" else "unavailable in current desktop session")
    # Marker dispatch reaches the bundled bridge, even without a source script.
    invalid = root / "invalid.json"
    invalid.write_text("{}")
    bridge = subprocess.run([str(helper), str(app / "Contents/Resources/keytrack-runtime/_internal/rime/kev_bridge.marker"), str(invalid), str(root / "response")], cwd=root, env=env, capture_output=True, text=True, timeout=10)
    assert bridge.returncode == 1 and "Kev Rime bridge:" in bridge.stderr, bridge.stderr
print("Package checks passed: isolated runtime, shared appearance catalog/new-theme save and restore, prediction install/reinstall/library replacement, private settings, read-only statistics, recorder and bridge dispatch.")
