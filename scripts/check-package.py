"""Exercise the frozen helper from an arbitrary directory with only system PATH."""
import json
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
        original_phrases = state["phrases"]
        assert request({"action": "report", "day": state["today"]})["segments"] is None
        phrases = [{"code": "qpackage", "category": "测试", "text": '独立安装\n多行 "内容"'}]
        saved = request({"action": "phrases", "phrases": phrases, "revision": state["revision"]})
        state = request({"action": "state"})
        assert state["phrases"] == phrases
        preferences = dict(state["settings"], theme="blue", font_size=17, layout="vertical")
        request({"action": "settings", "settings": preferences, "revision": state["revision"]})
        state = request({"action": "state"})
        assert state["settings"]["theme"] == "blue"
        request({"action": "restore", "id": saved["backup"], "revision": state["revision"]})
        assert request({"action": "state"})["phrases"] == original_phrases
        request({"action": "install"}, ok=False)
        assert len(request({"action": "backups"})["backups"]) == 3
        assert request({"action": "doctor"})["checks"]
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        errors = process.stderr.read()
        assert process.returncode == 0, errors
    # The ordinary recorder must ingest using bundled PyObjC and SQLite, too.
    data = home / ".keytrack"
    data.mkdir()
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
print("Package checks passed: isolated runtime, read-only statistics, save/restore, recorder and bridge dispatch.")
