'use strict';
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const number = (value) => Number(value || 0).toLocaleString('zh-CN');
const tokenFromURL = new URLSearchParams(location.hash.slice(1)).get('token');
if (tokenFromURL) { sessionStorage.setItem('keytrack-token', tokenFromURL); history.replaceState(null, '', '/'); }
const token = sessionStorage.getItem('keytrack-token') || '';
let state, report, page = 'dashboard', day, draftSettings, draftPhrases, dirty = false, phraseIndex = null, restoreID;
let toastTimer, switching = false;
const labels = { dashboard:'输入看板', phrases:'常用语', appearance:'候选外观', settings:'输入与 AI', backups:'备份与诊断' };
const accents = {existing:'#0f766e',green:'#0f766e',blue:'#2563eb',slate:'#475569'};
const clone = value => JSON.parse(JSON.stringify(value));
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.className = 'toast' + (error ? ' error' : ''); el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 4800); }
async function api(path, body) {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Keytrack-Token':token, ...(body === undefined ? {} : {'Content-Type':'application/json'}) }, ...(body === undefined ? {} : {body:JSON.stringify(body)}) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作未完成，请重试');
  return data;
}
function busy(button, yes) { if (button) { button.disabled = yes; button.setAttribute('aria-busy', String(yes)); } }
async function action(button, callback) { busy(button,true); try { await callback(); } catch(error) { toast(error.message,true); } finally { busy(button,false); } }
function status() {
  $('#demo-banner').hidden = !state.status.demo;
  $('#sidebar-status').textContent = state.status.demo ? '演示数据 · 本机配置未改动' : `${state.status.recorder.running ? '采集运行中' : '采集状态待检查'} · AI ${state.status.kev_enabled ? '开启' : '关闭'}`;
  $('#deployment').textContent = state.deployment.pending ? '等待部署' : '配置可用';
}
function setDirty() { dirty = true; const indicator = $('#dirty-indicator'); if (indicator) indicator.textContent = '尚未保存'; }
function heading(title, subtitle, actions='') { return `<div class="page-heading"><div><div class="eyebrow">${page === 'dashboard' ? 'Your input, at a glance' : 'Personal preferences'}</div><h1>${title}</h1><p class="sub">${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`; }
function metric(label, value, unit, note, icon) { return `<div class="card metric"><div class="metric-label">${label}<span class="metric-icon">${icon}</span></div><div class="metric-number">${value==null?"—":number(value)}<small>${unit}</small></div><div class="metric-foot">${note}</div></div>`; }
function chart(items, selectedDay) {
  const max = Math.max(1,...items.map(item=>item.chars));
  return `<div class="chart">${items.map(item=>`<div class="chart-col"><button class="bar ${item.day===selectedDay?'selected':''}" style="height:${Math.max(3,item.chars/max*112)}px" data-day="${item.day}" aria-label="${item.day} ${item.chars} 字" title="${item.day} · ${number(item.chars)} 字"></button><div class="chart-label">${item.day.slice(5).replace('-','/')}</div></div>`).join('')}</div>`;
}
function bars(items) { const max = Math.max(1,...items.map(item=>item.chars)); return items.length ? items.slice(0,6).map(item=>`<div class="app-row"><div class="app-label"><span>${esc(item.name)}</span><span>${number(item.chars)} 字</span></div><div class="track"><span style="width:${item.chars/max*100}%"></span></div></div>`).join('') : '<div class="empty">这一天还没有输入记录</div>'; }
function dashboard() {
  const r = report;
  const maxKey = Math.max(1,...Object.values(r.key_frequency));
  const keyRows = r.keyboard.map(row=>`<div class="keyboard-row">${row.map(([key,label,width])=>{const count=r.key_frequency[key]||0; const intensity=Math.log(count+1)/Math.log(maxKey+1);return `<div class="key" style="flex:${width};background:rgba(15,118,110,${.035+intensity*.28})" title="${esc(label||'空格')} · ${number(count)} 次">${esc(label)}</div>`;}).join('')}</div>`).join('');
  const maxHour = Math.max(1,...r.hours);
  const fingerTotal = r.fingers.reduce((total,item)=>total+item.count,0);
  const maxDay = Math.max(1,...r.calendar.map(item=>item.chars));
  $('#content').innerHTML = heading('你的输入，一目了然。','回看输入节奏，找到更舒服的工作习惯。',`<button class="button secondary" id="today-button">今天</button><input type="date" aria-label="选择日期" id="day-picker" value="${esc(day)}">`) +
    `<section class="card full"><h2>${r.key_quality.reliable?'采集范围':'按键统计待完善'}</h2><p>${esc(r.key_quality.message)}</p><p class="sub">${esc(r.key_quality.scope)}</p>${r.key_quality.first_verified_minute?`<p class="sub">修复后采集始于 ${esc(r.key_quality.first_verified_minute.replace('T',' '))}；更早的漏采无法补回。</p>`:''}</section>`+
    `<div class="metrics">${metric('上屏文字',r.total_chars,'字',`${number(r.segment_count)} 个输入片段`,'✎')}${metric('输入速度',r.cpm,'字 / 分','按有按键记录的活跃分钟计算','↗')}${metric('活跃时间',r.active_minutes,'分钟','有按键记录的分钟数','◷')}${metric('退格占比',r.correction_rate,'%',`${number(r.total_keys)} 次按键`,'⌫')}</div>` +
    `<div class="dashboard-grid"><section class="card"><div class="card-header"><h2>最近两周</h2><span class="sub">上屏字数 · 点击查看当天</span></div>${chart(r.trend,day)}<div class="range-note">输入法上屏记录，不包含粘贴和其他输入法的文字。</div></section><section class="card"><div class="card-header"><h2>在哪里输入</h2><span class="sub">${esc(day)}</span></div>${bars(r.apps)}</section></div>`+
    `<div class="two-col"><section class="card"><div class="card-header"><h2>输入日历</h2><span class="sub">最近 91 天</span></div><div class="calendar">${r.calendar.map(item=>`<button class="day-cell" data-day="${item.day}" style="background:rgba(15,118,110,${item.chars?.12+.7*Math.sqrt(item.chars/maxDay):.055})" aria-label="${item.day} ${item.chars} 字" title="${item.day} · ${number(item.chars)} 字"></button>`).join('')}</div><div class="calendar-bottom"><span>每一天的积累，都看得见</span><span class="legend">少<i style="opacity:.3"></i><i style="opacity:.6"></i><i></i>多</span></div></section><section class="card"><div class="card-header"><h2>一天的节奏</h2><span class="sub">按小时统计按键</span></div><div class="chart hour-chart">${r.hours.length?"":`<p class="sub">${esc(r.key_quality.message)}</p>`}${r.hours.map((count,hour)=>`<div class="chart-col"><div class="bar" style="height:${Math.max(3,count/maxHour*58)}px" title="${hour}:00 · ${count} 次"></div>${hour%4===0?`<div class="chart-label">${hour}:00</div>`:'<div class="chart-label">&nbsp;</div>'}</div>`).join('')}</div></section></div>`+
    `<section class="card full"><div class="card-header"><h2>键盘热力图</h2><span class="sub">已映射 ${number(r.key_quality.mapped_keys)} 次 · 布局外 ${number(r.key_quality.unmapped_keys)} 次</span></div><div class="keyboard">${keyRows}</div>${r.key_quality.reliable?"":`<p class="sub">仅展示已收到的按键；浅色不代表没有按过。</p>`}</section>`+
    `<section class="card full"><div class="card-header"><h2>按标准指法估算的按键分布</h2><span class="sub">仅以布局内按键为分母</span></div><div class="finger-list">${fingerTotal?"":`<p class="sub">${esc(r.key_quality.reliable?"没有可映射到键盘布局的按键":r.key_quality.message)}</p>`}${r.fingers.map(item=>`<div class="finger"><span>${esc(item.name)}</span><strong>${fingerTotal?(item.count/fingerTotal*100).toFixed(1):0}%</strong></div>`).join('')}</div></section>`+
    `<section class="card full"><div class="text-gate"><div><h2>当天输入回看</h2><p>默认不展示原文。展开后，只在这个本地窗口里读取与显示。</p></div><button class="button secondary" id="text-toggle">${r.segments===null?'展开输入原文':'收起输入原文'}</button></div><div id="segments">${r.segments===null?'':segmentHTML(r)}</div></section>`;
}
function segmentHTML(r) { return r.segments.length ? `${r.segment_count>r.segment_limit?'<p class="sub">仅显示最近 500 个片段。</p>':''}${r.segments.map(item=>`<div class="segment"><div class="segment-meta"><span>${esc(item.time)}</span><span>${esc(item.app)}</span></div><pre>${esc(item.text)}</pre></div>`).join('')}` : '<div class="empty">这一天没有上屏文字</div>'; }
function themesHTML() { return `<div class="theme-grid">${[['existing','保留当前','#0f766e','不更换现有配色'],['green','青绿','#0f766e','安静、清晰'],['blue','海蓝','#2563eb','明快、易辨认'],['slate','石墨','#475569','克制、低饱和']].map(([id,name,color,note])=>`<button class="theme-tile" data-theme="${id}" aria-pressed="${draftSettings.theme===id}"><span class="swatch"><i style="background:${color}"></i><i style="background:#edf3f0"></i><i style="background:#c2d8d0"></i></span><strong>${name}</strong><small>${note}</small></button>`).join('')}</div>`; }
function saveActions() { return `<span class="dirty" id="dirty-indicator">${dirty?'尚未保存':''}</span><button class="button primary" id="save-settings">保存并应用</button>`; }
function appearance() {
  $('#content').innerHTML = heading('让候选窗更顺眼。','调整字体、布局与配色，在保存前先看效果。',saveActions())+
    `<section class="card full"><div class="card-header"><h2>候选窗预览</h2><select aria-label="预览模式" id="preview-mode"><option value="light">浅色模式</option><option value="dark">深色模式</option></select></div><div class="preview-stage"><div class="candidate-preview" id="candidate-preview"><div class="candidate-code">ni hao · 你好</div><div class="candidate-items"><span class="candidate selected"><span class="number">1</span>你好<span class="comment">✦ AI</span></span><span class="candidate"><span class="number">2</span>拟好</span><span class="candidate"><span class="number">3</span>你号<span class="comment">ni hao</span></span><span class="candidate"><span class="number">4</span>你</span></div></div></div><p class="preview-note">布局示意，实际候选窗由鼠须管绘制；“保留当前”预览使用青绿示意。</p></section>`+
    `<section class="card full"><h2>配色方案</h2>${themesHTML()}</section><section class="card full"><div class="card-header"><h2>字体与布局</h2><span class="sub">浅色 / 深色随系统外观切换</span></div><div class="form-grid"><label>候选字号<input id="font-size" type="range" min="12" max="28" value="${draftSettings.font_size}"><small id="font-size-label">${draftSettings.font_size} pt</small></label><label>注释字号<input id="comment-size" type="range" min="10" max="24" value="${draftSettings.comment_size}"><small id="comment-size-label">${draftSettings.comment_size} pt</small></label><label>排列方向<select id="layout"><option value="horizontal" ${draftSettings.layout==='horizontal'?'selected':''}>横排 · 一行展开</option><option value="vertical" ${draftSettings.layout==='vertical'?'selected':''}>竖排 · 逐行显示</option></select></label><label>候选间距<select id="density"><option value="comfortable" ${draftSettings.density==='comfortable'?'selected':''}>舒适</option><option value="compact" ${draftSettings.density==='compact'?'selected':''}>紧凑</option></select></label></div></section>`;
  updatePreview();
}
function updatePreview() {
  const el = $('#candidate-preview'); if (!el) return;
  const dark = $('#preview-mode').value === 'dark';
  let accent = accents[draftSettings.theme]; if(dark) accent={green:'#14b8a6',existing:'#14b8a6',blue:'#60a5fa',slate:'#94a3b8'}[draftSettings.theme];
  el.classList.toggle('vertical',draftSettings.layout==='vertical'); el.style.background=dark?'#19232b':'#f9fbfa';el.style.color=dark?'#f1f5f9':'#172d2b';
  el.querySelectorAll('.candidate').forEach(candidate=>{candidate.style.fontSize=draftSettings.font_size+'px';candidate.style.padding=draftSettings.density==='compact'?'4px 7px':'7px 11px';});
  el.querySelectorAll('.comment').forEach(comment=>comment.style.fontSize=draftSettings.comment_size+'px');
  el.querySelector('.selected').style.background=accent; el.querySelector('.selected').style.color=dark?'#102a2a':'#fff';
}
function settings() {
  $('#content').innerHTML = heading('输入习惯，由你决定。','AI 按需调用，日常输入继续交给鼠须管。',saveActions())+
    `<section class="card full"><h2>AI 候选建议</h2><div class="form-row"><div><h3>开启 Kev 建议</h3><p>开启后也只在按快捷键时请求模型；再次按可撤销。</p></div><label class="switch"><input id="kev-switch" type="checkbox" aria-label="开启 Kev 建议" ${state.status.kev_enabled?'checked':''}><span class="switch-visual"></span></label></div><div class="form-row"><div><h3>调用快捷键</h3><p>修改后重新部署生效；避免与常用应用快捷键冲突。</p></div><select id="hotkey" aria-label="AI 调用快捷键">${[['Control+Shift+k','⌃ ⇧ K'],['Control+Alt+k','⌃ ⌥ K'],['Control+Alt+j','⌃ ⌥ J']].map(([value,label])=>`<option value="${value}" ${draftSettings.hotkey===value?'selected':''}>${label}</option>`).join('')}</select></div><div class="form-row"><div><h3>模型运行位置</h3><p>只连接本机模型服务；关闭建议时会停止本项目的常驻模型。</p></div><span class="code">127.0.0.1:8009</span></div></section>`+
    `<section class="card full"><div class="card-header"><h2>应用默认中英文</h2><button id="add-app" class="button secondary">＋ 添加应用</button></div><p class="sub">填写应用标识，例如 com.apple.Terminal。会保留未在这里管理的原有设置。</p><div id="app-rows">${appRows()}</div></section><div class="notice">只改当前控制台管理的设置。每次保存都会备份，重新部署不会改动输入历史。</div>`;
}
function appRows() { return draftSettings.apps.map((app,index)=>`<div class="app-settings-row" data-app-index="${index}"><input aria-label="应用标识 ${index+1}" class="app-bundle" value="${esc(app.bundle)}" placeholder="com.apple.Terminal"><select aria-label="默认语言 ${index+1}" class="app-language"><option value="true" ${app.english?'selected':''}>默认英文</option><option value="false" ${!app.english?'selected':''}>默认中文</option></select><button class="icon-button" data-remove-app="${index}" aria-label="移除应用 ${index+1}">×</button></div>`).join('') || '<div class="empty">还没有自定义应用规则</div>'; }
function collectApps() { if($('#app-rows')) draftSettings.apps=[...document.querySelectorAll('[data-app-index]')].map(row=>({bundle:row.querySelector('.app-bundle').value.trim(),english:row.querySelector('.app-language').value==='true'})); }
function phrases() {
  const categories=[...new Set(draftPhrases.map(item=>item.category))];
  $('#content').innerHTML=heading('把重复输入，变成一个短编码。','常用回复、签名和地址，按分类整理。',`<span class="dirty" id="dirty-indicator">${dirty?'尚未保存':''}</span><button class="button secondary" id="add-phrase">＋ 添加</button><button class="button primary" id="save-phrases">保存并应用</button>`)+
    `<div class="notice">输入完整短编码后，内容会出现在雾凇拼音候选中，按空格上屏。原有自定义短语保持原样。</div><div class="phrase-controls"><input id="phrase-search" aria-label="搜索常用语" placeholder="搜索内容、分类或编码…"><select id="phrase-filter" aria-label="筛选分类"><option value="">所有分类</option>${categories.map(category=>`<option>${esc(category)}</option>`).join('')}</select></div><div class="phrase-list" id="phrase-list"></div>`;
  phraseList();
}
function phraseList() {
  const search = $('#phrase-search').value.trim().toLowerCase(), category = $('#phrase-filter').value;
  const items=draftPhrases.map((item,index)=>({...item,index})).filter(item=>(!category||item.category===category)&&[item.text,item.code,item.category].join(' ').toLowerCase().includes(search));
  $('#phrase-list').innerHTML=items.length?items.map(item=>`<article class="card phrase-card"><div class="phrase-top"><span class="tag">${esc(item.category)}</span><span class="code">${esc(item.code)}</span></div><div class="phrase-body">${esc(item.text)}</div><div class="phrase-actions"><button class="button text" data-copy-phrase="${item.index}">复制</button><button class="button text" data-edit-phrase="${item.index}">编辑</button><button class="button text" data-remove-phrase="${item.index}">移出列表</button></div></article>`).join(''):'<div class="card empty">'+(draftPhrases.length?'没有匹配的常用语':'添加第一条常用语，让重复输入更轻松。')+'</div>';
}
function editPhrase(index) {
  phraseIndex=index;
  const item=index===null?{category:'常用',code:'',text:''}:draftPhrases[index];
  $('#phrase-dialog-title').textContent=index===null?'添加常用语':'编辑常用语';
  $('#phrase-category').value=item.category;$('#phrase-code').value=item.code;$('#phrase-text').value=item.text;
  $('#phrase-dialog').showModal();
}
async function backups() {
  const [backups,health]=await Promise.all([api('/api/backups'),api('/api/doctor')]);
  $('#content').innerHTML=heading('设置有备份，状态看得清。','保存前自动保留版本，也可以随时手动备份。',`<button id="redeploy" class="button secondary">重新部署</button><button id="make-backup" class="button primary">立即备份</button>`)+
    `<section class="card full"><div class="card-header"><h2>当前诊断</h2><span class="sub">服务与安装检查</span></div>${health.checks.map(item=>`<div class="check-row ${esc(item.level)}"><span class="check-icon">${item.level==='ok'?'✓':item.level==='error'?'×':'!'}</span><span>${esc(item.message)}</span></div>`).join('')}<p class="preview-note">模型接口可用不代表每次推理都很快；候选窗还需要实际试打确认。</p></section><section class="card full"><div class="card-header"><h2>本机配置备份</h2><span class="sub">最近 50 份 · 不包含输入历史</span></div>${backups.backups.length?backups.backups.map(item=>`<div class="backup-row"><div><h3>${esc(item.reason)}</h3><p>${esc(new Date(item.created).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}</p></div><button class="button secondary" data-restore="${esc(item.id)}">恢复这个版本</button></div>`).join(''):'<div class="empty">还没有备份。第一次保存设置时会自动创建。</div>'}</section>`;
}
async function render() {
  $('#breadcrumb').textContent=labels[page];document.title='Keytrack · '+labels[page];
  document.querySelectorAll('[data-page]').forEach(button=>{button.classList.toggle('active',button.dataset.page===page);button.setAttribute('aria-current',button.dataset.page===page?'page':'false');});
  if(page==='dashboard'){report=await api('/api/report?day='+encodeURIComponent(day));dashboard();}
  else if(page==='phrases') phrases();else if(page==='appearance')appearance();else if(page==='settings')settings();else await backups();
}
async function loadState() {state=await api('/api/state');draftSettings=clone(state.settings);draftPhrases=clone(state.phrases);status();}
async function navigate(next) {
  if(next===page||switching)return;
  // Keep unsaved edits scoped to their screen; avoid silent loss across pages.
  if(dirty){toast('请先保存当前更改，或点击刷新放弃未保存更改。',true);return;}
  switching=true;try{page=next;await render();}finally{switching=false;}
}
async function refresh() {if(dirty){toast('请先保存当前修改，再刷新');return;}await loadState();await render();toast('已刷新本机数据');}
async function saveSettings(button) {collectApps();const result=await api('/api/settings',{settings:draftSettings,revision:state.revision});await loadState();dirty=false;await render();toast(result.message);}
async function savePhrases(button) {const result=await api('/api/phrases',{phrases:draftPhrases,revision:state.revision});await loadState();dirty=false;await render();toast(result.message);}
async function copyPhrase(index) {
  const text=draftPhrases[index].text;
  try{await navigator.clipboard.writeText(text);}catch(error){const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('无法自动复制，请选中内容后复制');}
  toast('已复制常用语');
}
document.addEventListener('click',event=>{
  const target=event.target.closest('button');if(!target)return;
  if(target.dataset.page)return action(target,()=>navigate(target.dataset.page));
  if(target.dataset.close){$('#'+target.dataset.close).close();return;}
  if(target.dataset.day)return action(target,async()=>{day=target.dataset.day;await render();});
  if(target.dataset.theme){draftSettings.theme=target.dataset.theme;setDirty();document.querySelectorAll('[data-theme]').forEach(tile=>tile.setAttribute('aria-pressed',String(tile===target)));updatePreview();return;}
  if(target.dataset.editPhrase!==undefined){editPhrase(Number(target.dataset.editPhrase));return;}
  if(target.dataset.removePhrase!==undefined){draftPhrases.splice(Number(target.dataset.removePhrase),1);setDirty();phraseList();return;}
  if(target.dataset.copyPhrase!==undefined)return action(target,()=>copyPhrase(Number(target.dataset.copyPhrase)));
  if(target.dataset.removeApp!==undefined){collectApps();draftSettings.apps.splice(Number(target.dataset.removeApp),1);setDirty();$('#app-rows').innerHTML=appRows();return;}
  if(target.dataset.restore){restoreID=target.dataset.restore;$('#confirm-dialog').showModal();return;}
  const handlers={
    refresh:refresh,
    'today-button':async()=>{day=state.today;await render();},
    'save-settings':()=>saveSettings(target),
    'save-phrases':()=>savePhrases(target),
    'add-phrase':()=>editPhrase(null),
    'add-app':()=>{collectApps();draftSettings.apps.push({bundle:'',english:true});setDirty();$('#app-rows').innerHTML=appRows();},
    'text-toggle':async()=>{if(report.segments===null)report=await api('/api/report?day='+encodeURIComponent(day)+'&text=1');else report.segments=null;dashboard();},
    'make-backup':async()=>{const result=await api('/api/backup',{});await backups();toast(result.message);},
    redeploy:async()=>{const result=await api('/api/redeploy',{});toast(result.message);},
    'confirm-restore':async()=>{const result=await api('/api/restore',{id:restoreID,revision:state.revision});$('#confirm-dialog').close();await loadState();dirty=false;await render();toast(result.message);}
  };
  if(handlers[target.id])action(target,handlers[target.id]);
});
document.addEventListener('input',event=>{
  const el=event.target;
  if(el.id==='phrase-search'){phraseList();return;}
  if(el.id==='font-size'||el.id==='comment-size'){const key=el.id==='font-size'?'font_size':'comment_size';draftSettings[key]=Number(el.value);$('#'+el.id+'-label').textContent=el.value+' pt';setDirty();updatePreview();}
  if(el.classList.contains('app-bundle'))setDirty();
});
document.addEventListener('change',event=>{
  const el=event.target;
  if(el.id==='day-picker')action(el,async()=>{day=el.value||state.today;await render();});
  if(el.id==='phrase-filter')phraseList();
  if(el.id==='preview-mode')updatePreview();
  if(['layout','density','hotkey'].includes(el.id)){draftSettings[el.id]=el.value;setDirty();updatePreview();}
  if(el.classList.contains('app-language'))setDirty();
  if(el.id==='kev-switch'){const desired=el.checked;action(el,async()=>{try{const result=await api('/api/kev',{enabled:desired});state=await api('/api/state');status();el.checked=state.status.kev_enabled;toast(result.message);}catch(error){el.checked=!desired;throw error;}});}
});
$('#phrase-form').addEventListener('submit',event=>{
  event.preventDefault();
  const item={code:$('#phrase-code').value.trim(),category:$('#phrase-category').value.trim(),text:$('#phrase-text').value};
  if(item.code.startsWith('v')||item.code.startsWith('u'))return toast('编码不要以 v 或 u 开头，它们用于特殊输入。',true);
  if(draftPhrases.some((phrase,index)=>phrase.code===item.code&&index!==phraseIndex))return toast('这个编码已存在，请使用其他编码。',true);
  if(phraseIndex===null)draftPhrases.push(item);else draftPhrases[phraseIndex]=item;
  $('#phrase-dialog').close();setDirty();const categories=[...new Set(draftPhrases.map(item=>item.category))];$('#phrase-filter').innerHTML='<option value="">所有分类</option>'+categories.map(category=>`<option>${esc(category)}</option>`).join('');phraseList();
});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
(async()=>{try{await loadState();day=state.today;await render();window.keytrackReady=true;}catch(error){$('#content').innerHTML=`<div class="card empty">${esc(error.message)}<p>请关闭此窗口，从 Keytrack 应用重新打开。</p></div>`;}})();
setInterval(async()=>{if(document.hidden||!state)return;try{const fresh=await api('/api/state');state.status=fresh.status;state.deployment=fresh.deployment;status();}catch(error){$('#deployment').textContent='连接已断开';}},15000);
