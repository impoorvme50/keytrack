-- Run with: lua tests/kev_rime_lua_mock.lua
-- A lazy Rime menu mock verifies that only the explicit hotkey changes it.

local source = debug.getinfo(1, "S").source:sub(2)
local root = source:match("^(.*)/tests/[^/]+$") or "."
if root == "" then root = "." end
package.path = root .. "/rime/?.lua;" .. package.path
local recent = require("kev_context")

local temporary = os.tmpname()
os.remove(temporary)
local home = temporary .. "-kev-rime-mock"
local function shell_quote(value)
  return "'" .. value:gsub("'", "'\\''") .. "'"
end
local original_getenv, original_yield, original_shadow = os.getenv, yield, ShadowCandidate
os.getenv = function(name)
  if name == "HOME" then return home end
  return original_getenv(name)
end
ShadowCandidate = function(candidate, kind, text, comment)
  return { type = kind, text = text, comment = comment, original = candidate }
end

local function run()
  local directory = home .. "/.keytrack/kev-rime"
  assert(os.execute("/bin/mkdir -p -m 700 " .. shell_quote(directory)))
  local words = { "你", "尼", "拟", "呢", "逆", "泥" }
  local original_candidates = {}
  for index, word in ipairs(words) do
    original_candidates[index] = {
      type = "mock", text = word, comment = index == 3 and "原注释" or ""
    }
  end
  local properties = {}
  local last_commit = "你好"
  local commit_callback
  local segment = { start = 0, _end = 3, selected_index = 0, status = "kGuess" }
  local context = {
    input = "nin",
    caret_pos = 3,
    composition = { back = function() return segment end },
    commit_history = { latest_text = function() return last_commit end },
    commit_notifier = { connect = function(_, callback)
      commit_callback = callback
      return { disconnect = function() commit_callback = nil end }
    end },
  }
  function context:get_property(key) return properties[key] end
  function context:set_property(key, value) properties[key] = value end
  function context:get_commit_text() return last_commit end

  local env = {
    engine = {
      context = context,
      schema = { config = { get_string = function() return nil end } },
    },
  }
  local filter = dofile(root .. "/rime/kev_filter.lua")
  local processor = dofile(root .. "/rime/kev_hotkey.lua")
  filter.init(env)
  processor.init(env)

  yield = function(candidate) coroutine.yield(candidate) end
  local function make_menu()
    local cached = {}
    local running = coroutine.create(function()
      local cursor = 0
      local input = {
        iter = function(self)
          -- librime-lua returns (next_function, translation), not a closure.
          return function(state)
            assert(state == self, "translation iterator lost its state")
            cursor = cursor + 1
            return original_candidates[cursor]
          end, self
        end,
      }
      filter.func(input, env)
    end)
    return {
      get_candidate_at = function(_, index)
        while #cached <= index and coroutine.status(running) ~= "dead" do
          local ok, candidate = coroutine.resume(running)
          assert(ok, candidate)
          if candidate then cached[#cached + 1] = candidate end
        end
        return cached[index + 1]
      end,
    }
  end
  segment.menu = make_menu()
  local refreshes = 0
  function context:has_menu() return segment.menu:get_candidate_at(0) ~= nil end
  function context:get_selected_candidate() return segment.menu:get_candidate_at(0) end
  function context:refresh_non_confirmed_composition()
    refreshes = refreshes + 1
    segment.menu = make_menu()
    return true
  end
  local function key(repr)
    return { release = function() return false end, repr = function() return repr end }
  end
  local hotkey = key("Shift+Control+k")
  local function first() return context:get_selected_candidate() end
  local function mark(index) return segment.menu:get_candidate_at(index - 1).comment end

  -- The feature is off by default. No request is queued and the shortcut passes through.
  assert(first().text == "你" and first().comment == "")
  assert(processor.func(hotkey, env) == 2)
  assert(processor.func(key("space"), env) == 2)
  assert(refreshes == 0)
  local entries = assert(io.popen("ls -A " .. shell_quote(directory))):read("*a")
  assert(entries == "")

  local switch = assert(io.open(directory .. "/enabled", "w"))
  switch:write("1\n")
  switch:close()
  context:refresh_non_confirmed_composition()
  assert(first().text == "你" and first().comment == "")
  for _, repr in ipairs({"space", "comma", "BackSpace", "Control+c", "a", "Escape"}) do
    local before = refreshes
    assert(processor.func(key(repr), env) == 2)
    assert(refreshes == before)
  end
  segment.selected_index = 1
  assert(processor.func(hotkey, env) == 2)
  segment.selected_index = 0

  env.kev_python = "/bin/sh"
  env.kev_bridge = home .. "/bridge.sh"
  local bridge = assert(io.open(env.kev_bridge, "w"))
  local snapshot = home .. "/snapshot.json"
  bridge:write('cp "$1" ' .. shell_quote(snapshot) .. '\nprintf "3\\t1\\n" > "$2"\n')
  bridge:close()
  last_commit = "去医院"
  commit_callback(context)
  last_commit = "看"
  commit_callback(context)
  assert(processor.func(hotkey, env) == 1)
  local request = assert(io.open(snapshot)):read("*a")
  assert(request:find('"previous_text":"去医院看"', 1, true))
  assert(first().text == "拟")
  assert(first().comment == "原注释  ✦ AI")
  assert(original_candidates[3].comment == "原注释")
  for _, repr in ipairs({"space", "comma", "BackSpace", "Control+c"}) do
    local before = refreshes
    assert(processor.func(key(repr), env) == 2)
    assert(refreshes == before)
    assert(first().text == "拟")
  end

  -- Pressing the hotkey again cancels the suggestion without another request.
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write("exit 1\n")
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(first().text == "你" and mark(3) == "原注释")

  -- Identical retry is answered in memory even when the bridge is now unavailable.
  -- Space above preserves context; navigation/command keys clear it, so prime anew.
  recent.commit(env, "去医院看")
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write('printf "3\\t1\\n" > "$2"\n')
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(processor.func(hotkey, env) == 1) -- undo
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write("exit 1\n")
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(first().text == "拟")
  assert(processor.func(hotkey, env) == 1) -- undo
  recent.reset(env)

  -- Weak confidence marks the proposed word in place.
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write('printf "3\\t0\\n" > "$2"\n')
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(first().text == "你")
  assert(mark(3) == "原注释  ✦ AI ?")

  -- A failed request is visible and can be retried without eating normal keys.
  assert(processor.func(hotkey, env) == 1) -- dismiss weak suggestion
  recent.reset(env)
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write("exit 1\n")
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(first().text == "你" and first().comment == "AI 暂不可用")
  local before = refreshes
  assert(processor.func(key("space"), env) == 2)
  assert(refreshes == before)
  bridge = assert(io.open(env.kev_bridge, "w"))
  bridge:write('printf "3\\t1\\n" > "$2"\n')
  bridge:close()
  assert(processor.func(hotkey, env) == 1)
  assert(first().text == "拟")

  -- Turning off restores the original menu on the next composition.
  switch = assert(io.open(directory .. "/enabled", "w"))
  switch:write("0\n")
  switch:close()
  context.input, context.caret_pos, segment._end = "ninhao", 6, 6
  context:refresh_non_confirmed_composition()
  assert(first().text == "你" and mark(3) == "原注释")
  assert(processor.func(hotkey, env) == 2)
  processor.fini(env)
  assert(commit_callback == nil)
end

local ok, error_message = xpcall(run, debug.traceback)
os.getenv, yield, ShadowCandidate = original_getenv, original_yield, original_shadow
os.execute("/bin/rm -rf " .. shell_quote(home))
if not ok then error(error_message) end
print("Kev Rime Lua mock passed")
