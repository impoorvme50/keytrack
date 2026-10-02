-- Isolated mock contracts; no user history, engine deploy or real HOME access.
local root, home = assert(arg[1]), assert(arg[2])
package.path = root .. "/rime/?.lua;" .. package.path
local getenv = os.getenv
os.getenv = function(name) if name == "HOME" then return home end; return getenv(name) end
local configured_language
local configuration = {get_string=function(_, key)
  assert(key == "keytrack_glossary/language", "unexpected config key")
  return configured_language
end}
local function gloss_env() return {engine={schema={config=configuration}}} end
local function write(path, text)
  local file = assert(io.open(path, "w")); file:write(text); file:close()
end
local function mode(language) configured_language = language end
local dictionary = {
  ["你好"] = { en = "hello", ja = "こんにちは" },
  ["世界"] = { en = "world", ja = "世界（せかい）" },
  ["甲"] = { en = string.rep("🙂", 30), ja = string.rep("字", 30) },
}
local loads = 0
local function module(loader)
  package.loaded.keytrack_comments, package.loaded.keytrack_glossary = nil, nil
  package.preload.keytrack_glossary = loader or function() loads = loads + 1; return dictionary end
  return require("keytrack_comments")
end
local function candidate(text, comment, kind)
  return { text = text or "你好", comment = comment or "", type = kind or "probe",
    quality = 7.5, start = 0, _end = 5 }
end
ShadowCandidate = function(original, kind, text, comment)
  return { type = kind, text = text, comment = comment, quality = original.quality,
    start = original.start, _end = original._end, original = original }
end
local function same(a, b)
  assert(a.text == b.text and a.type == b.type and a.quality == b.quality)
  assert(a.start == b.start and a._end == b._end)
end
local cases = 0
local function test(name, fn)
  local ok, err = xpcall(fn, debug.traceback)
  assert(ok, name .. ": " .. tostring(err)); cases = cases + 1
end
test("off preserves exact object without a config value", function()
  mode(nil)
  local m, env = module(), gloss_env(); m.init(env); m.begin_round(env)
  local c = candidate("你好", "原注释 ✦ AI")
  assert(m.decorate(c, env) == c)
  mode("off"); m.begin_round(env); assert(m.decorate(c, env) == c)
end)
test("single table load and live language switch", function()
  loads = 0
  local m, env, second = module(), gloss_env(), {}; m.init(env); m.init(second); assert(loads == 1)
  local c = candidate("你好", "原注释")
  mode("en"); m.begin_round(env)
  local en = m.decorate(c, env); same(en, c); assert(en.comment == "原注释 · EN:hello")
  assert(m.decorate(en, env) == en)
  mode("ja"); m.begin_round(env)
  local ja = m.decorate(en, env); same(ja, c); assert(ja.comment == "原注释 · 日:こんにちは")
  mode("off"); m.begin_round(env); assert(m.decorate(ja, env) == c)
end)
test("missing, bad type, invalid or failing in-memory config disables", function()
  local m, env = module(), gloss_env(); m.init(env)
  for _, text in ipairs({"EN", "en\n", "ja\r\n", "ja\n\n", " en", "language=en\n",
      string.rep("x", 65), "off", "", false, 7, {}}) do
    mode(text); m.begin_round(env); local c = candidate(); assert(m.decorate(c, env) == c, text)
  end
  for _, bad_env in ipairs({{}, {engine={}}, {engine={schema={}}},
      {engine={schema={config={get_string=function() error("bad config") end}}}}}) do
    m.init(bad_env); m.begin_round(bad_env); local c=candidate(); assert(m.decorate(c,bad_env)==c)
  end
end)
test("missing and corrupt tables fail open, cached once", function()
  for _, loader in ipairs({function() error("missing") end, function() return false end}) do
    local m, env = module(loader), gloss_env(); m.init(env)
    mode("en"); m.begin_round(env)
    local c = candidate("你好", "原注释"); assert(m.decorate(c, env) == c)
    package.loaded.keytrack_glossary = dictionary
    m.init({}); assert(m.decorate(c, env) == c)
    assert(m.decorate(c, env, {mandatory="联想 · 数字/Tab"}).comment == "原注释 · 联想 · 数字/Tab")
  end
end)
test("64 examined candidate cap resets and unmatched still count", function()
  local m, env = module(), gloss_env(); m.init(env); mode("en"); m.begin_round(env)
  for index = 1, 70 do
    local c = candidate(); local out = m.decorate(c, env)
    assert((index <= 64 and out.comment == "EN:hello") or (index > 64 and out == c))
  end
  m.begin_round(env); assert(m.decorate(candidate(), env).comment == "EN:hello")
  m.begin_round(env)
  for _ = 1, 64 do local c = candidate("无匹配"); assert(m.decorate(c, env) == c) end
  local c = candidate(); assert(m.decorate(c, env) == c)
end)
test("Unicode component and whole-comment limits preserve mandatory", function()
  local m, env = module(), gloss_env(); m.init(env); mode("en"); m.begin_round(env)
  local out = m.decorate(candidate("甲"), env)
  assert(utf8.len(out.comment) == 24 and out.comment == "EN:" .. string.rep("🙂", 20) .. "…")
  local original = string.rep("字", 64) .. "  ✦ AI"
  out = m.decorate(candidate("你好", original), env, {mandatory="联想 · 数字/Tab"})
  assert(out.comment == original .. " · 联想 · 数字/Tab")
  local c = candidate("你好", string.rep("🙂", 60)); assert(m.decorate(c, env) == c)
  c = candidate("你好", "用户的 EN:hello"); out = m.decorate(c, env)
  assert(out.comment:sub(1, #c.comment) == c.comment)
  c = candidate("你好", "用户 · EN:hello"); assert(m.decorate(c, env) == c)
end)
test("invalid Unicode and malformed entries fail open", function()
  local m, env = module(function() return { ["你好"]={en="\255"}, ["世界"]={en=42} } end), gloss_env()
  m.init(env); mode("en"); m.begin_round(env)
  for _, text in ipairs({"你好", "世界"}) do local c=candidate(text); assert(m.decorate(c, env)==c) end
end)
test("exact current wrapper text without genuine or suffix fallback", function()
  local m, env = module(), gloss_env(); m.init(env); mode("en"); m.begin_round(env)
  for _, text in ipairs({"你好🙂", "前文你好", "世界🌍", "你好世界", "Hello"}) do
    local c = candidate(text, "Emoji", "emoji")
    c.get_genuine = function() error("must not inspect original text") end
    assert(m.decorate(c, env) == c)
  end
  local c = candidate("世界", "转换", "simplified")
  local out=m.decorate(c, env); same(c,out); assert(out.comment=="转换 · EN:world")
end)
test("memory-only hot path does not open FIFO control or start a process", function()
  local m, env = module(), gloss_env(); m.init(env)
  local open, popen, execute = io.open, io.popen, os.execute
  io.open = function(path) error("unexpected file open: " .. tostring(path)) end
  io.popen = function() error("unexpected process") end
  os.execute = function() error("unexpected process") end
  local ok, error_message = xpcall(function()
    for _, language in ipairs({"off", "en"}) do
      mode(language); m.begin_round(env)
      local c=candidate(); local out=m.decorate(c,env)
      assert(language=="off" and out==c or language=="en" and out.comment=="EN:hello")
    end
  end, debug.traceback)
  io.open, io.popen, os.execute = open, popen, execute
  assert(ok,error_message)
end)
local function filter_run(filter, env, candidates)
  local input = {}
  function input:iter()
    local index, previous = 0, nil
    return function(state, control_value)
      assert(state == self and control_value == previous, "iterator state/control lost")
      index = index + 1; previous = candidates[index]; return previous
    end, self, nil
  end
  local outputs = {}
  yield = function(value) outputs[#outputs + 1] = value end
  filter.func(input, env); return outputs
end
local function environment(prediction)
  local props = {}
  local context = { input="nihao", commit_history={latest_text=function() return "" end},
    composition={back=function() return {has_tag=function(_,tag) return prediction and tag=="prediction" end} end} }
  function context:get_property(key) return props[key] or "" end
  function context:set_property(key, value) props[key]=value end
  return {engine={context=context,schema={config=configuration}}}, props
end
test("Kev disabled and ordinary input preserve state/order/count/identity", function()
  module(); mode("off")
  local filter, env = dofile(root .. "/rime/kev_filter.lua"), environment(false); filter.init(env)
  local input={}; for _=1,80 do input[#input+1]=candidate() end
  local outputs=filter_run(filter,env,input); assert(#outputs==#input)
  for i,c in ipairs(outputs) do assert(c==input[i]) end
  mode("en"); outputs=filter_run(filter,env,input)
  for i,c in ipairs(outputs) do same(c,input[i]); assert(i>64 and c==input[i] or i<=64 and c.comment=="EN:hello") end
end)
test("AI combines once; prediction final filter preserves wrapper and hint", function()
  module(); mode("en"); write(home .. "/.keytrack/kev-rime/enabled", "1\n")
  write(home .. "/.keytrack/prediction/control", "enabled=1\nmax_candidates=3\nmax_iterations=1\n")
  local kev, prediction = dofile(root.."/rime/kev_filter.lua"), dofile(root.."/rime/prediction_filter.lua")
  local env, props=environment(false); kev.init(env)
  props.kev_rime_input="nihao"; props.kev_rime_choice="世界"; props.kev_rime_adopt="1"
  local ordinary=filter_run(kev,env,{candidate("你好"),candidate("世界","原注释")})
  assert(ordinary[1].comment=="原注释  ✦ AI · EN:world")
  local final_env=environment(false); prediction.init(final_env)
  local final=filter_run(prediction,final_env,ordinary); assert(final[1]==ordinary[1] and final[2]==ordinary[2])
  env, props=environment(true); kev.init(env)
  props.kev_rime_input="nihao"; props.kev_rime_choice="世界"; props.kev_rime_adopt="1"
  local upstream=filter_run(kev,env,{candidate("你好","转换","simplified"),candidate("世界","转换","simplified")})
  assert(upstream[1].comment=="转换  ✦ AI")
  final_env=environment(true); prediction.init(final_env)
  final=filter_run(prediction,final_env,upstream)
  assert(final[1].comment=="转换  ✦ AI · 联想 · 数字/Tab · EN:world")
  assert(final[1].text==upstream[1].text and final[1].quality==upstream[1].quality)
  assert(final[1].type=="prediction") -- prior one-round iteration contract
end)
test("prediction caps and fail-open missing/broken module", function()
  local save_preload=package.preload.keytrack_comments
  for _, loader in ipairs({function() error("missing") end, function() return true end,
      function() return {init=function() error("broken") end, begin_round=function() end,
        decorate=function() error("must not run") end} end}) do
    package.loaded.keytrack_comments=nil; package.preload.keytrack_comments=loader
    local kev, prediction=dofile(root.."/rime/kev_filter.lua"),dofile(root.."/rime/prediction_filter.lua")
    local env=environment(false); kev.init(env); local c=candidate("你好","原注释")
    assert(filter_run(kev,env,{c})[1]==c)
    env=environment(true); prediction.init(env)
    local out=filter_run(prediction,env,{c,c,c,c,c,c}); assert(#out==3)
    assert(out[1].comment=="原注释 · 联想 · 数字/Tab")
    assert(out[1].text==c.text and out[1].quality==c.quality and out[1].type=="prediction")
  end
  package.preload.keytrack_comments=save_preload; package.loaded.keytrack_comments=nil
end)
test("bad decorators cannot drop or mutate ordinary candidates", function()
  local save_preload=package.preload.keytrack_comments
  for _, result in ipairs({false, 7, "broken", {}, candidate("错字"),
      {text="你好",type="changed",quality=7.5,comment="bad"},
      {text="你好",type="probe",quality=1,comment="bad"}}) do
    package.loaded.keytrack_comments=nil
    package.preload.keytrack_comments=function() return {init=function() end, begin_round=function() end,
      decorate=function() return result end} end
    local kev=dofile(root.."/rime/kev_filter.lua"); local env=environment(false); kev.init(env)
    local c=candidate("你好","原注释")
    assert(filter_run(kev,env,{c})[1]==c)
    local prediction=dofile(root.."/rime/prediction_filter.lua"); env=environment(true); prediction.init(env)
    local output=filter_run(prediction,env,{c,c,c,c}); assert(#output==3)
    assert(output[1].comment=="原注释 · 联想 · 数字/Tab")
  end
  package.preload.keytrack_comments=save_preload; package.loaded.keytrack_comments=nil
end)
print("Keytrack comments Lua mock passed: " .. cases .. " contracts")
