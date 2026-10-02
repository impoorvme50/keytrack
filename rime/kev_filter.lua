-- Show an explicit Kev suggestion without changing ordinary Rime input.
-- This filter only has work to do after the user presses the Kev hotkey.

local M = {}
local INPUT_PROP = "kev_rime_input"
local PREVIOUS_PROP = "kev_rime_previous"
local CHOICE_PROP = "kev_rime_choice"
local ADOPT_PROP = "kev_rime_adopt"
local STATUS_PROP = "kev_rime_status"
local MAX_CANDIDATES = 5

local function set_property(context, key, value)
  if (context:get_property(key) or "") ~= value then
    context:set_property(key, value)
  end
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
  set_property(context, INPUT_PROP, "")
  set_property(context, PREVIOUS_PROP, "")
  set_property(context, CHOICE_PROP, "")
  set_property(context, ADOPT_PROP, "")
  set_property(context, STATUS_PROP, "")
end

local function current_result(context)
  local choice = context:get_property(CHOICE_PROP) or ""
  local status = context:get_property(STATUS_PROP) or ""
  if choice == "" and status == "" then return nil end
  if (context.input or "") ~= (context:get_property(INPUT_PROP) or "")
      or (context.commit_history:latest_text() or "") ~=
        (context:get_property(PREVIOUS_PROP) or "") then
    clear_choice(context)
    return nil
  end
  return choice, (context:get_property(ADOPT_PROP) or "") == "1", status
end

local function emit(candidate, marker)
  if not marker then
    yield(candidate)
    return
  end
  local comment = candidate.comment or ""
  local marked = comment == "" and marker or comment .. "  " .. marker
  yield(ShadowCandidate(candidate, candidate.type, candidate.text, marked))
end

function M.init(env)
  local home = os.getenv("HOME")
  if home and home ~= "" then
    env.kev_enabled_path = home .. "/.keytrack/kev-rime/enabled"
  end
end

function M.func(input, env)
  local context = env.engine.context
  if not enabled(env.kev_enabled_path) then
    clear_choice(context)
    for candidate in input:iter() do yield(candidate) end
    return
  end

  local choice, adopt, status = current_result(context)
  if not choice then
    for candidate in input:iter() do yield(candidate) end
    return
  end

  local first = {}
  -- librime-lua's iterator needs its translation state on every call.
  -- Keeping only the function loses that state and empties the candidate menu.
  local next_candidate, state, control = input:iter()
  local function iterator()
    local candidate = next_candidate(state, control)
    control = candidate
    return candidate
  end
  for _ = 1, MAX_CANDIDATES do
    local candidate = iterator()
    if not candidate then break end
    first[#first + 1] = candidate
  end
  local selected
  for index, candidate in ipairs(first) do
    if candidate.text == choice then
      selected = index
      break
    end
  end
  if not selected then
    clear_choice(context)
  elseif adopt and selected > 1 then
    emit(first[selected], "✦ AI")
  end
  for index, candidate in ipairs(first) do
    if not (adopt and selected and selected > 1 and index == selected) then
      local marker = index == selected and (adopt and "✦ AI" or "✦ AI ?")
        or (index == 1 and status ~= "" and status)
        or nil
      emit(candidate, marker)
    end
  end
  for candidate in iterator do yield(candidate) end
end

return M
