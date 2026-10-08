"""Deploy input-tool controls with Squirrel's real librime in a private HOME.

Run directly on macOS, outside unittest discovery. All schemas are synthetic;
no installed dictionary, user database, or production Rime directory is read.
"""
from __future__ import annotations

import ctypes as C
import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from tests.native_appearance import API, Config, Traits  # noqa: E402


SOURCE = '''schema:
  schema_id: input_tools_daily
  name: Synthetic input-tool controls
  version: "1"
switches:
  - name: ascii_mode
    reset: 0
    states: [中文, 英文]
  - name: emoji
    reset: 1 # synthetic original Emoji default
    states: [关闭, 开启]
engine:
  processors: [ascii_composer]
  segmentors: [fallback_segmentor]
  translators: []
melt_eng:
  enable_completion: false # synthetic original English default
cn_en:
  enable_completion: true # synthetic original mixed default
unrelated:
  keep: true
'''


def main():
    library_path = Path("/Library/Input Methods/Squirrel.app/Contents/Frameworks/librime.1.dylib")
    if not library_path.is_file():
        raise SystemExit("This isolated check requires Squirrel's installed macOS librime.")
    prior_home = os.environ.get("HOME")
    with tempfile.TemporaryDirectory(prefix="keytrack-input-tools-native-") as temporary:
        root = Path(temporary)
        os.environ["HOME"] = str(root)
        from keytrack import input_tools

        rime = root / "Rime"
        rime.mkdir()
        identifiers = ("input_tools_daily", "input_tools_snapshot")
        daily_source = rime / f"{identifiers[0]}.schema.yaml"
        daily_custom = rime / f"{identifiers[0]}.custom.yaml"
        snapshot_source = rime / f"{identifiers[1]}.schema.yaml"
        original_custom = '# synthetic user setting\npatch:\n  "unrelated/custom": true\n'
        daily_source.write_text(SOURCE)
        daily_custom.write_text(original_custom)
        snapshot_original = SOURCE.replace(identifiers[0], identifiers[1])
        snapshot_source.write_text(snapshot_original)
        library = C.CDLL(str(library_path), mode=C.RTLD_GLOBAL)
        library.rime_get_api.restype = C.POINTER(API)
        api = library.rime_get_api().contents

        def call(name, result, *types):
            return C.CFUNCTYPE(result, *types)(getattr(api, name))

        traits = Traits()
        traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
        traits.shared_data_dir = traits.user_data_dir = str(rime).encode()
        traits.app_name = b"rime.keytrack-input-tools-check"
        traits.min_log_level = 2
        traits.log_dir = str(root).encode()
        modules = (C.c_char_p * 3)(b"default", b"deployer", None)
        traits.modules = modules
        deployments, assertions = 0, 0
        call("setup", None, C.POINTER(Traits))(C.byref(traits))
        call("deployer_initialize", None, C.POINTER(Traits))(C.byref(traits))

        def deployed(identifier, expected):
            nonlocal deployments, assertions
            # Force compilation; librime timestamps alone have whole-second
            # resolution and would skip rapid adjacent synthetic cases.
            (rime / "build" / f"{identifier}.schema.yaml").unlink(missing_ok=True)
            path = rime / f"{identifier}.schema.yaml"
            assert call("deploy_schema", C.c_int, C.c_char_p)(str(path).encode()), identifier
            deployments += 1
            config = Config()
            assert call("schema_open", C.c_int, C.c_char_p, C.POINTER(Config))(identifier.encode(), C.byref(config)), identifier
            try:
                controls = {"melt_eng/enable_completion": expected[0], "cn_en/enable_completion": expected[1],
                            "switches/@1/reset": expected[2], "switches/@0/reset": 0,
                            "unrelated/keep": True}
                if identifier == identifiers[0]:
                    controls["unrelated/custom"] = True
                for key, value in controls.items():
                    actual = C.c_int()
                    getter = "config_get_int" if key.endswith("/reset") else "config_get_bool"
                    found = call(getter, C.c_int, C.POINTER(Config), C.c_char_p, C.POINTER(C.c_int))(
                        C.byref(config), key.encode(), C.byref(actual))
                    if value is None:
                        assert not found, (identifier, key, "should be absent", actual.value)
                    else:
                        assert found, (identifier, key, "missing")
                        assert actual.value == value, (identifier, key, actual.value, value)
                    assertions += 1
            finally:
                call("config_close", None, C.POINTER(Config))(C.byref(config))

        def both(expected):
            for identifier in identifiers:
                deployed(identifier, expected)

        try:
            # Preserve does not invent missing defaults or alter user patches.
            assert input_tools.custom_patch(original_custom, {}, SOURCE) == original_custom
            assert input_tools.snapshot_patch(snapshot_original, {}, {}) == (snapshot_original, {})
            both((False, True, 1))
            originals = {}
            for choices, expected in (({"english_completion": "on", "mixed_completion": "off", "emoji_default": "off"},
                                       (True, False, 0)),
                                      ({"english_completion": "off", "mixed_completion": "on", "emoji_default": "on"},
                                       (False, True, 1))):
                daily_custom.write_text(input_tools.custom_patch(daily_custom.read_text(), choices, SOURCE))
                changed, originals = input_tools.snapshot_patch(snapshot_source.read_text(), choices, originals)
                snapshot_source.write_text(changed)
                both(expected)
            daily_custom.write_text(input_tools.custom_patch(daily_custom.read_text(), {}, SOURCE))
            changed, _ = input_tools.snapshot_patch(snapshot_source.read_text(), {}, originals)
            assert changed == snapshot_original
            assert daily_custom.read_text() == original_custom
            snapshot_source.write_text(changed)
            both((False, True, 1))

            # Both existing branches must restore absence, not a guessed true
            # or false scalar. This also verifies Rime slash patch creation.
            missing_source = SOURCE.replace("  enable_completion: false # synthetic original English default\n", "").replace(
                "    reset: 1 # synthetic original Emoji default\n", "")
            missing_snapshot = missing_source.replace(identifiers[0], identifiers[1])
            daily_source.write_text(missing_source)
            snapshot_source.write_text(missing_snapshot)
            both((None, True, None))
            choices = {"english_completion": "off", "emoji_default": "on"}
            daily_custom.write_text(input_tools.custom_patch(daily_custom.read_text(), choices, missing_source))
            changed, originals = input_tools.snapshot_patch(missing_snapshot, choices, {})
            assert originals == {"english_completion": "", "emoji_default": ""}
            snapshot_source.write_text(changed)
            both((False, True, 1))
            daily_custom.write_text(input_tools.custom_patch(daily_custom.read_text(), {}, missing_source))
            changed, _ = input_tools.snapshot_patch(snapshot_source.read_text(), {}, originals)
            assert changed == missing_snapshot
            assert daily_custom.read_text() == original_custom
            snapshot_source.write_text(changed)
            both((None, True, None))
        finally:
            call("finalize", None)()
            if prior_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = prior_home
        print(json.dumps({"input_tool_deployments": deployments, "native_config_assertions": assertions,
                          "daily_and_snapshot_consistent": True, "original_values_and_absence_restored": True,
                          "isolated_home_and_user_directory": True, "production_rime_touched": False}))


if __name__ == "__main__":
    main()
