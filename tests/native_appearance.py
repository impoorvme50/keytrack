"""Isolated appearance patch/deployment check against Squirrel's actual librime.

Run directly on macOS, not via unittest discovery. Uses synthetic configuration
and a private user directory; it never deploys the installed user's settings.
"""
import ctypes as C
import json
import os
import sys
import tempfile
from pathlib import Path


class Traits(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(key, C.c_char_p) for key in (
        "shared_data_dir", "user_data_dir", "distribution_name", "distribution_code_name",
        "distribution_version", "app_name")] + [("modules", C.POINTER(C.c_char_p)),
        ("min_log_level", C.c_int)] + [(key, C.c_char_p) for key in (
        "log_dir", "prebuilt_data_dir", "staging_dir")]


class Config(C.Structure):
    _fields_ = [("ptr", C.c_void_p)]


names = """setup set_notification_handler initialize finalize start_maintenance
is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy
deploy_schema deploy_config_file sync_user_data create_session find_session
destroy_session cleanup_stale_sessions cleanup_all_sessions process_key
commit_composition clear_composition get_commit free_commit get_context
free_context get_status free_status set_option get_option set_property
get_property get_schema_list free_schema_list get_current_schema select_schema
schema_open config_open config_close config_get_bool config_get_int
config_get_double config_get_string""".split()


class API(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(key, C.c_void_p) for key in names]


def main():
    project = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project))
    with tempfile.TemporaryDirectory(prefix="keytrack-appearance-native-") as temporary:
        root = Path(temporary)
        os.environ["HOME"] = str(root)
        from keytrack import console, kev_rime_setup

        rime = root / "Rime"
        rime.mkdir()
        (rime / "squirrel.yaml").write_text('''config_version: "1"
style:
  font_face: "Original Global"
  inline_preedit: true
  color_scheme: original
  color_scheme_dark: original_dark
preset_color_schemes:
  original:
    font_face: "Original Theme"
    label_font_face: "Original Number"
    comment_font_face: "Original Comment"
    inline_preedit: true
  original_dark:
    font_face: "Original Dark Theme"
    inline_preedit: true
''')
        (rime / "squirrel.custom.yaml").write_text('''patch:
  "style/font_face": "Original Direct" # preserve this comment
  "style/inline_preedit": true
  unrelated: true
''')
        (rime / "rime_ice.custom.yaml").write_text(kev_rime_setup.render_custom_yaml(
            "patch:\n", Path("/tmp/python"), Path("/tmp/bridge")))
        store = console.ConsoleStore(root / "console", rime, str(root / "unused.db"), demo=True)
        library = C.CDLL("/Library/Input Methods/Squirrel.app/Contents/Frameworks/librime.1.dylib", mode=C.RTLD_GLOBAL)
        library.rime_get_api.restype = C.POINTER(API)
        api = library.rime_get_api().contents

        def call(name, result, *types):
            return C.CFUNCTYPE(result, *types)(getattr(api, name))

        traits = Traits()
        traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
        traits.shared_data_dir = traits.user_data_dir = str(rime).encode()
        traits.app_name = b"rime.keytrack-appearance-check"
        traits.min_log_level = 2
        traits.log_dir = str(root).encode()
        modules = (C.c_char_p * 3)(b"default", b"deployer", None)
        traits.modules = modules
        call("setup", None, C.POINTER(Traits))(C.byref(traits))
        call("deployer_initialize", None, C.POINTER(Traits))(C.byref(traits))

        def deployed(expected):
            # Rime's source freshness uses whole-second timestamps. Force each
            # isolated compile so rapid successive cases exercise their patches.
            (rime / "build/squirrel.yaml").unlink(missing_ok=True)
            assert call("deploy_config_file", C.c_int, C.c_char_p, C.c_char_p)(b"squirrel.yaml", b"config_version")
            config = Config()
            assert call("config_open", C.c_int, C.c_char_p, C.POINTER(Config))(b"squirrel", C.byref(config))
            try:
                for path, value in expected.items():
                    if type(value) is bool:
                        actual = C.c_int()
                        assert call("config_get_bool", C.c_int, C.POINTER(Config), C.c_char_p, C.POINTER(C.c_int))(
                            C.byref(config), path.encode(), C.byref(actual)), path
                        assert bool(actual.value) == value, (path, actual.value, value)
                    else:
                        buffer = C.create_string_buffer(1024)
                        assert call("config_get_string", C.c_int, C.POINTER(Config), C.c_char_p, C.c_char_p, C.c_size_t)(
                            C.byref(config), path.encode(), buffer, len(buffer)), path
                        assert buffer.value.decode() == value, (path, buffer.value, value)
            finally:
                call("config_close", None, C.POINTER(Config))(C.byref(config))

        saved = store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face="Helvetica",
                                         preedit_mode="candidate"), store.revision())
        expected = {}
        for prefix in ("style", "preset_color_schemes/original", "preset_color_schemes/original_dark"):
            expected.update({f"{prefix}/{field}": "Helvetica" for field in console.APPEARANCE_FIELDS[:3]})
            expected[f"{prefix}/inline_preedit"] = False
        deployed(expected)
        store.save_settings(dict(console.DEFAULTS, theme="mist", font_mode="system", preedit_mode="inline"), store.revision())
        expected = {}
        for prefix in ("style", "preset_color_schemes/keytrack_light", "preset_color_schemes/keytrack_dark"):
            expected.update({f"{prefix}/{field}": "" for field in console.APPEARANCE_FIELDS[:3]})
            expected[f"{prefix}/inline_preedit"] = True
        deployed(expected)
        store.restore(saved["backup"], store.revision())
        deployed({"style/font_face": "Original Direct", "style/inline_preedit": True,
                  "preset_color_schemes/original/font_face": "Original Theme",
                  "preset_color_schemes/original/label_font_face": "Original Number",
                  "preset_color_schemes/original/comment_font_face": "Original Comment",
                  "preset_color_schemes/original_dark/font_face": "Original Dark Theme"})
        assert "# preserve this comment" in (rime / "squirrel.custom.yaml").read_text()
        call("finalize", None)()
        print(json.dumps({"appearance_deployments": 3, "native_config_assertions": 30,
                          "original_values_restored": True, "isolated_user_directory": True}))


if __name__ == "__main__":
    main()
