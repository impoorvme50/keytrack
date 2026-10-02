-- Short-lived context and decisions, owned by one Rime session. No input log reads.
local M = {}
local MAX_CHARACTERS, CONTEXT_SECONDS, CACHE_SECONDS, CACHE_LIMIT = 160, 60, 30, 8

function M.reset(env)
  env.kev_recent_text, env.kev_recent_time, env.kev_cache = "", nil, {}
end

function M.previous(env)
  local now = os.time()
  local last = env.kev_recent_time
  if last and (now < last or now - last >= CONTEXT_SECONDS) then
    M.reset(env)
  end
  return env.kev_recent_text or ""
end

function M.commit(env, text)
  if type(text) ~= "string" or text == "" then return end
  local combined = M.previous(env) .. text
  local count = utf8.len(combined)
  if not count then M.reset(env); return end
  if count > MAX_CHARACTERS then
    local start = utf8.offset(combined, count - MAX_CHARACTERS + 1)
    combined = combined:sub(start)
  end
  env.kev_recent_text, env.kev_recent_time = combined, os.time()
  env.kev_cache = {}
end

function M.lookup(env, fingerprint)
  local now = os.time()
  local cache = env.kev_cache or {}
  for index = #cache, 1, -1 do
    local entry = cache[index]
    if now < entry.time or now - entry.time >= CACHE_SECONDS then
      table.remove(cache, index)
    elseif entry.key == fingerprint then
      return entry.answer
    end
  end
end

function M.remember(env, fingerprint, answer)
  if not answer then return end -- Unavailable services must remain retryable.
  env.kev_cache = env.kev_cache or {}
  if #env.kev_cache >= CACHE_LIMIT then table.remove(env.kev_cache, 1) end
  env.kev_cache[#env.kev_cache + 1] = { key = fingerprint, answer = answer, time = os.time() }
end

-- Editing/movement means we can no longer infer text immediately before the caret.
function M.key(env, repr)
  if repr:find("Control+", 1, true) or repr:find("Super+", 1, true)
      or repr:find("Alt+", 1, true) or repr:find("Meta+", 1, true)
      or repr:match("BackSpace$") or repr:match("Delete$")
      or repr:match("Return$") or repr:match("Escape$") or repr:match("Tab$")
      or repr:match("Left$") or repr:match("Right$")
      or repr:match("Up$") or repr:match("Down$")
      or repr:match("Home$") or repr:match("End$") then
    M.reset(env)
  end
end

return M
