-- keytrack_logger.lua — keytrack 的 RIME 采集钩子（v3）。
-- 每次上屏（commit）往 ~/.keytrack/ime_commits.jsonl 追加一行：
--     {"ts": 1753700000, "text": "上屏文字", "sch": "rime_ice"}
-- 按键按分钟聚合成桶，分钟切换时往 ~/.keytrack/ime_keys.jsonl 写一行：
--     {"min": "2026-07-28T15:04", "keys": {"a": 12, "space": 3}}
-- 只存「每分钟各键几次」，不存按键顺序时间线（隐私边界：宁少勿多）。
--
-- 以 lua_processor@*keytrack_logger 挂载（星号 = 直接从 lua/ 目录取，无需 rime.lua）。
-- func 恒返回 kNoop，绝不影响输入；任何写日志失败都被 pcall 吞掉。
-- macOS 安全输入框不经过输入法，密码天然进不了这两个文件。

local P = {}

local kNoop = 2  -- librime ProcessResult: kRejected=0, kAccepted=1, kNoop=2

local _home
local function home()
  if not _home then
    _home = os.getenv("HOME") or ""
    pcall(os.execute, 'mkdir -p "' .. _home .. '/.keytrack"')
  end
  return _home
end

local function commits_path() return home() .. "/.keytrack/ime_commits.jsonl" end
local function keys_path()    return home() .. "/.keytrack/ime_keys.jsonl" end

-- 完整的 JSON 字符串转义（上屏文字可能带换行/制表符/控制字符）。
local function json_escape(s)
  return (s:gsub('[%z\1-\31\\"]', function(c)
    if c == '"' then return '\\"' end
    if c == '\\' then return '\\\\' end
    if c == '\n' then return '\\n' end
    if c == '\r' then return '\\r' end
    if c == '\t' then return '\\t' end
    return string.format('\\u%04x', c:byte())
  end))
end

local function append_line(path, line)
  local f = io.open(path, "a")
  if f then
    pcall(f.write, f, line)
    f:close()
  end
end

-- ---- 上屏文字记录 ----

local function write_commit(env, text)
  if not text or text == "" then return end
  local schema = ""
  if env.engine and env.engine.schema then
    schema = env.engine.schema.schema_id or ""
  end
  append_line(commits_path(), string.format(
    '{"ts":%d,"text":"%s","sch":"%s"}\n',
    os.time(), json_escape(text), json_escape(schema)))
end

-- ---- 按键分钟桶 ----

local bucket_min = nil     -- 当前桶的分钟，形如 2026-07-28T15:04
local bucket_version = 2
local bucket = {}          -- 当前桶：键名 -> 次数

local function flush_bucket()
  if not bucket_min then return end
  local parts = {}
  for k, n in pairs(bucket) do
    parts[#parts + 1] = string.format('"%s":%d', json_escape(k), n)
  end
  append_line(keys_path(), string.format(
    '{"min":"%s","capture_version":%d,"keys":{%s}}\n', bucket_min, bucket_version, table.concat(parts, ",")))
  bucket_min = nil
  bucket = {}
end

local function count_key(key, version)
  local repr = key:repr()  -- 形如 "a"、"space"、"Shift+Return"
  if not repr or repr == "" then return end
  local min = os.date("%Y-%m-%dT%H:%M")
  if min ~= bucket_min or version ~= bucket_version then
    flush_bucket()         -- 跨分钟了，先把旧桶写出去
    bucket_min = min
    bucket_version = version
  end
  bucket[repr] = (bucket[repr] or 0) + 1
end

-- ---- librime-lua 接口 ----

function P.init(env)
  -- Only certify buckets when this observer precedes every consuming processor.
  env.capture_version = 2
  pcall(function()
    if env.engine.schema.config:get_string("engine/processors/@0") == "lua_processor@*keytrack_logger" then
      env.capture_version = 3
    end
  end)
  local ctx = env.engine.context
  env.commit_conn = ctx.commit_notifier:connect(function(c)
    -- pcall：记录失败绝不能影响打字。
    pcall(function()
      write_commit(env, c:get_commit_text())
    end)
  end)
end

function P.func(key, env)
  if not key:release() then  -- 只数按下，不数抬起
    pcall(count_key, key, env.capture_version)
  end
  return kNoop
end

function P.fini(env)
  pcall(flush_bucket)
  if env.commit_conn then env.commit_conn:disconnect() end
end

return P
