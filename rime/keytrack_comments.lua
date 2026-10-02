-- Optional local glossary comments. No processor, history access or writes.
local M = {}
local glossary, loaded
local annotated = setmetatable({}, { __mode = "k" })
local MAX_ITEMS, MAX_GLOSS, MAX_COMMENT = 64, 24, 64

local function length(value)
  local ok, count = pcall(utf8.len, value)
  return ok and count or nil
end

local function component(value, language)
  if type(value) ~= "string" or value == "" then return nil end
  local full = (language == "en" and "EN:" or "日:") .. value
  local count = length(full)
  if not count then return nil end
  if count <= MAX_GLOSS then return full end
  return full:sub(1, utf8.offset(full, MAX_GLOSS) - 1) .. "…"
end

local function ends_with_component(comment, part)
  return comment == part or comment:sub(-#(" · " .. part)) == " · " .. part
end

local function append(comment, part)
  if not part or part == "" or ends_with_component(comment, part) then return comment end
  return comment == "" and part or comment .. " · " .. part
end

-- Mandatory hints and original comments have priority over the optional gloss.
function M.compose(comment, mandatory, gloss)
  local result = append(comment or "", mandatory)
  if gloss then
    local proposed = append(result, gloss)
    local count = length(proposed)
    if count and count <= MAX_COMMENT then result = proposed end
  end
  return result
end

function M.init(env)
  if not loaded then
    loaded = true
    local ok, values = pcall(require, "keytrack_glossary")
    if ok and type(values) == "table" then glossary = values end
  end
  env.keytrack_comments = { language = "off", seen = 0 }
end

function M.begin_round(env)
  local state = env.keytrack_comments
  if not state then return end
  state.seen = 0
  -- Rime's already-loaded configuration cannot block on a FIFO/control file.
  -- The UI persists language and redeploys; the key path never reads that file.
  local ok, language = pcall(function()
    return env.engine.schema.config:get_string("keytrack_glossary/language")
  end)
  state.language = ok and type(language) == "string"
    and (language == "en" or language == "ja") and language or "off"
end

function M.decorate(candidate, env, options)
  options = options or {}
  local state = env.keytrack_comments
  local permitted = false
  if options.glossary ~= false and state and state.language ~= "off" and glossary then
    state.seen = state.seen + 1
    permitted = state.seen <= MAX_ITEMS
    if not permitted and not options.mandatory then return candidate end
  end
  local comment = candidate.comment or ""
  local previous = annotated[candidate]
  -- Only remove a suffix for which this module retains the exact original.
  -- Similar user-authored comments are never parsed or stripped.
  local original = candidate
  if previous and previous.text == candidate.text and previous.rendered == comment
      and (permitted or not state or state.language == "off") then
    comment, original = previous.comment, previous.original
  end
  local gloss
  if permitted then
    -- Deliberately do not inspect get_genuine(), suffixes or segmentation.
    local entry = rawget(glossary, candidate.text)
    if type(entry) == "table" then
      gloss = component(rawget(entry, state.language), state.language)
    end
  end
  local rendered = M.compose(comment, options.mandatory, gloss)
  if rendered == (candidate.comment or "") then return candidate end
  if rendered == (original.comment or "") and original.type == candidate.type
      and original.text == candidate.text then return original end
  local ok, shadow = pcall(ShadowCandidate, candidate, candidate.type, candidate.text, rendered)
  if not ok or type(shadow) ~= type(candidate) then return candidate end
  -- ShadowCandidate normally inherits quality; keep that contract explicit.
  local quality_ok = pcall(function() shadow.quality = candidate.quality end)
  if not quality_ok then return candidate end
  annotated[shadow] = {
    original = original, comment = comment, rendered = rendered, text = candidate.text,
  }
  return shadow
end

return M
