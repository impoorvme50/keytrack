#!/usr/bin/env python3
"""Freeze native public Rime pools with a private HOME and no user dictionary.

This is a reproducible data collection tool, not a test of the daily schema.
It never submits text, loads Lua/loggers, reads history or copies user databases.
"""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from keytrack import kev_eval

# Fixed public typo cases; the desired full answer is outside the normal code.
# These are chosen before model evaluation to test refusal to promote a bad pool.
REJECT_TYPOS = [
    ("qinglianxiyishen", "如果症状加重，", "请联系医生"),
    ("woxiangchidianxing", "下午茶的时候，", "我想吃点心"),
    ("qinggaosuwoditiezhang", "我找不到车站，", "请告诉我地铁站"),
    ("chuhuoqianzuozhijiang", "要检查产品质量，", "出货前做质检"),
    ("qingfazuixinbaoji", "客户需要最新价格，", "请发最新报价"),
    ("qingquerenjiaoqian", "排产前要明确交付日期，", "请确认交期"),
]

SCHEMA = '''schema:
  schema_id: keytrack_public_eval
  name: Public evaluation only
  version: "1"
engine:
  processors: [speller, selector, express_editor]
  segmentors: [abc_segmentor, fallback_segmentor]
  translators: [script_translator]
  filters: [uniquifier]
speller:
  alphabet: abcdefghijklmnopqrstuvwxyz
  delimiter: "'"
translator:
  dictionary: rime_ice
  prism: rime_ice
  enable_user_dict: false
  enable_completion: true
  enable_sentence: true
menu:
  page_size: 5
'''


class Traits(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(x, C.c_char_p) for x in (
        'shared_data_dir', 'user_data_dir', 'distribution_name', 'distribution_code_name',
        'distribution_version', 'app_name')] + [('modules', C.POINTER(C.c_char_p)),
        ('min_log_level', C.c_int)] + [(x, C.c_char_p) for x in ('log_dir', 'prebuilt_data_dir', 'staging_dir')]


class Candidate(C.Structure):
    _fields_ = [('text', C.c_char_p), ('comment', C.c_char_p), ('reserved', C.c_void_p)]


class Menu(C.Structure):
    _fields_ = [(x, C.c_int) for x in ('page_size', 'page_no', 'is_last_page',
        'highlighted_candidate_index', 'num_candidates')] + [
        ('candidates', C.POINTER(Candidate)), ('select_keys', C.c_char_p)]


class Composition(C.Structure):
    _fields_ = [(x, C.c_int) for x in ('length', 'cursor_pos', 'sel_start', 'sel_end')] + [('preedit', C.c_char_p)]


class Context(C.Structure):
    _fields_ = [('data_size', C.c_int), ('composition', Composition), ('menu', Menu),
        ('commit_text_preview', C.c_char_p), ('select_labels', C.POINTER(C.c_char_p))]


NAMES = ('setup set_notification_handler initialize finalize start_maintenance is_maintenance_mode '
    'join_maintenance_thread deployer_initialize prebuild deploy deploy_schema deploy_config_file '
    'sync_user_data create_session find_session destroy_session cleanup_stale_sessions cleanup_all_sessions '
    'process_key commit_composition clear_composition get_commit free_commit get_context free_context '
    'get_status free_status set_option get_option set_property get_property get_schema_list '
    'free_schema_list get_current_schema select_schema').split()


class API(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(name, C.c_void_p) for name in NAMES]


def capture(source: Path, output: Path) -> None:
    frozen = kev_eval.load_dataset(source)
    if output.exists() or output.with_suffix('.manifest.json').exists():
        raise ValueError('refusing to replace a previously frozen dataset')
    public_build = Path.home() / 'Library/Rime/build'
    library = Path('/Library/Input Methods/Squirrel.app/Contents/Frameworks/librime.1.dylib')
    binaries = [public_build / name for name in ('rime_ice.table.bin', 'rime_ice.prism.bin')]
    provenance = [{'file': path.name, 'sha256': kev_eval.digest(path)} for path in binaries]
    library_hash = kev_eval.digest(library)
    original_home = os.environ.get('HOME')
    examples = json.loads(json.dumps(frozen['data']['examples']))
    for row, (code, context, target) in zip((x for x in examples if x['kind'] == 'reject'), REJECT_TYPOS):
        row.update(input=code, previous_text=context, missing_target=target,
                   reject_reason='typo_pool_without_intended_complete_answer')
    with tempfile.TemporaryDirectory(prefix='keytrack-public-kev-') as temp:
        root = Path(temp)
        os.environ['HOME'] = str(root)
        try:
            (root / 'build').mkdir()
            for path in binaries:
                shutil.copyfile(path, root / 'build' / path.name)
            (root / 'build/keytrack_public_eval.schema.yaml').write_text(SCHEMA)
            (root / 'build/default.yaml').write_text('config_version: "1"\nschema_list:\n  - schema: keytrack_public_eval\n')
            lib = C.CDLL(str(library), mode=C.RTLD_GLOBAL)
            lib.rime_get_api.restype = C.POINTER(API)
            api = lib.rime_get_api().contents
            def call(name, result, *types):
                return C.CFUNCTYPE(result, *types)(getattr(api, name))
            traits = Traits()
            traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
            traits.shared_data_dir = traits.user_data_dir = str(root).encode()
            traits.prebuilt_data_dir = str(root / 'build').encode()
            traits.app_name = b'rime.keytrack-public-eval'
            traits.min_log_level = 3
            traits.log_dir = str(root).encode()
            modules = (C.c_char_p * 2)(b'default', None)
            traits.modules = modules
            call('setup', None, C.POINTER(Traits))(C.byref(traits))
            call('initialize', None, C.POINTER(Traits))(C.byref(traits))
            session = call('create_session', C.c_size_t)()
            if not session or not call('select_schema', C.c_int, C.c_size_t, C.c_char_p)(session, b'keytrack_public_eval'):
                raise ValueError('isolated public schema unavailable')
            try:
                key = call('process_key', C.c_int, C.c_size_t, C.c_int, C.c_int)
                clear = call('clear_composition', None, C.c_size_t)
                for row in examples:
                    clear(session)
                    for char in row['input']:
                        key(session, ord(char), 0)
                    context = Context()
                    context.data_size = C.sizeof(context) - C.sizeof(C.c_int)
                    if not call('get_context', C.c_int, C.c_size_t, C.POINTER(Context))(session, C.byref(context)):
                        raise ValueError('native context unavailable')
                    try:
                        words = [context.menu.candidates[i].text.decode('utf-8')
                                 for i in range(context.menu.num_candidates)]
                    finally:
                        call('free_context', C.c_int, C.POINTER(Context))(C.byref(context))
                    if len(words) != 5 or len(set(words)) != 5:
                        raise ValueError(f'public sample {row["id"]} does not have five unique candidates')
                    row['candidates'] = words
                    if row['kind'] == 'reject' and row['missing_target'] in words:
                        raise ValueError(f'public reject {row["id"]} unexpectedly contains its intended full answer')
            finally:
                call('destroy_session', C.c_int, C.c_size_t)(session)
                call('finalize', None)()
        finally:
            if original_home is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = original_home
    data = {**frozen['data'], 'dataset_id': 'keytrack-kev-public-native-v2',
            'candidate_source': 'isolated_public_rime_pool', 'examples': examples}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    manifest = {**frozen['manifest'], 'dataset_id': data['dataset_id'],
        'candidate_source': data['candidate_source'], 'sha256': kev_eval.digest(output),
        'parent_dataset_sha256': frozen['sha256'],
        'candidate_provenance': {'engine': 'Squirrel bundled librime', 'library_sha256': library_hash,
            'public_binary_sources': provenance, 'schema': SCHEMA,
            'schema_sha256': hashlib.sha256(SCHEMA.encode()).hexdigest(),
            'user_dictionary_enabled': False, 'text_commits': 0, 'lua_or_logger_loaded': False,
            'note': 'Simplified public Rime schema, not the daily schema or personal frequency order. '
                    'No binary dictionary or user database is redistributed. Candidate strings are lexical data.'}}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Frozen {len(examples)} isolated public Rime pools; SHA-256 {manifest["sha256"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=kev_eval.DIAGNOSTIC_DATASET)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    capture(args.source, args.output)
