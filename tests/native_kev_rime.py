"""Isolated smoke test against Squirrel's actual librime and Lua plugin (macOS).

Run directly, not via unittest discovery. Uses synthetic text and a private HOME.
"""
import ctypes as C
import atexit
import json
import os, shutil, tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix='keytrack-native-'))
atexit.register(shutil.rmtree, root)
project = Path(__file__).resolve().parent.parent
os.environ['HOME'] = str(root)
(root/'.keytrack/kev-rime').mkdir(parents=True)
(root/'.keytrack/kev-rime/enabled').write_text('1\n')
(root/'build').mkdir()
(root/'lua').mkdir()
for name in ['kev_context.lua','kev_filter.lua','kev_hotkey.lua','keytrack_phrases.lua','keytrack_logger.lua']:
 shutil.copyfile(project/'rime'/name,root/'lua'/name)
(root/'lua/keytrack_phrases_data.lua').write_text('return {{code="qreply", text="第一行\\n第二行", category="测试"}}\n')
(root/'bridge.sh').write_text('cp "$1" "$HOME/request.json"\necho called >> "$HOME/calls"\nprintf "2\\t1\\n" > "$2"\n')
(root/'lua/probe.lua').write_text('''return function(input, seg, env)
 for _, word in ipairs({"你好", "拟好", "你", "拟", "尼", "泥"}) do
  yield(Candidate("probe", seg.start, seg._end, word, ""))
 end
end
''')
(root/'build/probe.schema.yaml').write_text(f'''schema:
  schema_id: probe
  name: Probe
  version: "1"
engine:
  processors: ["lua_processor@*keytrack_logger", "lua_processor@*kev_hotkey", speller, punctuator, selector, express_editor]
  segmentors: [abc_segmentor, punct_segmentor, fallback_segmentor]
  translators: [punct_translator, "lua_translator@*probe", "lua_translator@*keytrack_phrases"]
  filters: ["lua_filter@*kev_filter"]
speller:
  alphabet: abcdefghijklmnopqrstuvwxyz
menu:
  page_size: 7
punctuator:
  half_shape:
    ",": "，"
kev_rime:
  python: /bin/sh
  bridge: {root}/bridge.sh
  hotkey: Control+Shift+k
''')
(root/'build/default.yaml').write_text('config_version: "1"\nschema_list:\n  - schema: probe\n')

class Traits(C.Structure):
 _fields_=[('data_size',C.c_int)]+[(x,C.c_char_p) for x in ('shared_data_dir','user_data_dir','distribution_name','distribution_code_name','distribution_version','app_name')]+[('modules',C.POINTER(C.c_char_p)),('min_log_level',C.c_int)]+[(x,C.c_char_p) for x in ('log_dir','prebuilt_data_dir','staging_dir')]
class Candidate(C.Structure):
 _fields_=[('text',C.c_char_p),('comment',C.c_char_p),('reserved',C.c_void_p)]
class Menu(C.Structure):
 _fields_=[(x,C.c_int) for x in ('page_size','page_no','is_last_page','highlighted_candidate_index','num_candidates')]+[('candidates',C.POINTER(Candidate)),('select_keys',C.c_char_p)]
class Composition(C.Structure):
 _fields_=[(x,C.c_int) for x in ('length','cursor_pos','sel_start','sel_end')]+[('preedit',C.c_char_p)]
class Context(C.Structure):
 _fields_=[('data_size',C.c_int),('composition',Composition),('menu',Menu),('commit_text_preview',C.c_char_p),('select_labels',C.POINTER(C.c_char_p))]
class Commit(C.Structure):
 _fields_=[('data_size',C.c_int),('text',C.c_char_p)]
names='setup set_notification_handler initialize finalize start_maintenance is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy deploy_schema deploy_config_file sync_user_data create_session find_session destroy_session cleanup_stale_sessions cleanup_all_sessions process_key commit_composition clear_composition get_commit free_commit get_context free_context get_status free_status set_option get_option set_property get_property get_schema_list free_schema_list get_current_schema select_schema'.split()
class API(C.Structure):
 _fields_=[('data_size',C.c_int)]+[(x,C.c_void_p) for x in names]
libdir=Path('/Library/Input Methods/Squirrel.app/Contents/Frameworks')
lib=C.CDLL(str(libdir/'librime.1.dylib'),mode=C.RTLD_GLOBAL)
lua=C.CDLL(str(libdir/'rime-plugins/librime-lua.dylib'),mode=C.RTLD_GLOBAL)
lib.rime_get_api.restype=C.POINTER(API)
api=lib.rime_get_api().contents

def call(name,result,*types):
 return C.CFUNCTYPE(result,*types)(getattr(api,name))
t=Traits();t.data_size=C.sizeof(t)-C.sizeof(C.c_int)
t.shared_data_dir=t.user_data_dir=str(root).encode();t.app_name=b'rime.keytrack-check'
t.min_log_level=2;t.log_dir=str(root).encode()
mods=(C.c_char_p*4)(b'default',b'deployer',b'lua',None);t.modules=mods
call('setup',None,C.POINTER(Traits))(C.byref(t))
# Exercise actual Rime patch compilation as well as the runtime observer.
import sys
sys.path.insert(0, str(project))
from keytrack import rime_setup, kev_rime_setup
source = (root/'build/probe.schema.yaml').read_text().replace('"lua_processor@*keytrack_logger", "lua_processor@*kev_hotkey", ', '')
(root/'probe.schema.yaml').write_text(source)
old = 'patch:\n  "engine/processors/@next": lua_processor@*keytrack_logger\n'
old = kev_rime_setup.render_custom_yaml(old, Path('/bin/sh'), root/'bridge.sh')
(root/'probe.custom.yaml').write_text(rime_setup.render_custom_yaml(old))
call('deployer_initialize',None,C.POINTER(Traits))(C.byref(t))
assert call('deploy_schema',C.c_int,C.c_char_p)(str(root/'probe.schema.yaml').encode())
deployed = (root/'build/probe.schema.yaml').read_text()
assert deployed.index('lua_processor@*keytrack_logger') < deployed.index('lua_processor@*kev_hotkey') < deployed.index('    - speller'), deployed
call('initialize',None,C.POINTER(Traits))(C.byref(t))
s=call('create_session',C.c_size_t)()
assert s
assert call('select_schema',C.c_int,C.c_size_t,C.c_char_p)(s,b'probe')
key=call('process_key',C.c_int,C.c_size_t,C.c_int,C.c_int)

def committed():
 c=Commit();c.data_size=C.sizeof(c)-C.sizeof(C.c_int)
 assert call('get_commit',C.c_int,C.c_size_t,C.POINTER(Commit))(s,C.byref(c))
 text=c.text.decode()
 call('free_commit',C.c_int,C.POINTER(Commit))(C.byref(c))
 return text

# Separate commits must reach the native Lua notifier and join in session memory.
for _ in range(2):
 for ch in 'nihao': key(s,ord(ch),0)
 assert key(s,ord(' '),0)
 assert committed() == '你好'

def snapshot(label):
 c=Context();c.data_size=C.sizeof(c)-C.sizeof(C.c_int)
 assert call('get_context',C.c_int,C.c_size_t,C.POINTER(Context))(s,C.byref(c))
 words=[(c.menu.candidates[i].text.decode(),(c.menu.candidates[i].comment or b'').decode()) for i in range(c.menu.num_candidates)]
 preedit=(c.composition.preedit or b'').decode()
 call('free_context',C.c_int,C.POINTER(Context))(C.byref(c))
 print(label,preedit,words,flush=True)
 return preedit,words

for ch in 'nihao': key(s,ord(ch),0)
_,words=snapshot('before');assert len(words)==6
print('hotkey accepted',key(s,ord('k'),5),flush=True)
_,words=snapshot('after');assert words[0]==('拟好','✦ AI') and len(words)==6
assert json.loads((root/'request.json').read_text())['previous_text']=='你好你好'
# Cancel restores candidate menu without committing pinyin.
assert key(s,ord('k'),5)
_,words=snapshot('cancel');assert words[0]==('你好','') and len(words)==6
assert key(s,ord('k'),5)
assert (root/'calls').read_text().splitlines()==['called'] # Undo/reapply uses cache.
assert key(s,ord(' '),0)
assert committed()=='拟好'
# One comma commits the suggestion plus punctuation, without duplicated keypresses.
for ch in 'nihao': key(s,ord(ch),0)
assert key(s,ord('k'),5)
assert key(s,ord(','),0)
assert committed()=='拟好，'
for ch in 'qreply': key(s,ord(ch),0)
_,words=snapshot('phrase');assert words[0]==('第一行\n第二行','测试')
assert key(s,ord(' '),0)
assert committed()=='第一行\n第二行'
# Releases are observed but must not be counted.
key(s, ord('a'), 1 << 30)
call('destroy_session',C.c_int,C.c_size_t)(s)
call('finalize',None)()
print('Native Rime context, cache, candidate marker, cancellation, Space and comma PASS',flush=True)

buckets = [json.loads(line) for line in (root/'.keytrack/ime_keys.jsonl').read_text().splitlines()]
assert all(b['capture_version'] == 3 for b in buckets), buckets
from collections import Counter
observed = Counter()
for b in buckets: observed.update(b['keys'])
expected = Counter('nihao' * 4 + 'qreply')
expected.update({'space': 4, 'Shift+Control+k': 4, 'comma': 1})
assert observed == expected, (observed, expected)
print('Logger: exact 35 keypresses, releases excluded, capture_version 3 PASS')
