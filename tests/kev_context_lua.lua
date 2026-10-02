-- Run with: lua tests/kev_context_lua.lua
package.path = "rime/?.lua;" .. package.path
local recent = require("kev_context")
local original_time = os.time
local now = 100
os.time = function() return now end
local ok, message = xpcall(function()
  local env, other = {}, {}
  local initial = { index = 1, adopt = false }
  recent.remember(env, "no preceding text", initial)
  assert(recent.previous(env) == "")
  assert(recent.lookup(env, "no preceding text") == initial)
  recent.commit(env, "去医院")
  recent.commit(env, "看")
  assert(recent.previous(env) == "去医院看")
  assert(recent.previous(other) == "") -- No cross-session sharing.
  recent.commit(env, string.rep("好", 200))
  assert(recent.previous(env) == string.rep("好", 160))
  recent.reset(env)
  recent.commit(env, "😀é医院")
  assert(utf8.len(recent.previous(env)) == 4)
  for _, key in ipairs({"BackSpace", "Left", "Shift+Return", "Control+v", "Super+c", "Alt+Tab", "Escape"}) do
    recent.commit(env, "上下文")
    recent.key(env, key)
    assert(recent.previous(env) == "")
  end
  recent.commit(env, "上下文")
  recent.key(env, "space")
  recent.key(env, "a")
  assert(recent.previous(env) == "上下文")
  local answer = { index = 2, adopt = true }
  recent.remember(env, "exact request", answer)
  assert(recent.lookup(env, "exact request") == answer)
  assert(recent.lookup(env, "other candidates/context") == nil)
  recent.remember(env, "failed", nil)
  assert(recent.lookup(env, "failed") == nil)
  now = 130
  assert(recent.lookup(env, "exact request") == nil)
  now = 160
  assert(recent.previous(env) == "")
  for index = 1, 12 do recent.remember(env, tostring(index), answer) end
  assert(#env.kev_cache == 8 and recent.lookup(env, "1") == nil)
  recent.commit(env, "新文字")
  assert(recent.lookup(env, "12") == nil)
  now = 159 -- A clock rollback must not preserve old context.
  assert(recent.previous(env) == "")
end, debug.traceback)
os.time = original_time
if not ok then error(message) end
print("Kev session context/cache checks passed")
