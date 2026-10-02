-- User-authored snippets; explicit short codes, no model or clipboard access.
local M = {}
function M.init(env)
  local path = rime_api.get_user_data_dir() .. "/lua/keytrack_phrases_data.lua"
  local loader = loadfile(path)
  local ok, items = pcall(function() return loader and loader() or {} end)
  env.keytrack_phrases = ok and type(items) == "table" and items or {}
end
function M.func(input, segment, env)
  if segment.start ~= 0 or segment._end ~= #input then return end
  for _, item in ipairs(env.keytrack_phrases or {}) do
    if item.code == input then
      local candidate = Candidate("keytrack_phrase", segment.start, segment._end, item.text, item.category)
      candidate.quality = 100
      yield(candidate)
    end
  end
end
return M
