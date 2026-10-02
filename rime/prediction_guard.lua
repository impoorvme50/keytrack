-- keytrack-local-prediction: keep post-commit menus explicitly selectable.
-- No subprocess, network, personal-history read or model work in the key path.
local M = {}
local kAccepted, kNoop = 1, 2

local function enabled(env)
  local f = io.open(env.control_path, "r")
  if not f then return false end
  local data = f:read(96) or ""
  f:close()
  return data:match("^enabled=1\nmax_candidates=[1-5]\nmax_iterations=1\n$") ~= nil
end

local function active(context)
  local segment = context.composition:back()
  return segment and segment:has_tag("prediction")
end

local function dismiss(context)
  -- Clear with prediction disabled: upstream otherwise recreates the same menu.
  context:set_option("prediction", false)
  context:clear()
end

function M.init(env)
  env.control_path = (os.getenv("HOME") or "") .. "/.keytrack/prediction/control"
  env.engine.context:set_option("prediction", false)
end

function M.func(key, env)
  if key:release() then return kNoop end
  local context = env.engine.context
  local is_active = active(context)
  if not enabled(env) then
    if is_active then dismiss(context) else context:set_option("prediction", false) end
    return kNoop
  end
  local repr = key:repr()
  if is_active then
    if repr == "Escape" or repr == "BackSpace" then
      dismiss(context)
      return kAccepted
    end
    if repr == "Tab" then
      -- Native commit keeps the prediction type, respecting max_iterations=1.
      context:commit()
      return kAccepted
    end
    if repr:match("^[1-5]$") then
      local segment = context.composition:back()
      local candidate = segment.menu and segment.menu:get_candidate_at(tonumber(repr) - 1)
      if candidate then return kNoop end
      -- An unavailable label must not select the highlighted prediction.
      dismiss(context)
      return kNoop
    end
    if repr == "Up" or repr == "Down" then return kNoop end
    -- Letters start a fresh composition. Space/punctuation/shortcuts first
    -- dismiss and then pass to ordinary Rime/application processing.
    dismiss(context)
  end
  if repr:match("^[a-z]$") and not context:get_option("ascii_mode") then
    context:set_option("prediction", true)
  elseif context:get_option("ascii_mode") then
    context:set_option("prediction", false)
  end
  return kNoop
end

return M
