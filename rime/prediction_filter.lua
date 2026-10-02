-- keytrack-local-prediction: mark and strictly cap locally computed candidates.
local M = {}
local MANDATORY = "联想 · 数字/Tab"

local function decorate(candidate, env)
  local comments = env.keytrack_comments_module
  if comments then
    local ok, decorated = pcall(comments.decorate, candidate, env, { mandatory = MANDATORY })
    if ok and type(decorated) == type(candidate) then
      local valid, marked = pcall(function()
        return decorated.type == candidate.type and decorated.text == candidate.text
          and decorated.quality == candidate.quality
          and type(decorated.comment) == "string" and decorated.comment:find(MANDATORY, 1, true)
      end)
      if valid and marked then return decorated end
    end
  end
  -- A missing/broken optional module must still preserve the selection hint.
  local comment = candidate.comment or ""
  if comment == MANDATORY or comment:sub(-#(" · " .. MANDATORY)) == " · " .. MANDATORY then
    return candidate
  end
  comment = comment == "" and MANDATORY or comment .. " · " .. MANDATORY
  return ShadowCandidate(candidate, candidate.type, candidate.text, comment)
end

local function controls(env)
  local f = io.open(env.control_path, "r")
  if not f then return false, 3 end
  local data = f:read(96) or ""
  f:close()
  local count = tonumber(data:match("^enabled=1\nmax_candidates=([1-5])\nmax_iterations=1\n$"))
  return count ~= nil, count or 3
end

function M.init(env)
  env.control_path = (os.getenv("HOME") or "") .. "/.keytrack/prediction/control"
  env.keytrack_comments_module = nil
  local ok, comments = pcall(require, "keytrack_comments")
  if ok and type(comments) == "table" and type(comments.init) == "function"
      and type(comments.begin_round) == "function" and type(comments.decorate) == "function"
      and pcall(comments.init, env) then
    env.keytrack_comments_module = comments
  end
end

function M.func(input, env)
  local on, maximum = controls(env)
  local count = 0
  local segment = env.engine.context.composition:back()
  -- Existing Emoji/OpenCC filters may wrap and change the candidate type.
  -- The native prediction segment is authoritative, including those wrappers.
  local prediction_segment = segment and segment:has_tag("prediction")
  if env.keytrack_comments_module then
    if not pcall(env.keytrack_comments_module.begin_round, env) then
      env.keytrack_comments_module = nil
    end
  end
  for candidate in input:iter() do
    if prediction_segment or candidate.type == "prediction" then
      if on and count < maximum then
        count = count + 1
        -- Existing predictor iteration accounting depends on this type. Keep
        -- the pre-glossary normalization even after Emoji/OpenCC wrappers.
        local normalized = candidate
        if candidate.type ~= "prediction" then
          normalized = ShadowCandidate(candidate, "prediction", candidate.text, candidate.comment or "")
        end
        yield(decorate(normalized, env))
      end
    else
      yield(candidate)
    end
  end
end

return M
