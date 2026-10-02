-- Optional, explicit Kev candidate suggestion for Rime Ice.
-- Ordinary keys always continue to Rime untouched.

local M = {}
local recent = require("kev_context")
local kAccepted, kNoop = 1, 2
local MAX_CANDIDATES = 5
local DEFAULT_HOTKEY = "Control+Shift+k"
local INPUT_PROP = "kev_rime_input"
local PREVIOUS_PROP = "kev_rime_previous"
local CHOICE_PROP = "kev_rime_choice"
local ADOPT_PROP = "kev_rime_adopt"
local STATUS_PROP = "kev_rime_status"

local function normalized_chord(repr)
  if type(repr) ~= "string" then return "" end
  local modifiers, key = repr:match("^(.+)%+([^+]+)$")
  if not modifiers then return repr end
  if #key == 1 then key = key:lower() end
  local names = {}
  for name in modifiers:gmatch("[^+]+") do names[#names + 1] = name end
  table.sort(names)
  return table.concat(names, "+") .. "+" .. key
end

local function enabled(path)
  if not path then return false end
  local file = io.open(path, "r")
  if not file then return false end
  local value = file:read("*l")
  file:close()
  return value == "1"
end

local function clear_choice(context)
  context:set_property(INPUT_PROP, "")
  context:set_property(PREVIOUS_PROP, "")
  context:set_property(CHOICE_PROP, "")
  context:set_property(ADOPT_PROP, "")
  context:set_property(STATUS_PROP, "")
end

local function previous_text(context)
  return context.commit_history:latest_text() or ""
end

local function clear_stale_choice(context)
  local saved_input = context:get_property(INPUT_PROP) or ""
  if saved_input ~= "" and (
    not context:has_menu()
    or saved_input ~= (context.input or "")
    or (context:get_property(PREVIOUS_PROP) or "") ~= previous_text(context)
  ) then
    clear_choice(context)
  end
end

local function shell_quote(value)
  return "'" .. value:gsub("'", "'\\''") .. "'"
end

local function json_quote(value)
  return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
    if char == '"' then return '\\"' end
    if char == "\\" then return "\\\\" end
    if char == "\n" then return "\\n" end
    if char == "\r" then return "\\r" end
    if char == "\t" then return "\\t" end
    return string.format("\\u%04x", char:byte())
  end) .. '"'
end

local function request_json(code, previous, candidates)
  local quoted = {}
  for i, text in ipairs(candidates) do quoted[i] = json_quote(text) end
  return '{"input":' .. json_quote(code)
    .. ',"previous_text":' .. json_quote(previous)
    .. ',"candidates":[' .. table.concat(quoted, ",") .. "]}\n"
end

local function unique_paths(directory)
  local process = io.popen("/usr/bin/uuidgen 2>/dev/null", "r")
  if not process then return nil, nil end
  local uuid = process:read("*l") or ""
  process:close()
  if not uuid:match("^[%da-fA-F%-]+$") or #uuid ~= 36 then return nil, nil end
  local basename = directory .. "/" .. uuid
  return basename .. ".json", basename .. ".response"
end

local function get_candidates(context)
  local segment = context.composition:back()
  local menu = segment and segment.menu
  if not menu then return {} end
  local candidates = {}
  for index = 0, MAX_CANDIDATES - 1 do
    local candidate = menu:get_candidate_at(index)
    if not candidate or not candidate.text or candidate.text == "" then break end
    candidates[#candidates + 1] = candidate.text
  end
  return candidates
end

local function run_bridge(env, code, previous, candidates)
  local python, bridge = env.kev_python, env.kev_bridge
  if not python or not bridge or python:sub(1, 1) ~= "/"
      or bridge:sub(1, 1) ~= "/" then return nil end
  local home = os.getenv("HOME")
  if not home or home == "" then return nil end
  local directory = home .. "/.keytrack/kev-rime"
  local request_path, response_path = unique_paths(directory)
  if not request_path then return nil end
  local ok, answer = pcall(function()
    local request = io.open(request_path, "w")
    if not request then return nil end
    local written = request:write(request_json(code, previous, candidates))
    local closed = request:close()
    if not written or not closed then return nil end
    local command = shell_quote(python) .. " " .. shell_quote(bridge)
      .. " " .. shell_quote(request_path) .. " " .. shell_quote(response_path)
      .. " >/dev/null 2>&1"
    local status = os.execute(command)
    if status ~= true and status ~= 0 then return nil end
    local response = io.open(response_path, "r")
    if not response then return nil end
    local value = response:read(32) or ""
    local more = response:read(1)
    response:close()
    if more then return nil end
    local index_text, adopt_text = value:match("^([1-5])\t([01])%s*$")
    local index = tonumber(index_text)
    if index and index <= #candidates then
      return { index = index, adopt = adopt_text == "1" }
    end
    return nil
  end)
  pcall(os.remove, request_path)
  pcall(os.remove, response_path)
  if ok then return answer end
  return nil
end

local function rerank(env)
  local context = env.engine.context
  clear_stale_choice(context)
  if not context:has_menu() then return false end
  if (context:get_property(CHOICE_PROP) or "") ~= "" then
    clear_choice(context)
    context:refresh_non_confirmed_composition()
    return true
  end

  local code = context.input or ""
  local segment = context.composition:back()
  if #code == 0 or #code > 40 or not code:match("^[a-z']+$")
      or not segment or segment.start ~= 0 or segment._end ~= #code
      or context.caret_pos ~= #code or segment.selected_index ~= 0
      or segment.status == "kSelected" or segment.status == "kConfirmed" then
    return false
  end
  local candidates = get_candidates(context)
  if #candidates < 2 then return false end
  local previous = previous_text(context)
  local surrounding = recent.previous(env)
  local fingerprint = request_json(code, surrounding, candidates)
  local answer = recent.lookup(env, fingerprint)
  if not answer then
    answer = run_bridge(env, code, surrounding, candidates)
    recent.remember(env, fingerprint, answer)
  end
  if not context:has_menu() or context.input ~= code
      or previous_text(context) ~= previous then return true end
  if not answer then
    context:set_property(INPUT_PROP, code)
    context:set_property(PREVIOUS_PROP, previous)
    context:set_property(STATUS_PROP, "AI 暂不可用")
    context:refresh_non_confirmed_composition()
    return true
  end
  context:set_property(INPUT_PROP, code)
  context:set_property(PREVIOUS_PROP, previous)
  context:set_property(CHOICE_PROP, candidates[answer.index])
  context:set_property(ADOPT_PROP, answer.adopt and "1" or "0")
  context:set_property(STATUS_PROP, "")
  if context:refresh_non_confirmed_composition() == false then
    clear_choice(context)
  end
  return true
end

function M.init(env)
  local config = env.engine.schema.config
  env.kev_hotkey = normalized_chord(config:get_string("kev_rime/hotkey") or DEFAULT_HOTKEY)
  env.kev_python = config:get_string("kev_rime/python")
  env.kev_bridge = config:get_string("kev_rime/bridge")
  local home = os.getenv("HOME")
  if home and home ~= "" then
    env.kev_enabled_path = home .. "/.keytrack/kev-rime/enabled"
  end
  recent.reset(env)
  env.kev_commit_conn = env.engine.context.commit_notifier:connect(function(context)
    pcall(function()
      if enabled(env.kev_enabled_path) then
        recent.commit(env, context:get_commit_text())
      else
        recent.reset(env)
      end
    end)
  end)
end

function M.func(key, env)
  local key_ok, released, repr = pcall(function()
    return key:release(), key:repr()
  end)
  if not key_ok then return kNoop end
  if not released and normalized_chord(repr) == (env.kev_hotkey or DEFAULT_HOTKEY) then
    if not enabled(env.kev_enabled_path) then recent.reset(env); return kNoop end
    local ok, handled = pcall(rerank, env)
    return ok and handled and kAccepted or kNoop
  end
  -- Never refresh or consume a normal key, even when Kev was unavailable.
  if not released then pcall(recent.key, env, repr) end
  pcall(clear_stale_choice, env.engine.context)
  return kNoop
end

function M.fini(env)
  if env.kev_commit_conn then env.kev_commit_conn:disconnect() end
  recent.reset(env)
end

return M
