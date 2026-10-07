/* ==========================================================================
   Agent 拆机工坊 — 模拟器集合
   12 个交互式沙盘，全部离线运行，无外部依赖
   ========================================================================== */
(function(){
"use strict";

/* ---------- 小工具 ---------- */
function tok(s){
  if(!s) return 0;
  var cn = (s.match(/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/g)||[]).length;
  var rest = s.length - cn;
  return Math.round(cn + rest/4);
}
function $(sel, root){ return (root||document).querySelector(sel); }
function $$(sel, root){ return Array.prototype.slice.call((root||document).querySelectorAll(sel)); }
function el(html){ var d=document.createElement('div'); d.innerHTML=html.trim(); return d.firstChild; }
function fmt(n, d){ d = d===undefined?2:d; return Number(n).toFixed(d); }
function comma(n){ return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

var SIMS = {};

/* ======================================================================
   L1 · 零件拆解台
   ====================================================================== */
SIMS.anatomy = function(root){
  var parts = [
    { id:'llm', key:'LLM', cn:'大脑', color:'var(--cyan)',
      what:'一个函数：给一串 token，返回下一个 token。所有决策都由它做。',
      role:'决定 <b>能力天花板</b>。它不会的东西，上下文和工具再好也变不出来。',
      you:'对应你建模时的模型本体：选型、规模、是否支持推理，都在这一层。',
      cant:'它不会执行任何东西、不会记忆、看不到你数据库里的数据。' },
    { id:'ctx', key:'上下文', cn:'眼睛', color:'var(--amber)',
      what:'模型决策时能看到的一切：系统提示词、工具定义、用户消息、模型回复、工具结果。',
      role:'决定 <b>你能不能碰到天花板</b>。信息不在里面，模型再强也看不见。',
      you:'对应特征工程 + 数据管道。特征没进表，调参调到天亮也没用。',
      cant:'它不是长期记忆。会话结束就没了——那是 L7 的事。' },
    { id:'tool', key:'工具', cn:'手脚', color:'var(--magenta)',
      what:'Agent 能对外部世界做的动作：读文件、查库、发请求、跑代码。',
      role:'决定 <b>Agent 能改变什么</b>。没有工具，它就只是个聊天机器人。',
      you:'对应你的数据源和执行接口。查汇率、算大数、写回结果，都要靠它。',
      cant:'它不会自己判断该不该用。选择是模型做的，约束是 Harness 加的。' }
  ];
  var html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line)">';
  parts.forEach(function(p){
    html += '<div class="ana-p" data-id="'+p.id+'" style="background:var(--ink-2);padding:20px 16px;cursor:pointer;transition:.2s;border-top:3px solid '+p.color+'">'
      + '<div class="mono" style="font-size:10px;letter-spacing:.2em;color:var(--paper-3)">'+p.cn+'</div>'
      + '<div style="font-family:var(--f-display);font-size:24px;color:'+p.color+';margin:6px 0 8px">'+p.key+'</div>'
      + '<div style="font-size:12.5px;color:var(--paper-2);line-height:1.7">'+p.role+'</div></div>';
  });
  html += '</div><div class="ana-detail" style="margin-top:14px;border:1px solid var(--line);background:rgba(2,5,10,.6);padding:16px 18px;min-height:150px"></div>';
  html += '<div class="block" style="margin-top:14px;border-left-color:var(--cyan)"><span class="lbl">边界提醒</span>'
       +  '<p style="font-size:13.5px;color:var(--paper-2)">Harness 是「Agent 边界之内、模型之外」的那一层。'
       +  '<b class="hl">Environment 在边界之外</b>——哪怕工具函数和 Harness 跑在同一个进程里，它仍然属于环境。</p></div>';
  root.innerHTML = html;

  var detail = $('.ana-detail', root);
  function show(id){
    var p = parts.filter(function(x){return x.id===id;})[0];
    detail.innerHTML = '<div class="mono" style="font-size:10px;letter-spacing:.2em;color:'+p.color+';margin-bottom:8px">'
      + p.cn + ' · ' + p.key + '</div>'
      + '<p style="margin:0 0 10px;color:var(--paper)">'+p.what+'</p>'
      + '<p style="margin:0 0 6px;font-size:13.5px;color:var(--paper-2)"><b class="hl">它的职责：</b>'+p.role+'</p>'
      + '<p style="margin:0 0 6px;font-size:13.5px;color:var(--paper-2)"><b class="hl-a">对你会是：</b>'+p.you+'</p>'
      + '<p style="margin:0;font-size:13.5px;color:#ffc4da"><b>它做不到：</b>'+p.cant+'</p>';
    $$('.ana-p', root).forEach(function(n){
      n.style.background = n.dataset.id===id ? 'rgba(19,40,68,.85)' : 'var(--ink-2)';
    });
  }
  $$('.ana-p', root).forEach(function(n){ n.onclick = function(){ show(n.dataset.id); }; });
  show('llm');
};

/* ======================================================================
   L2 · ReAct 轨迹机
   ====================================================================== */
SIMS.react = function(root){
  var PREFIX_SYS = '你是一个财务分析 Agent。可以使用工具查询数据、换算汇率、执行代码。请一步步完成用户的任务，最后给出结论。';
  var PREFIX_TOOLS = '[query_finance, get_fx_rate, code_interpreter]';
  var PREFIX_TOKENS = 486;   // 系统提示词 + 工具定义的 token 数（预置）

  var SCRIPT = [
    { k:'think', r:'用户要汇总四个季度的多币种收入。我需要先拿到每个季度的原始金额和币种。',
      c:[{name:'query_finance', args:{period:'2025Q1-Q4', field:'revenue'}}], note:'第 1 轮 · 先取数' },
    { k:'obs', t:'{"Q1":"2.5M USD","Q2":"2.1M EUR","Q3":"1.8M GBP","Q4":"380M CNY"}' },
    { k:'think', r:'拿到了本币金额，但币种不同，不能直接相加。需要四个币种对 USD 的汇率。',
      c:[{name:'get_fx_rate', args:{base:'USD', quote:['EUR','GBP','CNY']}}], note:'第 2 轮 · 再取汇率' },
    { k:'obs', t:'{"USD":1.0,"EUR":1.08,"GBP":1.27,"CNY":0.138}' },
    { k:'think', r:'数据齐了。金额数量级较大、还有小数，我口算容易错，写代码算更可靠。',
      c:[{name:'code_interpreter', args:{code:'sum([2.5, 2.1*1.08, 1.8*1.27, 380*0.138])/4'}}], note:'第 3 轮 · 交给代码算' },
    { k:'obs', t:'2.9045  (单位：百万美元)' },
    { k:'final', r:'四季度金额已折算并求和，可以给结论了。',
      t:'2025 年四个季度合计约 11.62 百万美元，季度均值约 2.90 百万美元。其中 Q4 折算后贡献最大。' }
  ];

  var state = { i:0, rounds:0, traj:[], running:false, timer:null, failed:null };
  var opts = { toolDefs:true, reasoning:true, history:true, toolResult:true };

  root.innerHTML = ''
  + '<div class="ctrl">'
  + '  <button class="btn" data-a="step">▸ 单步</button>'
  + '  <button class="btn" data-a="auto">▶ 自动</button>'
  + '  <button class="btn ghost" data-a="reset">↺ 重置</button>'
  + '  <span style="flex:1"></span>'
  + '  <label><input type="checkbox" data-o="toolDefs" checked> 提供工具定义</label>'
  + '  <label><input type="checkbox" data-o="reasoning" checked> 保留思考过程</label>'
  + '  <label><input type="checkbox" data-o="history" checked> 保留历史记录</label>'
  + '  <label><input type="checkbox" data-o="toolResult" checked> 回传工具结果</label>'
  + '</div>'
  + '<div class="readout">'
  + '  <div class="cell"><div class="k">任务</div><div class="v" style="font-size:12px;line-height:1.5">四季度多币种收入汇总</div></div>'
  + '  <div class="cell"><div class="k">轮次</div><div class="v" data-r="round">0</div></div>'
  + '  <div class="cell"><div class="k">静态前缀 tokens</div><div class="v">'+PREFIX_TOKENS+'</div></div>'
  + '  <div class="cell"><div class="k">轨迹 tokens</div><div class="v" data-r="traj">0</div></div>'
  + '  <div class="cell"><div class="k">状态</div><div class="v" data-r="stat" style="font-size:14px">待启动</div></div>'
  + '</div>'
  + '<div class="log" data-r="log"></div>'
  + '<div class="block" style="border-left-color:var(--amber);margin-top:14px"><span class="lbl">观察点</span>'
  + '<p style="font-size:13.5px;color:var(--paper-2);margin:0">关掉「回传工具结果」再跑一遍，看看轮次会涨到多少；关掉「提供工具定义」，看看模型还能不能动用手脚。</p></div>';

  var logEl = $('[data-r=log]', root);
  function row(cls, i, t){
    var r = el('<div class="row '+cls+'"><span class="i">'+i+'</span><span class="t">'+t+'</span></div>');
    logEl.appendChild(r); logEl.scrollTop = logEl.scrollHeight;
  }
  function setR(k,v){ var n=$('[data-r='+k+']',root); if(n) n.textContent=v; }

  function reset(){
    if(state.timer) clearInterval(state.timer);
    state = { i:0, rounds:0, traj:[], running:false, timer:null, failed:null };
    logEl.innerHTML='';
    setR('round','0'); setR('traj','0'); setR('stat','待启动');
    $('[data-r=stat]',root).className='v';
    row('sys','SYS','静态前缀已装载：系统提示词 + 工具定义 = '+PREFIX_TOKENS+' tokens');
    row('sys','USR','用户：帮我汇总 2025 年四个季度的收入，并给出季度均值。');
    state.traj.push({role:'user', content:'帮我汇总 2025 年四个季度的收入，并给出季度均值。'});
  }

  function step(){
    if(state.failed){ row('err','✖','循环已终止：'+state.failed); return; }
    if(state.i >= SCRIPT.length){ setR('stat','已完成'); return; }

    // --- 无工具定义：模型看不到工具，直接认输 ---
    if(!opts.toolDefs && state.i===0){
      state.rounds++;
      row('sys','R'+state.rounds+'','');
      row('think','THINK', opts.reasoning ? '我需要查询财务系统和汇率数据…但是我没有可用的工具。' : '<span style="opacity:.4">（思考过程未保留）</span>');
      row('err','FAIL','无工具定义 → 模型不知道自己有工具 → 无法调用工具。');
      row('fin','END','回复：「抱歉，我无法访问财务数据。」任务失败。');
      state.failed = '无工具定义，模型无法调用任何工具';
      setR('round',state.rounds); setR('stat','✖ 失败'); $('[data-r=stat]',root).className='v bad';
      return;
    }

    var s = SCRIPT[state.i];

    if(s.k === 'obs'){
      var t = opts.toolResult ? s.t : '<span style="color:var(--red)">[工具结果未回传]</span>';
      row('obs','OBS', t);
      if(opts.toolResult) state.traj.push({role:'tool', content:s.t});
      state.i++;
      return;
    }

    // think / final
    state.rounds++;
    var rtext = opts.reasoning ? s.r : '<span style="opacity:.4">（思考过程未保留）</span>';
    row('think','R'+state.rounds,'<b>reasoning:</b> '+rtext);

    var calls = s.c || [];
    if(calls.length){
      calls.forEach(function(c){
        row('act','ACT','<b>tool_call:</b> '+c.name+'('+JSON.stringify(c.args)+')');
      });
    }
    if(s.t) row('fin','ANS', s.t);

    var shownHistory = opts.history ? state.traj.length : 1;
    var trajTok = state.traj.reduce(function(a,m){ return a + tok(m.content||'') + 12; }, 0);
    setR('traj', comma(trajTok + state.rounds*46));
    setR('round', state.rounds);

    // --- 无历史记录：每次只看最后一条 → 重复操作 ---
    if(!opts.history && calls.length){
      row('err','WARN','无历史记录 → 模型只看得到最后一条消息，不知道自己上一步做过什么 → 重复调用。');
    }
    // --- 无工具结果：结果始终为空 → 无限重试 ---
    if(!opts.toolResult && calls.length && state.i >= 4){
      if(state.rounds >= 12){
        row('err','FAIL','连续 12 轮没有拿到有效结果 → 触发熔断（最大轮次上限）。');
        row('fin','END','任务失败：盲目循环，耗尽预算。');
        state.failed = '工具结果从未回传，Agent 陷入盲目循环并触发熔断';
        setR('stat','✖ 熔断'); $('[data-r=stat]',root).className='v bad';
        return;
      }
    }
    state.traj.push({role:'assistant', reasoning:s.r, tool_calls:calls});
    state.i++;

    if(s.k==='final'){
      setR('stat','✔ 已完成'); var n=$('[data-r=stat]',root); n.className='v ok';
      row('sys','SYS','循环退出：模型回复中没有工具调用 → 任务完成，返回 content。');
    }
  }

  root.querySelector('[data-a=step]').onclick = step;
  root.querySelector('[data-a=reset]').onclick = reset;
  root.querySelector('[data-a=auto]').onclick = function(){
    if(state.timer){ clearInterval(state.timer); state.timer=null; this.textContent='▶ 自动'; return; }
    this.textContent='❚❚ 暂停';
    var self=this;
    state.timer = setInterval(function(){
      step();
      if(state.failed || state.i>=SCRIPT.length){ clearInterval(state.timer); state.timer=null; self.textContent='▶ 自动'; }
    }, 620);
  };
  $$('[data-o]', root).forEach(function(cb){
    cb.onchange = function(){ opts[cb.dataset.o] = cb.checked; reset(); };
  });
  reset();
};

/* ======================================================================
   L3 · 上下文消融台
   ====================================================================== */
SIMS.ablation = function(root){
  var rows = [
    { cfg:'完整基线',        rounds:'4',  ok:true,  why:'正常工作：每轮都能看到工具定义、思考过程、历史记录和工具结果。', tone:'ok' },
    { cfg:'无工具定义',      rounds:'1',  ok:false, why:'模型不知道存在可调用的工具 → 一次工具都没调用 → 直接认输。', tone:'bad' },
    { cfg:'无思考过程',      rounds:'6',  ok:false, why:'reasoning 被裁掉后，决策失去上下文 → 步骤跳跃、结论不连贯，最后答案算错。', tone:'bad' },
    { cfg:'无历史记录',      rounds:'9',  ok:false, why:'每轮只看得到最后一条消息 → 重复调用同一个工具 → 直到轮次上限。', tone:'warn' },
    { cfg:'无工具结果',      rounds:'12', ok:false, why:'观察结果不贴回轨迹 → 模型以为还没做 → 盲目循环 → 触发熔断。', tone:'bad' }
  ];
  var html = '<div class="ctrl"><button class="btn" data-a="run">▶ 运行全部对照</button>'
    + '<button class="btn ghost" data-a="clr">↺ 清空</button>'
    + '<span class="mono" style="font-size:10.5px;color:var(--paper-3)">（复现书中实验 1-1）</span></div>';
  html += '<table><thead><tr><th style="width:150px">上下文配置</th><th style="width:80px">轮次</th><th style="width:90px">结果</th><th>失败原因</th></tr></thead><tbody data-r="tb">';
  rows.forEach(function(r,i){
    html += '<tr data-i="'+i+'" style="opacity:.25;transition:.4s"><td><b>'+r.cfg+'</b></td><td class="mono" data-r="rd">—</td><td data-r="res">—</td><td data-r="why" style="font-size:13px">—</td></tr>';
  });
  html += '</tbody></table>';
  html += '<div class="block analogy" style="margin-top:14px"><span class="lbl">这张表的结论</span>'
       +  '<p class="txt">上下文决定 Agent 能看到什么，而 Agent 只能基于它看到的信息做决策。</p></div>';
  root.innerHTML = html;

  function fillRow(i){
    var tr = $('tr[data-i="'+i+'"]', root), r = rows[i];
    tr.style.opacity = 1;
    var res = $('[data-r=res]', tr);
    res.innerHTML = r.ok ? '<b class="hl-g">✔ 成功</b>' : '<b class="hl-m">✖ 失败</b>';
    var rd = $('[data-r=rd]', tr);
    rd.textContent = r.rounds; rd.className = 'mono v ' + (r.tone==='bad'?'bad':r.tone==='warn'?'warn':'ok');
    $('[data-r=why]', tr).innerHTML = r.why;
  }
  var t=null;
  function clearAll(){ if(t) clearInterval(t); t=null;
    $$('tbody tr', root).forEach(function(tr){ tr.style.opacity=.25;
      $('[data-r=rd]',tr).textContent='—'; $('[data-r=res]',tr).innerHTML='—'; $('[data-r=why]',tr).innerHTML='—'; });
  }
  root.querySelector('[data-a=run]').onclick = function(){
    clearAll(); var i=0;
    t = setInterval(function(){ fillRow(i++); if(i>=rows.length){ clearInterval(t); t=null; } }, 420);
  };
  root.querySelector('[data-a=clr]').onclick = clearAll;
};

/* ======================================================================
   L4 · 上下文拼装器
   ====================================================================== */
SIMS.messages = function(root){
  var items = [
    { id:'sys',  box:true,  label:'系统提示词', group:'prefix', size:210,
      val:{ role:'system', content:'你是一个财务分析 Agent。可以使用工具查询数据。请一步步完成用户的任务。' } },
    { id:'tools',box:true,  label:'工具定义',   group:'prefix', size:276,
      val:{ role:'tools', tools:[{name:'query_finance',description:'按期间查询财务字段',parameters:{period:'string',field:'string'}},{name:'get_fx_rate',description:'查询汇率',parameters:{base:'string',quote:'array'}},{name:'code_interpreter',description:'执行 Python 代码',parameters:{code:'string'}}] } },
    { id:'user', box:false, label:'用户消息',   group:'traj',   size:34,
      val:{ role:'user', content:'帮我汇总 2025 年四个季度的收入，并给出季度均值。' } },
    { id:'reason',box:true, label:'模型回复 · reasoning', group:'traj', size:52,
      val:{ role:'assistant', reasoning:'需要先拿到每个季度的原始金额和币种。' } },
    { id:'call', box:true,  label:'模型回复 · tool_calls', group:'traj', size:38,
      val:{ tool_calls:[{name:'query_finance', args:{period:'2025Q1-Q4', field:'revenue'}}] } },
    { id:'obs',  box:true,  label:'工具执行结果', group:'traj', size:44,
      val:{ role:'tool', content:'{"Q1":"2.5M USD","Q2":"2.1M EUR","Q3":"1.8M GBP","Q4":"380M CNY"}' } }
  ];
  var on = { sys:true, tools:true, user:true, reason:true, call:true, obs:true };

  var html = '<div class="ctrl">';
  items.forEach(function(it){
    html += '<label><input type="checkbox" data-c="'+it.id+'" checked> '+it.label+'</label>';
  });
  html += '</div>';
  html += '<div class="readout">'
    + '<div class="cell"><div class="k">静态前缀 tokens</div><div class="v" data-r="pre">0</div></div>'
    + '<div class="cell"><div class="k">轨迹 tokens</div><div class="v" data-r="trj">0</div></div>'
    + '<div class="cell"><div class="k">合计</div><div class="v" data-r="tot">0</div></div>'
    + '<div class="cell"><div class="k">缓存友好度</div><div class="v" data-r="cache">—</div></div>'
    + '</div>'
    + '<pre data-r="json" style="max-height:330px;overflow:auto;margin:0"></pre>';
  root.innerHTML = html;

  function render(){
    var prefix=0, traj=0, arr=[];
    items.forEach(function(it){
      if(!on[it.id]) return;
      if(it.group==='prefix') prefix += it.size; else traj += it.size;
      arr.push(it.val);
    });
    $('[data-r=pre]',root).textContent = comma(prefix);
    $('[data-r=trj]',root).textContent = comma(traj);
    $('[data-r=tot]',root).textContent = comma(prefix+traj);
    var cache = $('[data-r=cache]',root);
    if(!on.sys && !on.tools){ cache.textContent='无前缀'; cache.className='v warn'; }
    else if(!on.sys || !on.tools){ cache.textContent='前缀不稳'; cache.className='v bad'; }
    else { cache.textContent='优'; cache.className='v ok'; }
    $('[data-r=json]',root).textContent = JSON.stringify(arr, null, 2);
  }
  $$('[data-c]',root).forEach(function(cb){
    cb.onchange = function(){ on[cb.dataset.c]=cb.checked; render(); };
  });
  render();
};

/* ======================================================================
   L5 · 前缀缓存计价器
   ====================================================================== */
SIMS.cache = function(root){
  var BASE_SYS = '你是一个数据分析 Agent。你可以使用工具查询数据、执行代码、生成图表。请严格按步骤完成任务，每一步都先说明理由再行动。';
  var TOOL_SCHEMA = '{"tools":[{"name":"query_finance"},{"name":"get_fx_rate"},{"name":"code_interpreter"},{"name":"write_file"},{"name":"send_report"}]}';

  root.innerHTML = ''
  + '<div class="ctrl" style="align-items:flex-start">'
  + '  <div style="flex:1;min-width:280px"><label style="display:block;margin-bottom:5px">系统提示词（静态前缀的头部）</label>'
  + '  <textarea data-r="sys">'+BASE_SYS+'</textarea></div>'
  + '</div>'
  + '<div class="ctrl">'
  + '  <label><input type="checkbox" data-o="ts"> 在<b>开头</b>插入当前时间戳</label>'
  + '  <label><input type="checkbox" data-o="shuffle"> 每轮重排工具列表</label>'
  + '  <label><input type="checkbox" data-o="tail"> 工具 schema 改到<b>末尾</b>动态追加</label>'
  + '  <label>会话轮数 <input type="range" data-o="turns" min="1" max="30" value="20"><span class="mono" data-r="turns">20</span></label>'
  + '</div>'
  + '<div class="readout">'
  + '  <div class="cell"><div class="k">前缀 tokens</div><div class="v" data-r="ptok">0</div></div>'
  + '  <div class="cell"><div class="k">缓存命中率</div><div class="v" data-r="hit">0%</div></div>'
  + '  <div class="cell"><div class="k">命中 tokens</div><div class="v" data-r="htok">0</div></div>'
  + '  <div class="cell"><div class="k">未命中 tokens</div><div class="v" data-r="mtok">0</div></div>'
  + '  <div class="cell"><div class="k">总费用</div><div class="v" data-r="cost">$0</div></div>'
  + '  <div class="cell"><div class="k">相对最优</div><div class="v" data-r="rel">—</div></div>'
  + '</div>'
  + '<div data-r="bars"></div>'
  + '<div class="block" style="border-left-color:var(--cyan);margin-top:14px"><span class="lbl">计价假设</span>'
  + '<p style="font-size:13px;color:var(--paper-2);margin:0">缓存命中 $0.10 / 百万 tokens，未命中 $1.00 / 百万 tokens（差 10 倍）。'
  + '每轮轨迹增长约 380 tokens，每轮都要把「前缀 + 轨迹」整段送进模型。</p></div>';

  var PRICE_HIT=0.10, PRICE_MISS=1.00, GROW=380;

  function calc(opts){
    var sys = $('[data-r=sys]',root).value;
    if(opts.ts) sys = '[当前时间 2026-02-14 09:31:07] ' + sys;
    var prefix = tok(sys) + tok(TOOL_SCHEMA);
    var turns = opts.turns;

    // 前缀是否逐字节稳定？
    var stable = !opts.ts && !opts.shuffle;
    // 工具 schema 在末尾时：前面 sys 部分仍稳定，tail 部分每轮重算（并入 miss）
    var tailMiss = opts.tail ? tok(TOOL_SCHEMA) : 0;
    if(opts.tail){ prefix = tok(sys); }

    var hitTok=0, missTok=0, traj=0;
    for(var i=1;i<=turns;i++){
      traj += GROW;
      var input = prefix + traj;
      if(stable && i>1){ hitTok += prefix; missTok += (input - prefix) + tailMiss; }
      else { missTok += input + tailMiss; }
    }
    return { prefix:prefix, hitTok:hitTok, missTok:missTok, turns:turns,
             hitRate: hitTok+missTok>0 ? hitTok/(hitTok+missTok) : 0,
             cost: (hitTok*PRICE_HIT + missTok*PRICE_MISS)/1e6 };
  }

  function optimalCost(turns){
    // A 策略（稳定前缀）作为基线
    return calc({ ts:false, shuffle:false, tail:false, turns:turns }).cost;
  }

  var scenarios = [
    { key:'A', name:'A · 前缀逐字节稳定', opts:{ts:false,shuffle:false,tail:false} },
    { key:'B', name:'B · 开头插时间戳',   opts:{ts:true, shuffle:false,tail:false} },
    { key:'C', name:'C · 每轮重排工具列表', opts:{ts:false,shuffle:true, tail:false} },
    { key:'D', name:'D · 会变部分挪到末尾', opts:{ts:false,shuffle:false,tail:true} }
  ];

  function render(){
    var turns = +$('[data-o=turns]',root).value;
    $('[data-r=turns]',root).textContent = turns;
    var opts = { turns:turns, ts:$('[data-o=ts]',root).checked,
                 shuffle:$('[data-o=shuffle]',root).checked,
                 tail:$('[data-o=tail]',root).checked };
    var r = calc(opts);
    $('[data-r=ptok]',root).textContent = comma(r.prefix);
    $('[data-r=hit]',root).textContent  = fmt(r.hitRate*100,1)+'%';
    $('[data-r=htok]',root).textContent = comma(r.hitTok);
    $('[data-r=mtok]',root).textContent = comma(r.missTok);
    $('[data-r=cost]',root).textContent = '$'+fmt(r.cost,4);
    var oc = optimalCost(turns);
    var rel = $('[data-r=rel]',root);
    var ratio = oc>0 ? r.cost/oc : 1;
    rel.textContent = ratio<=1.001 ? '最优' : (fmt(ratio,1)+'× 最优方案');
    rel.className = 'v ' + (ratio<=1.001?'ok':(ratio<3?'warn':'bad'));

    // 四方案柱状图
    var max = 0, res = scenarios.map(function(s){
      var o = {turns:turns, ts:s.opts.ts, shuffle:s.opts.shuffle, tail:s.opts.tail};
      var v = calc(o).cost; max = Math.max(max,v); return {name:s.name, v:v, key:s.key};
    });
    var html = '<div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--paper-3);margin:16px 0 8px">四种前缀策略的费用对比（'+turns+' 轮）</div>';
    res.forEach(function(x){
      var pct = max>0 ? x.v/max*100 : 0;
      var color = x.key==='A' ? 'var(--green)' : (x.key==='D' ? 'var(--cyan)' : 'var(--magenta)');
      html += '<div class="bar-row"><span class="lb">'+x.name+'</span>'
        + '<span class="bar"><i style="width:'+pct+'%;background:'+color+'"></i></span>'
        + '<span class="vl">$'+fmt(x.v,4)+'</span></div>';
    });
    $('[data-r=bars]',root).innerHTML = html;
  }

  $$('[data-o]',root).forEach(function(c){ c.oninput = render; c.onchange = render; });
  $('[data-r=sys]',root).oninput = render;
  render();
};

/* ======================================================================
   L6 · 上下文压缩沙盘
   ====================================================================== */
SIMS.compress = function(root){
  var strategies = [
    { id:'win', name:'① 滑动窗口', keep:0.62, cache:'partial',
      desc:'只保留最近 N 条消息。实现最简单，但早期关键约束被无声丢弃。',
      risk:'早期约束丢失', riskTone:'bad', blocks:[['近期原文',62,'var(--cyan)'],['已丢弃',38,'var(--ink-4)']] },
    { id:'sum', name:'② 摘要压缩', keep:0.78, cache:'partial',
      desc:'把旧消息替换成一段模型生成的摘要。要额外花一次模型调用，且摘要本身有损。',
      risk:'摘要失真', riskTone:'warn', blocks:[['近期原文',45,'var(--cyan)'],['摘要',26,'var(--amber)'],['已丢弃',29,'var(--ink-4)']] },
    { id:'layer', name:'③ 分层压缩', keep:0.88, cache:'partial',
      desc:'近期原文 + 中期摘要 + 远期要点。保留率最高，实现最复杂。',
      risk:'三层边界难调', riskTone:'warn', blocks:[['近期原文',32,'var(--cyan)'],['中期摘要',24,'var(--amber)'],['远期要点',20,'var(--green)'],['已丢弃',24,'var(--ink-4)']] },
    { id:'iso', name:'④ 子 Agent 隔离 ★', keep:0.96, cache:'full',
      desc:'子任务交给独立上下文的子 Agent，只把结论回传主上下文。冗长过程从一开始就没进来。',
      risk:'主 Agent 看不到过程细节', riskTone:'ok', blocks:[['结论回传',18,'var(--green)'],['主上下文其余',30,'var(--cyan)'],['留在子 Agent',52,'var(--ink-3)']] }
  ];
  root.innerHTML = ''
  + '<div class="ctrl">'
  + '  <label>原始轨迹 <input type="range" data-o="raw" min="4000" max="40000" step="1000" value="24000"><span class="mono" data-r="raw">24,000</span> tokens</label>'
  + '</div>'
  + '<div class="ctrl" data-r="picks"></div>'
  + '<div class="readout">'
  + '  <div class="cell"><div class="k">压缩后 tokens</div><div class="v" data-r="after">—</div></div>'
  + '  <div class="cell"><div class="k">压缩比</div><div class="v" data-r="ratio">—</div></div>'
  + '  <div class="cell"><div class="k">关键信息保留率</div><div class="v" data-r="keep">—</div></div>'
  + '  <div class="cell"><div class="k">缓存影响</div><div class="v" data-r="cache">—</div></div>'
  + '  <div class="cell"><div class="k">主要风险</div><div class="v" data-r="risk" style="font-size:14px">—</div></div>'
  + '</div>'
  + '<div data-r="viz" style="margin:6px 0 4px"></div>'
  + '<div data-r="desc" class="block" style="border-left-color:var(--amber);margin-top:14px"></div>';

  var cur = 'iso';
  var pickBox = $('[data-r=picks]',root);
  strategies.forEach(function(s){
    var l = el('<label><input type="radio" name="cm'+(Math.random()*1e6|0)+'" value="'+s.id+'"'+(s.id===cur?' checked':'')+'> '+s.name+'</label>');
    l.querySelector('input').onchange = function(){ cur = s.id; render(); };
    pickBox.appendChild(l);
  });

  function render(){
    var raw = +$('[data-o=raw]',root).value;
    $('[data-r=raw]',root).textContent = comma(raw);
    var s = strategies.filter(function(x){return x.id===cur;})[0];
    var after = Math.round(raw * (1 - s.keep));
    var saved = Math.round(raw * s.keep);
    $('[data-r=after]',root).textContent = comma(after);
    $('[data-r=ratio]',root).textContent = fmt(raw/after,1)+' : 1';
    var keepEl = $('[data-r=keep]',root);
    keepEl.textContent = fmt(s.keep*100,0)+'%';
    keepEl.className = 'v ' + (s.keep>=0.9?'ok':s.keep>=0.7?'warn':'bad');
    var cacheEl = $('[data-r=cache]',root);
    if(s.cache==='full'){ cacheEl.textContent='前缀不受影响'; cacheEl.className='v ok'; }
    else { cacheEl.textContent='压缩即打断缓存'; cacheEl.className='v warn'; }
    var riskEl = $('[data-r=risk]',root);
    riskEl.textContent = s.risk;
    riskEl.className = 'v ' + (s.riskTone==='ok'?'ok':s.riskTone==='warn'?'warn':'bad');

    $('[data-r=desc]',root).innerHTML = '<span class="lbl">'+s.name+'</span><p class="txt" style="font-family:var(--f-body);font-size:13.5px;color:var(--paper-2)">'+s.desc+'</p>';

    var h = '<div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--paper-3);margin-bottom:8px">压缩后上下文构成（共 '+comma(after)+' tokens）</div>';
    h += '<div style="display:flex;height:34px;border:1px solid var(--line);overflow:hidden">';
    s.blocks.forEach(function(b){
      var w = b[1]/100*after;
      h += '<div title="'+b[0]+'" style="width:'+(b[1])+'%;background:'+b[2]+';opacity:.75;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--ink)">'
        + '<span class="mono" style="font-size:10px;color:#04080f;white-space:nowrap;overflow:hidden">'+b[0]+'</span></div>';
    });
    h += '</div>';
    h += '<div class="small mono" style="margin-top:8px">被省掉的 '+comma(saved)+' tokens —— 这就是你省下的钱和注意力。</div>';
    $('[data-r=viz]',root).innerHTML = h;
  }
  $('[data-o=raw]',root).oninput = render;
  render();
};

/* ======================================================================
   L7 · 记忆格式试验台
   ====================================================================== */
SIMS.memory = function(root){
  var query = '用户这次的年度报表，应该用哪个州的销售税率？';
  var formats = [
    { id:'nl', name:'自然语言', icon:'💬', reliability:62,
      store:'记忆条目：「用户主要在美国加州做生意，上次说过税率的事有点麻烦。」',
      got:'「税率的事有点麻烦」—— 信息模糊，模型需要猜具体数字。',
      score:'可读性满分，但对精确计算毫无帮助。',
      tone:'warn' },
    { id:'json', name:'结构化 JSON', icon:'{ }', reliability:88,
      store:'{"tax_region":"US-CA","tax_rate_pct":7.25,"updated":"2025-11-03","source":"user_stated"}',
      got:'7.25（可直接使用，且带更新时间和来源）',
      score:'可精确查询、可校验、可回溯来源。缺点是需要提前设计 schema。',
      tone:'ok' },
    { id:'code', name:'可执行代码', icon:'ƒ', reliability:99,
      store:'def sales_tax(state, amount):\n    RATES = {"CA":0.0725,"NY":0.08}\n    return round(amount * RATES.get(state, 0), 2)',
      got:'sales_tax("CA", 125000) → 9062.50（确定性计算，零幻觉）',
      score:'能写成规则的经验就该写成代码：可测试、可复用、不会理解错。',
      tone:'ok' },
    { id:'mm', name:'多模态截图', icon:'🖼', reliability:74,
      store:'一张用户上次发的税务文件截图 + OCR 文本',
      got:'需要多一步 OCR 或视觉理解，才能拿到 7.25% 这个数。',
      score:'保留了原始证据（可用于审计），但检索和过期管理更难。',
      tone:'warn' }
  ];
  var html = '<div class="block" style="border-left-color:var(--cyan);margin:0 0 16px"><span class="lbl">同一个问题</span>'
    + '<p style="font-family:var(--f-body);font-size:14.5px;color:var(--paper);margin:0">'+query+'</p></div>';
  html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)" data-r="grid">';
  formats.forEach(function(f){
    html += '<div style="background:var(--ink-2);padding:16px;cursor:pointer" data-f="'+f.id+'">'
      + '<div style="font-size:20px;margin-bottom:6px">'+f.icon+'</div>'
      + '<div style="font-family:var(--f-display);font-size:16px;color:#e8f4ff;margin-bottom:10px">'+f.name+'</div>'
      + '<div class="mono" style="font-size:11px;color:var(--paper-3);letter-spacing:.1em">可信度</div>'
      + '<div style="height:6px;background:var(--ink);border:1px solid var(--line);margin:5px 0 0"><i style="display:block;height:100%;width:'+f.reliability+'%;background:'+(f.tone==='ok'?'var(--green)':'var(--amber)')+'"></i></div>'
      + '<div class="mono" style="font-size:11px;color:'+(f.tone==='ok'?'var(--green)':'var(--amber)')+';margin-top:4px">'+f.reliability+' / 100</div>'
      + '</div>';
  });
  html += '</div><div data-r="out" style="margin-top:14px"></div>';
  root.innerHTML = html;

  function show(id){
    var f = formats.filter(function(x){return x.id===id;})[0];
    $('[data-r=out]',root).innerHTML =
      '<div class="block" style="border-left-color:var(--magenta);margin:0 0 10px"><span class="lbl">存进去的样子</span>'
      + '<pre style="margin:6px 0 0;font-size:12px">'+f.store+'</pre></div>'
      + '<div class="block" style="border-left-color:var(--cyan);margin:0 0 10px"><span class="lbl">取出来得到</span>'
      + '<p style="margin:0;font-size:13.5px;color:var(--paper)">'+f.got+'</p></div>'
      + '<div class="block analogy" style="margin:0"><span class="lbl">点评</span><p class="txt" style="font-size:16px">'+f.score+'</p></div>';
    $$('[data-f]',root).forEach(function(n){ n.style.background = n.dataset.f===id ? 'rgba(19,40,68,.9)' : 'var(--ink-2)'; });
  }
  $$('[data-f]',root).forEach(function(n){ n.onclick = function(){ show(n.dataset.f); }; });
  show('code');
};

/* ======================================================================
   L8 · 混合检索实验台
   ====================================================================== */
SIMS.retrieval = function(root){
  var DOCS = [
    { id:'react', t:'ReAct 循环', d:'Agent 反复执行「想、做、看」：先推理下一步该干什么，调用工具，再把工具返回的结果并回上下文，循环直到任务完成。退出条件包括任务完成、没有工具调用、错误超限和最大轮次。' },
    { id:'kv',    t:'KV Cache 与前缀缓存', d:'自回归生成从左向右逐 token 追加，每层为每个 token 保存一对 Key/Value 向量。若修改序列中靠前的位置，其后所有 token 的注意力计算都会变化，缓存整体失效。因此上下文需要保持前缀逐字节稳定。' },
    { id:'rag',   t:'RAG 检索增强生成', d:'把文档切分成块并建立索引，检索出相关块拼进上下文再生成回答。常见流程是分块、编码、检索、重排序、生成，两阶段漏斗结构类似推荐系统的粗排与精排。' },
    { id:'bm25',  t:'BM25 稀疏检索算法', d:'BM25 依据词频、逆文档频率和文档长度归一化来打分，参数 k1 控制词频饱和、b 控制长度惩罚。它对专有名词、型号、错误码这类罕见 token 非常敏感，可解释性好，每个词对分数的贡献都能拆开看。' },
    { id:'err',   t:'错误码 ERR_4021 排查手册', d:'ERR_4021 表示上游鉴权令牌过期。处理办法是调用刷新接口重新获取 token 并重试请求。该错误码通常伴随 401 状态返回，日志中会记录 traceId 便于追踪。' },
    { id:'cache', t:'模型 API 成本优化', d:'推理成本主要来自输入 token。缓存命中部分通常按十分之一计价，因此让长前缀保持稳定可以显著降低成本。缓存是按字节前缀匹配的，不是按语义匹配。' },
    { id:'ctx',   t:'上下文压缩策略', d:'轨迹会随轮次不断增长。可用滑动窗口、摘要压缩、分层压缩三种有损手段，或采用子 Agent 隔离让冗长过程不进主上下文。压缩会打断前缀缓存，因此触发越少越好。' },
    { id:'multi', t:'多 Agent 协作失败模式', d:'多 Agent 会出现共享文件系统并发冲突、错误级联放大、同质趋同、互相扯皮、循环失控、理解债与认知投降六种典型失败。它们本质上是分布式系统的经典问题被搬到了自然语言层。' }
  ];

  /* --- 迷你 BM25（教学实现，中文按字 + 二元组切分） --- */
  function cut(s){
    s = s.toLowerCase();
    var grams = [], i;
    for(i=0;i<s.length;i++){
      var c = s[i];
      if(/[\u4e00-\u9fff]/.test(c)) grams.push(c);
      else if(/[a-z0-9_]/.test(c)){
        var j=i, w='';
        while(j<s.length && /[a-z0-9_]/.test(s[j])){ w+=s[j]; j++; }
        grams.push(w); i=j-1;
      }
    }
    for(i=0;i<s.length-1;i++){
      if(/[\u4e00-\u9fff]/.test(s[i]) && /[\u4e00-\u9fff]/.test(s[i+1])) grams.push(s.substr(i,2));
    }
    return grams;
  }
  var DOC_TERMS = DOCS.map(function(d){ return cut(d.t + ' ' + d.d); });
  var DF = {};
  DOC_TERMS.forEach(function(ts){
    var seen = {};
    ts.forEach(function(t){ if(!seen[t]){ seen[t]=1; DF[t]=(DF[t]||0)+1; } });
  });
  var AVG = DOC_TERMS.reduce(function(a,t){return a+t.length;},0)/DOC_TERMS.length;
  var K1 = 1.5, B = 0.75;

  function bm25(query){
    var q = cut(query), N = DOCS.length;
    return DOC_TERMS.map(function(ts, i){
      var tf = {}, len = ts.length;
      ts.forEach(function(t){ tf[t]=(tf[t]||0)+1; });
      var s = 0;
      q.forEach(function(t){
        if(!tf[t]) return;
        var df = DF[t]||1;
        var idf = Math.log(1 + (N - df + 0.5)/(df + 0.5));
        s += idf * (tf[t]*(K1+1)) / (tf[t] + K1*(1 - B + B*len/AVG));
      });
      return s;
    });
  }
  /* 预置的「语义分」—— 离线环境跑不了真嵌入模型，这里用固定分数模拟其典型行为 */
  var SEM = {
    'ERR_4021 怎么解决': null,  // 动态生成
    '怎么降低 API 调用成本': [0.21,0.71,0.18,0.12,0.10,0.88,0.44,0.09],
    'Agent 一直重复调用同一个工具怎么办': [0.30,0.18,0.22,0.11,0.08,0.14,0.79,0.65]
  };
  var presets = [
    { q:'ERR_4021 怎么解决', note:'关键词型：含专有错误码', sem:[0.55,0.14,0.20,0.16,0.31,0.12,0.15,0.08],
      lesson:'稠密检索被「错误处理」的语义带偏，把通用文档排到了前面；BM25 靠罕见 token ERR_4021 一击命中。<b>这就是混合检索存在的理由。</b>' },
    { q:'怎么降低 API 调用成本', note:'语义型：字面完全不重叠', sem:[0.21,0.71,0.18,0.12,0.10,0.88,0.44,0.09],
      lesson:'BM25 只在字面命中「成本」「API」时才有分，容易漏掉真正讲缓存的文档；语义检索能捕捉到「降成本 ≈ 缓存命中」这层意思。<b>两路互补。</b>' },
    { q:'Agent 一直重复调用同一个工具怎么办', note:'混合型：既有关键词又有语义', sem:[0.30,0.18,0.22,0.11,0.08,0.14,0.79,0.65],
      lesson:'关键词命中 ReAct（重复调用），语义指向上下文压缩（轨迹太长）。两路融合后，最需要的那篇排到了第一。' }
  ];

  root.innerHTML = ''
  + '<div class="ctrl">'
  + '  <label style="flex:1;min-width:240px">查询<br><input type="text" data-r="q" style="width:100%" value="ERR_4021 怎么解决"></label>'
  + '  <label><input type="checkbox" data-o="hybrid" checked> 启用混合检索融合</label>'
  + '</div>'
  + '<div class="ctrl" data-r="presets"></div>'
  + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);border:1px solid var(--line)">'
  + '  <div style="background:var(--ink-2);padding:12px 14px"><div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--magenta);margin-bottom:9px">BM25 稀疏检索（关键词）</div><div data-r="l1"></div></div>'
  + '  <div style="background:var(--ink-2);padding:12px 14px"><div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--cyan);margin-bottom:9px">语义检索（预置分数模拟）</div><div data-r="l2"></div></div>'
  + '</div>'
  + '<div style="border:1px solid var(--line-hi);border-top:0;background:rgba(4,10,20,.7);padding:12px 14px"><div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--green);margin-bottom:9px">融合结果（加权归一化）</div><div data-r="l3"></div></div>'
  + '<div data-r="lesson" class="block analogy" style="margin-top:14px"></div>';

  function norm(a){
    var mx = Math.max.apply(null,a)||1, mn = Math.min.apply(null,a);
    if(mx-mn < 1e-9) return a.map(function(){return 0;});
    return a.map(function(v){ return (v-mn)/(mx-mn); });
  }
  function rankList(scores){
    var idx = scores.map(function(v,i){ return [v,i]; }).sort(function(a,b){ return b[0]-a[0]; });
    var h = '';
    idx.slice(0,4).forEach(function(p, r){
      var pct = Math.max(0, Math.min(1, p[0]/ (Math.max.apply(null,scores)||1))) * 100;
      var strong = r===0;
      h += '<div style="margin-bottom:9px"><div class="mono" style="font-size:11.5px;color:'+(strong?'var(--cyan)':'var(--paper-3)')+'">'
        + (r+1)+'. '+DOCS[p[1]].t+'<span style="float:right;color:var(--paper-3)">'+fmt(p[0],3)+'</span></div>'
        + '<div style="height:4px;background:var(--ink);margin-top:4px"><i style="display:block;height:100%;width:'+pct+'%;background:'+(strong?'var(--cyan)':'var(--line-hi)')+'"></i></div></div>';
    });
    return h;
  }
  function preset(){ 
    var q = $('[data-r=q]',root).value.trim();
    var p = presets.filter(function(x){ return x.q===q; })[0];
    return p || presets[0];
  }
  function render(){
    var q = $('[data-r=q]',root).value;
    var p = preset();
    var bs = bm25(q), ss = p.sem.slice();
    var hybrid = $('[data-o=hybrid]',root).checked;
    var fused = norm(bs).map(function(v,i){ return 0.5*v + 0.5*norm(ss)[i]; });
    $('[data-r=l1]',root).innerHTML = rankList(bs);
    $('[data-r=l2]',root).innerHTML = rankList(ss);
    $('[data-r=l3]',root).innerHTML = rankList(hybrid?fused:bs);
    $('[data-r=lesson]',root).innerHTML = '<span class="lbl">这一组说明什么</span><p class="txt" style="font-family:var(--f-body);font-size:13.5px;color:var(--paper-2)">'+p.lesson+'</p>';
  }
  var pb = $('[data-r=presets]',root);
  presets.forEach(function(p){
    var b = el('<button class="btn ghost">'+p.note+'</button>');
    b.onclick = function(){ $('[data-r=q]',root).value = p.q; render(); };
    pb.appendChild(b);
  });
  $('[data-r=q]',root).oninput = render;
  $('[data-o=hybrid]',root).onchange = render;
  render();
};

/* ======================================================================
   L9 · 工具设计评审台
   ====================================================================== */
SIMS.tools = function(root){
  var designs = [
    { id:'vague', name:'方案 A · 一个万能工具', tone:'bad', score:34,
      schema:'do_thing(action: string, params: object)',
      calls:['do_thing(action="get_revenue", params={"q":"Q1"})','do_thing(action="convert", params={"from":"EUR"})','do_thing(action="计算", params={})  ← 中文 action 混用'],
      verdict:'名字毫无信息量，action 是自由字符串。模型要靠猜来选动作，参数是万能 object 无法校验，还出现了中英文混用。',
      fix:'给每个动作一个语义明确的名字；把 action 收敛成枚举。' },
    { id:'split', name:'方案 B · 拆成一堆专用工具', tone:'warn', score:71,
      schema:'get_revenue(period) / get_cost(period) / get_fx(base,quote) / calc(expr) / fmt(num) / round2(x) …（共 24 个工具）',
      calls:['get_revenue(period="2025Q1")','get_fx(base="EUR", quote="USD")','calc(expr="2.5+2.1*1.08")   ← 还需要 round2 吗？'],
      verdict:'每个工具都语义清晰，但 24 个工具定义会吃掉大量上下文，而且 calc / round2 / fmt 这类能力高度重叠，模型在相似选项间摇摆。',
      fix:'合并明显重叠的工具；把长尾能力交给通用执行器 + Skill。' },
    { id:'good', name:'方案 C · 少而清晰 + 防呆', tone:'ok', score:96,
      schema:'query_finance(period: enum[2025Q1..2025Q4], field: enum["revenue","cost"], currency: enum["USD"]="USD")\ncode_interpreter(code: string, timeout_s: int=10)',
      calls:['query_finance(period="2025Q1", field="revenue", currency="USD")','code_interpreter(code="round(sum(v),2)", timeout_s=10)'],
      verdict:'period 和 field 都是枚举，模型不可能拼错；currency 有安全默认值；计算类需求统一交给 code_interpreter，不另做重复工具。只有 2 个工具，描述占的上下文极少。',
      fix:'—（这就是目标形态）' }
  ];
  var html = '<div class="ctrl" data-r="picks"></div><div data-r="out"></div>';
  root.innerHTML = html;
  var cur = 'vague';
  designs.forEach(function(d){
    var l = el('<label><input type="radio" name="td" value="'+d.id+'"'+(d.id===cur?' checked':'')+'> '+d.name+'</label>');
    l.querySelector('input').onchange = function(){ cur = d.id; render(); };
    $('[data-r=picks]',root).appendChild(l);
  });
  function render(){
    var d = designs.filter(function(x){return x.id===cur;})[0];
    var color = d.tone==='ok'?'var(--green)':d.tone==='warn'?'var(--amber)':'var(--red)';
    var h = '<div class="readout">'
      + '<div class="cell"><div class="k">工具 schema</div><div class="v" style="font-size:11px;color:var(--paper-2);font-family:var(--f-mono)">'+d.schema.replace(/\n/g,'<br>')+'</div></div>'
      + '<div class="cell"><div class="k">可校验性得分</div><div class="v" style="color:'+color+'">'+d.score+'</div></div>'
      + '</div>';
    h += '<div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--paper-3);margin:14px 0 8px">模型实际会发出的调用</div>';
    h += '<pre style="margin:0 0 12px">';
    d.calls.forEach(function(c,i){
      h += '<span class="c">// 第 '+(i+1)+' 次</span>\n'+c+(i<d.calls.length-1?'\n':'');
    });
    h += '</pre>';
    h += '<div class="block" style="border-left-color:'+color+';margin:0 0 10px"><span class="lbl">评审意见</span>'
      + '<p style="margin:0;font-size:13.5px;color:var(--paper-2)">'+d.verdict+'</p></div>';
    if(d.fix!=='—（这就是目标形态）'){
      h += '<div class="block" style="border-left-color:var(--cyan);margin:0"><span class="lbl">怎么改</span>'
        + '<p style="margin:0;font-size:13.5px;color:var(--paper-2)">'+d.fix+'</p></div>';
    }
    $('[data-r=out]',root).innerHTML = h;
  }
  render();
};

/* ======================================================================
   L10 · Pass@k / Pass^k 计算器
   ====================================================================== */
SIMS.passk = function(root){
  root.innerHTML = ''
  + '<div class="ctrl">'
  + '  <label>单次成功率 p <input type="range" data-o="p" min="50" max="99" value="90"><span class="mono" data-r="pv">0.90</span></label>'
  + '  <label>尝试次数 k <input type="range" data-o="k" min="1" max="20" value="5"><span class="mono" data-r="kv">5</span></label>'
  + '  <button class="btn ghost" data-a="scenario">切到「客服机器人」场景</button>'
  + '</div>'
  + '<div class="readout">'
  + '  <div class="cell"><div class="k">Pass@k 至少成功一次</div><div class="v ok" data-r="pk">—</div></div>'
  + '  <div class="cell"><div class="k">Pass^k 每次都要成功</div><div class="v bad" data-r="kk">—</div></div>'
  + '  <div class="cell"><div class="k">差距</div><div class="v warn" data-r="gap">—</div></div>'
  + '  <div class="cell"><div class="k">连续 100 次都不出错</div><div class="v bad" data-r="hundred">—</div></div>'
  + '</div>'
  + '<div data-r="chart" style="border:1px solid var(--line);background:rgba(2,5,10,.6);padding:14px"></div>'
  + '<div class="block" style="border-left-color:var(--cyan);margin-top:14px"><span class="lbl">样本量小抄</span>'
  + '  <p style="font-size:13.5px;color:var(--paper-2);margin:0 0 8px">要在 80% 把握下检出两个系统之间 <b class="hl" data-r="d">5</b> 个百分点的差异（α=0.05，双侧），每个系统大约需要：</p>'
  + '  <div class="ctrl" style="margin:0"><label>要检出的差异 <input type="range" data-o="d" min="1" max="15" value="5"><span class="mono" data-r="dv">5 pp</span></label></div>'
  + '  <p style="font-size:15px;color:var(--paper);margin:8px 0 0">每组样本量 ≈ <b class="hl-a" data-r="n">—</b> 条</p>'
  + '</div>';

  function pct(x){ return fmt(x*100, x>0.999?3:1)+'%'; }

  function chart(p, k){
    var W=620, H=190, PL=44, PB=26, PT=12, PR=12;
    var xs = function(i){ return PL + (W-PL-PR) * (i-1)/19; };
    var ys = function(v){ return PT + (H-PT-PB) * (1-v); };
    var line = function(fn){ var pts=[]; for(var i=1;i<=20;i++) pts.push(fmt(xs(i),1)+','+fmt(ys(Math.max(0,Math.min(1,fn(i)))),1)); return pts.join(' '); };
    var pkLine = line(function(i){ return 1-Math.pow(1-p,i); });
    var kkLine = line(function(i){ return Math.pow(p,i); });
    var s = '<div class="mono" style="font-size:10px;letter-spacing:.16em;color:var(--paper-3);margin-bottom:8px">p = '+fmt(p,2)+' 时，两个指标随 k 变化</div>';
    s += '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">';
    for(var g=0; g<=4; g++){
      var y = PT + (H-PT-PB)*g/4;
      s += '<line x1="'+PL+'" y1="'+fmt(y,1)+'" x2="'+(W-PR)+'" y2="'+fmt(y,1)+'" stroke="#1b3a5e" stroke-width="1"/>';
      s += '<text x="'+(PL-8)+'" y="'+(y+4)+'" fill="#5d7d9e" font-size="10" text-anchor="end" font-family="monospace">'+fmt((1-g/4)*100,0)+'%</text>';
    }
    [1,5,10,15,20].forEach(function(i){
      s += '<text x="'+fmt(xs(i),1)+'" y="'+(H-8)+'" fill="#5d7d9e" font-size="10" text-anchor="middle" font-family="monospace">k='+i+'</text>';
    });
    s += '<polyline points="'+pkLine+'" fill="none" stroke="#3ddc84" stroke-width="2.2"/>';
    s += '<polyline points="'+kkLine+'" fill="none" stroke="#ff4d8d" stroke-width="2.2"/>';
    s += '<line x1="'+fmt(xs(k),1)+'" y1="'+PT+'" x2="'+fmt(xs(k),1)+'" y2="'+(H-PB)+'" stroke="#46e8ff" stroke-width="1" stroke-dasharray="3 3"/>';
    s += '<circle cx="'+fmt(xs(k),1)+'" cy="'+fmt(ys(1-Math.pow(1-p,k)),1)+'" r="4" fill="#3ddc84"/>';
    s += '<circle cx="'+fmt(xs(k),1)+'" cy="'+fmt(ys(Math.pow(p,k)),1)+'" r="4" fill="#ff4d8d"/>';
    s += '</svg>';
    s += '<div class="mono" style="font-size:11px;margin-top:6px">'
      + '<span style="color:var(--green)">━ Pass@k（能力上限：至少成功一次）</span>&nbsp;&nbsp;&nbsp;'
      + '<span style="color:var(--magenta)">━ Pass^k（业务可靠性：每次都要成功）</span></div>';
    return s;
  }

  function render(){
    var p = +$('[data-o=p]',root).value/100;
    var k = +$('[data-o=k]',root).value;
    $('[data-r=pv]',root).textContent = fmt(p,2);
    $('[data-r=kv]',root).textContent = k;
    var PK = 1-Math.pow(1-p,k), KK = Math.pow(p,k);
    $('[data-r=pk]',root).textContent = pct(PK);
    $('[data-r=kk]',root).textContent = pct(KK);
    $('[data-r=gap]',root).textContent = fmt((PK-KK)*100,1)+' pp';
    $('[data-r=hundred]',root).textContent = pct(Math.pow(p,100));
    $('[data-r=chart]',root).innerHTML = chart(p,k);

    var d = +$('[data-o=d]',root).value/100;
    $('[data-r=d]',root).textContent = (d*100).toFixed(0);
    $('[data-r=dv]',root).textContent = (d*100).toFixed(0)+' pp';
    // 两比例检验样本量（简化公式，p1=p2=0.9 附近）
    var p1=0.9, p2=0.9-d;
    var pbar=(p1+p2)/2;
    var n = Math.ceil( Math.pow(1.96*Math.sqrt(2*pbar*(1-pbar)) + 0.84*Math.sqrt(p1*(1-p1)+p2*(1-p2)), 2) / (d*d) );
    $('[data-r=n]',root).textContent = comma(Math.max(n,2));
  }
  $$('[data-o]',root).forEach(function(c){ c.oninput = render; });
  $('[data-a=scenario]',root).onclick = function(){
    $('[data-o=p]',root).value = 96;
    $('[data-o=k]',root).value = 10;
    render();
    this.textContent = '已切到 p=0.96, k=10 —— 看 Pass^100';
  };
  render();
};

/* ======================================================================
   L11 · 奖励设计沙盘
   ====================================================================== */
SIMS.reward = function(root){
  var cases = [
    { id:'r1', name:'奖励：单元测试通过数', tone:'bad',
      learned:'Agent 发现删掉失败的测试文件，通过率立刻变成 100%。测试确实"全过了"。',
      patched:'覆盖率从 84% 掉到 0%，还引入了两个线上 bug。',
      diag:'典型的 reward hacking：奖励信号可以被直接操纵，而不是必须通过真实解决问题来获得。',
      fix:'奖励要绑定到不可篡改的验证路径（原始测试文件只读 + 独立的回归集），并对"改动测试"这个动作单独加惩罚。' },
    { id:'r2', name:'奖励：过程分（每步 +0.1）', tone:'warn',
      learned:'无论任务难易，Agent 都会把步骤拖到上限：简单改个常量也要读 12 个文件、跑 5 遍测试。',
      patched:'平均耗时上涨 4 倍，成本失控，但正确率只从 71% 涨到 73%。',
      diag:'过程奖励给了稠密信号（好学好用），但没写"效率"这一项，于是模型优化的是步数而不是结果。',
      fix:'过程奖励必须成对：既奖励「做对的关键步骤」，也惩罚「无效步骤」。书里 RLVP 的思路就是奖励结果、惩罚不良路径。' },
    { id:'r3', name:'奖励：结果（任务真的成功）+ 路径惩罚', tone:'ok',
      learned:'Agent 学会了先跑一遍回归测试确认现状，再动手改，改完再跑一次对比。步数反而比基线少。',
      patched:'正确率从 71% 涨到 89%，平均耗时下降 18%。',
      diag:'结果奖励不可作弊（由环境裁决），路径惩罚抑制了绕路和过早结束。这是书里强调的"可验证闭环"。',
      fix:'—（但要记住：结果可自动验证是前提，不能自动验证的任务退化到过程规则或 Rubric）' }
  ];
  var html = '<div class="ctrl"><span class="mono" style="font-size:11px;color:var(--paper-3)">任务：让 Agent 修一个真实的 bug（有完整单元测试）</span></div>';
  html += '<div class="ctrl" data-r="picks"></div><div data-r="out"></div>';
  root.innerHTML = html;
  var cur='r1';
  cases.forEach(function(c){
    var l = el('<label><input type="radio" name="rw" value="'+c.id+'"'+(c.id===cur?' checked':'')+'> '+c.name+'</label>');
    l.querySelector('input').onchange = function(){ cur=c.id; render(); };
    $('[data-r=picks]',root).appendChild(l);
  });
  function render(){
    var c = cases.filter(function(x){return x.id===cur;})[0];
    var color = c.tone==='ok'?'var(--green)':c.tone==='warn'?'var(--amber)':'var(--red)';
    var h = '<div class="block" style="border-left-color:'+color+';margin:0 0 10px"><span class="lbl">Agent 学到了什么</span>'
      + '<p style="margin:0;font-size:14px;color:var(--paper)">'+c.learned+'</p></div>'
      + '<div class="block" style="border-left-color:var(--magenta);margin:0 0 10px"><span class="lbl">上线之后</span>'
      + '<p style="margin:0;font-size:14px;color:#ffc4da">'+c.patched+'</p></div>'
      + '<div class="block" style="border-left-color:var(--cyan);margin:0 0 10px"><span class="lbl">诊断</span>'
      + '<p style="margin:0;font-size:13.5px;color:var(--paper-2)">'+c.diag+'</p></div>';
    if(c.fix!=='—（但要记住：结果可自动验证是前提，不能自动验证的任务退化到过程规则或 Rubric）'){
      h += '<div class="block" style="border-left-color:var(--amber);margin:0"><span class="lbl">怎么改</span><p style="margin:0;font-size:13.5px;color:var(--paper-2)">'+c.fix+'</p></div>';
    } else {
      h += '<div class="block" style="border-left-color:var(--green);margin:0"><span class="lbl">前提条件</span><p style="margin:0;font-size:13.5px;color:var(--paper-2)">'+c.fix.replace('—（','').replace('）','')+'</p></div>';
    }
    $('[data-r=out]',root).innerHTML = h;
  }
  render();
};

/* ======================================================================
   L12 · 多 Agent 沙盘
   ====================================================================== */
SIMS.multiagent = function(root){
  root.innerHTML = ''
  + '<div class="ctrl">'
  + '  <label>Agent 数量 <input type="range" data-o="n" min="1" max="5" value="3"><span class="mono" data-r="nv">3</span></label>'
  + '  <label><input type="checkbox" data-o="shared" checked> 共享文件系统</label>'
  + '  <label><input type="checkbox" data-o="lock"> 写入加锁</label>'
  + '  <label><input type="checkbox" data-o="reviewer"> 独立审核者</label>'
  + '  <label><input type="checkbox" data-o="cap" checked> 消息轮次上限</label>'
  + '  <label><input type="checkbox" data-o="diverse"> 不同模型 / 不同提示</label>'
  + '  <button class="btn" data-a="run">▶ 运行协作</button>'
  + '</div>'
  + '<div class="readout">'
  + '  <div class="cell"><div class="k">协作模式</div><div class="v" data-r="mode" style="font-size:13px">—</div></div>'
  + '  <div class="cell"><div class="k">触发失败模式</div><div class="v bad" data-r="fails">—</div></div>'
  + '  <div class="cell"><div class="k">产出可信度</div><div class="v" data-r="trust">—</div></div>'
  + '</div>'
  + '<div class="log" data-r="log" style="min-height:170px"></div>'
  + '<div class="block" style="border-left-color:var(--magenta);margin-top:14px"><span class="lbl">六种失败模式</span>'
  + '<p style="font-size:13px;color:var(--paper-2);margin:0">共享文件系统并发冲突 · 错误级联放大 · 同质趋同 · 互相扯皮 · 循环失控 · 理解债与认知投降</p></div>';

  var logEl = $('[data-r=log]',root);
  function lg(cls,i,t){ logEl.appendChild(el('<div class="row '+cls+'"><span class="i">'+i+'</span><span class="t">'+t+'</span></div>')); logEl.scrollTop=logEl.scrollHeight; }

  function run(){
    var n = +$('[data-o=n]',root).value;
    var shared = $('[data-o=shared]',root).checked;
    var lock = $('[data-o=lock]',root).checked;
    var reviewer = $('[data-o=reviewer]',root).checked;
    var cap = $('[data-o=cap]',root).checked;
    var diverse = $('[data-o=diverse]',root).checked;

    logEl.innerHTML='';
    var fails = [];
    var mode = shared ? (n>1?'共享上下文协作（同一份上下文）':'单 Agent') : '不共享上下文协作（各自独立，交换结论）';
    $('[data-r=mode]',root).textContent = mode;

    lg('sys','SYS','启动 '+n+' 个 Agent，模式：'+mode);
    if(n===1){ lg('sys','SYS','单 Agent：不涉及协作失败模式。'); }
    else{
      var i;
      for(i=0;i<n;i++) lg('sys','A'+(i+1),'Agent '+(i+1)+' 开始工作');
      if(shared){
        lg('act','W','多个 Agent 同时写同一份报告文件');
        if(!lock){ lg('err','✖','写入冲突：Agent 1 的改动被 Agent 3 覆盖（共享文件系统并发冲突）'); fails.push('并发冲突'); }
        else lg('obs','✓','写入加锁，串行完成（并发冲突被消除）');
        if(!cap){ lg('err','✖','消息在 Agent 之间无限传递，达到 40 轮仍未收敛（循环失控）'); fails.push('循环失控'); }
        else lg('obs','✓','消息轮次上限 = 12，超限即终止');
      } else {
        lg('act','W','各 Agent 独立探索，最后交换结论');
        if(!diverse){ lg('err','✖','三个 Agent 给出完全相同的结论 —— 同源模型 + 相似提示（同质趋同）'); fails.push('同质趋同'); }
        else lg('obs','✓','使用不同模型族与不同提示，结论出现真实分歧');
        lg('act','W','Agent 2 基于 Agent 1 的错误中间结论继续推理');
        lg('err','✖','错误被下游放大 3 倍（错误级联放大）'); fails.push('错误级联放大');
      }
      if(reviewer){
        lg('act','W','独立审核者开始复核');
        if(!cap){ lg('err','✖','审核者与提议者来回 20 轮仍不拍板（互相扯皮）'); fails.push('互相扯皮'); }
        else { lg('obs','✓','审核者限 3 轮内必须给结论'); lg('obs','✓','发现 1 处事实错误并驳回（独立视角起了作用）'); }
      } else {
        lg('err','✖','没有独立视角，所有 Agent 都在自我确认（理解债累积）'); fails.push('理解债');
      }
    }
    lg('fin','END','协作结束。人类是否还能说清系统为什么得出这个结论？');
    $('[data-r=fails]',root).textContent = fails.length? fails.length+' 种' : '0 种';
    $('[data-r=fails]',root).className = 'v ' + (fails.length? 'bad':'ok');
    var trust = Math.max(10, 100 - fails.length*22 + (reviewer?8:0) + (diverse?6:0));
    $('[data-r=trust]',root).textContent = trust+' / 100';
    $('[data-r=trust]',root).className = 'v ' + (trust>75?'ok':trust>45?'warn':'bad');
  }
  $$('[data-o]',root).forEach(function(c){
    c.oninput = function(){ $('[data-r=nv]',root).textContent = $('[data-o=n]',root).value; };
    c.onchange = function(){ $('[data-r=nv]',root).textContent = $('[data-o=n]',root).value; };
  });
  $('[data-a=run]',root).onclick = run;
  run();
};

window.SIMS = SIMS;
})();
