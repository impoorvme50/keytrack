-- keytrack-local-prediction: mark and strictly cap locally computed candidates.
local M = {}

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
end

function M.func(input, env)
  local on, maximum = controls(env)
  local count = 0
  local segment = env.engine.context.composition:back()
  -- Existing Emoji/OpenCC filters may wrap and change the candidate type.
  -- The native prediction segment is authoritative, including those wrappers.
  local prediction_segment = segment and segment:has_tag("prediction")
  for candidate in input:iter() do
    if prediction_segment or candidate.type == "prediction" then
      if on and count < maximum then
        count = count + 1
        yield(ShadowCandidate(candidate, "prediction", candidate.text, "联想 · 数字/Tab"))
      end
    else
      yield(candidate)
    end
  end
end

return M
