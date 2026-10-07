/* ==========================================================================
   Agent 拆机工坊 — 应用引擎
   ========================================================================== */
(function(){
"use strict";

var C = window.CONTENT;
var LV = C.levels;
var BADGES = ['🔧','👁','✋','🧬'];
var STORE = 'agent-teardown-v1';

/* ---------- 进度存储（file:// 下 localStorage 可能不可用，做降级） ---------- */
var mem = null;
function load(){
  try{ var s = localStorage.getItem(STORE); if(s) return JSON.parse(s); }catch(e){}
  return mem || { xp:0, done:[], quiz:{}, unlocked:false };
}
function save(st){
  mem = st;
  try{ localStorage.setItem(STORE, JSON.stringify(st)); }catch(e){}
}
var S = load();

/* ---------- DOM ---------- */
var rail = document.getElementById('rail');
var stage = document.getElementById('stage');

function toast(msg){
  var t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(function(){ t.classList.remove('on'); }, 2200);
}
function isDone(id){ return S.done.indexOf(id) >= 0; }
function unlocked(id){
  if(S.unlocked) return true;
  if(id === 1) return true;
  return isDone(id - 1);
}
function actOf(id){ return LV.filter(function(l){ return l.id===id; })[0].act; }

function refreshHud(){
  var total = LV.length;
  var n = LV.filter(function(l){ return isDone(l.id); }).length;
  document.getElementById('xp').textContent = S.xp;
  document.getElementById('prog').textContent = n + '/' + total;
  document.getElementById('xpfill').style.width = (S.xp / (total*120) * 100) + '%';
  // 徽章 = 该幕全部完成
  C.acts.forEach(function(a){
    var b = document.querySelector('.badge[data-b="'+a.id+'"]');
    if(!b) return;
    var all = a.levels.every(isDone);
    b.classList.toggle('on', all);
    b.textContent = all ? BADGES[a.id-1] : '·';
  });
}

/* ---------- 左侧导轨 ---------- */
function buildRail(){
  var h = '';
  C.acts.forEach(function(a){
    var done = a.levels.filter(isDone).length;
    h += '<div class="act'+(done===a.levels.length?' prog':'')+'">';
    h += '<div class="act-head"><span class="num">幕 '+(['一','二','三','四'][a.id-1])+'</span>'
       + '<span class="cn">'+a.cn+'</span><span class="bar"></span>'
       + '<span class="mono" style="font-size:10px">'+done+'/'+a.levels.length+'</span></div>';
    a.levels.forEach(function(id){
      var l = LV.filter(function(x){ return x.id===id; })[0];
      var cls = 'node' + (isDone(id)?' done':'') + (unlocked(id)?'' :' locked');
      h += '<button class="'+cls+'" data-go="'+id+'">'
         +   '<span class="idx">'+String(id).padStart(2,'0')+'</span>'
         +   '<span class="tt">'+shortTitle(l.title)+'<small>'+l.tagline.replace(/[<>]/g,'')+'</small></span>'
         +   '<span class="tick">'+(isDone(id)?'✔':'')+'</span>'
         + '</button>';
    });
    h += '</div>';
  });
  h += '<div style="padding:16px 16px 0"><button class="btn ghost" style="width:100%" data-a="unlockall">解锁全部关卡</button></div>';
  rail.innerHTML = h;
  Array.prototype.forEach.call(rail.querySelectorAll('[data-go]'), function(b){
    b.onclick = function(){
      var id = +b.dataset.go;
      if(!unlocked(id)){ toast('先通过第 '+(id-1)+' 关'); return; }
      go(id);
    };
  });
  rail.querySelector('[data-a=unlockall]').onclick = function(){
    S.unlocked = true; save(S); buildRail(); refreshHud(); toast('已解锁全部 12 关');
  };
}
function shortTitle(t){
  var m = t.split(/[，,：:（(]/)[0];
  return (m.length > 13 ? m.slice(0,13)+'…' : m);
}
function markCur(id){
  Array.prototype.forEach.call(rail.querySelectorAll('.node'), function(n){
    n.classList.toggle('cur', +n.dataset.go === id);
  });
}

/* ---------- 首页 ---------- */
function renderHome(){
  var totalCards = LV.reduce(function(a,l){ return a+l.cards.length; },0);
  var totalQ = LV.reduce(function(a,l){ return a+l.quiz.length; },0);
  var totalMin = LV.reduce(function(a,l){ return a+l.minutes; },0);
  var h = '';
  h += '<div class="hero">'
    +  '<div class="lv-eyebrow">TEARDOWN BLUEPRINT · 拆机蓝图</div>'
    +  '<h1 class="big">不读这本书。<br><span>把它拆开看。</span></h1>'
    +  '<p class="lede">这是一本 306 页、10 章、108 个实验的 AI Agent 教材的<b>拆机版</b>。'
    +  '我们把它的骨架抽出来，做成 <b>12 个关卡</b>：每关先给你 3 分钟能读完的概念卡，'
    +  '再让你拨动一个模拟器亲眼看它运转，最后用 3 道题确认你真的懂了。'
    +  '全部离线运行，不需要联网、不需要 API key、不需要装任何东西。</p>'
    +  '</div>';
  h += '<div class="tiles">'
    + '<div class="tile"><div class="n">12</div><div class="l">关卡 Levels</div></div>'
    + '<div class="tile"><div class="n">'+totalCards+'</div><div class="l">概念卡 Concept cards</div></div>'
    + '<div class="tile"><div class="n">12</div><div class="l">可交互模拟器 Simulators</div></div>'
    + '<div class="tile"><div class="n">'+totalQ+'</div><div class="l">通关小测 Questions</div></div>'
    + '<div class="tile"><div class="n">'+Math.round(totalMin/60)+'h</div><div class="l">总投入（含动手）</div></div>'
    + '</div>';
  h += '<div class="sec"><span class="ico">🗺</span><span>四幕十二关</span><span class="rule"></span><span class="cnt">点击进入</span></div>';
  C.acts.forEach(function(a){
    var names = a.levels.map(function(id){
      var l = LV.filter(function(x){return x.id===id;})[0];
      return l.title.split(/[，,：:（(]/)[0];
    }).join(' · ');
    h += '<div class="actcard" data-go="'+a.levels[0]+'">'
      +  '<div class="no">0'+a.id+'</div>'
      +  '<div><div class="tt">幕'+['一','二','三','四'][a.id-1]+' · '+a.cn+'<span class="mono" style="font-size:11px;color:var(--paper-3)"> '+a.en+'</span></div>'
      +  '<div style="font-size:13.5px;color:var(--paper-2);margin:4px 0 6px">'+a.desc+'</div>'
      +  '<div class="ll">'+names+'</div></div></div>';
  });
  h += '<div class="sec"><span class="ico">⚙</span><span>怎么用这套东西</span><span class="rule"></span></div>';
  h += '<div class="block" style="border-left-color:var(--cyan)"><span class="lbl">每一关的结构</span>'
    + '<p style="font-size:13.5px;color:var(--paper-2);margin:0">'
    + '<b class="hl">🧠 概念卡</b> —— 折叠卡片，点开看。每张卡都有「核心内容 + 用数据分析打的比方 + 常见误区」三段。<br>'
    + '<b class="hl">🔬 模拟器</b> —— 拨动参数，看系统怎么反应。这是这套东西和读书最大的区别。<br>'
    + '<b class="hl-a">🧪 动手实验</b> —— 配套的离线 Python 脚本，在 <code>labs/</code> 目录里。回到上一级目录双击 <code>开始学习.cmd</code>，按数字就能跑，不用敲命令、不会乱码。<br>'
    + '<b class="hl-m">🎯 通关小测</b> —— 全对才算过关，自动解锁下一关。</p></div>';
  h += '<div class="note"><b>关于难度曲线：</b>第 1–6 关建立结构感，第 7–9 关是你的主场（记忆、检索、工具），'
    + '第 10–12 关（评估、后训练、进化）会大量复用你已有的统计与建模直觉。'
    + '如果时间紧，最低限度请务必打通 <b>第 2 关（ReAct 循环）</b> 和 <b>第 10 关（评估）</b>——这两关是整本书的承重墙。</div>';
  stage.innerHTML = '<div class="stagger">'+h+'</div>';
  Array.prototype.forEach.call(stage.querySelectorAll('[data-go]'), function(b){
    b.onclick = function(){ go(+b.dataset.go); };
  });
  markCur(0);
}

/* ---------- 关卡渲染 ---------- */
function renderLevel(id){
  var l = LV.filter(function(x){ return x.id===id; })[0];
  var a = C.acts.filter(function(x){ return x.id===l.act; })[0];
  var qstate = S.quiz[id] || [];
  var h = '';

  h += '<div class="lv-head">'
    + '<div class="lv-eyebrow">幕'+['一','二','三','四'][a.id-1]+' · '+a.cn+' &nbsp;/&nbsp; LEVEL '+String(id).padStart(2,'0')+'</div>'
    + '<h1 class="lv-title">'+l.title+'</h1>'
    + '<p class="lv-tag">'+l.tagline+'</p>'
    + '<div class="lv-meta">'
    +   '<span class="chip cyan">⏱ 约 '+l.minutes+' 分钟</span>'
    +   '<span class="chip">📖 '+l.ref+'</span>'
    +   '<span class="chip amber">'+l.cards.length+' 张概念卡</span>'
    +   '<span class="chip amber">'+l.quiz.length+' 道通关题</span>'
    +   (isDone(id) ? '<span class="chip" style="border-color:var(--green);color:var(--green)">✔ 已通关</span>' : '')
    + '</div></div>';

  h += '<div class="block" style="border-left-color:var(--cyan)"><span class="lbl">为什么这一关值得花时间</span>'
    +  '<p style="margin:0;font-size:14px;color:var(--paper)">'+l.why+'</p></div>';

  /* --- 概念卡 --- */
  h += '<div class="sec"><span class="ico">🧠</span><span>3 分钟掰碎</span><span class="rule"></span><span class="cnt">'+l.cards.length+' 张卡 · 点击展开</span></div>';
  l.cards.forEach(function(c, i){
    var tagCls = (i===0?'':(i===l.cards.length-1?'m':(i%2?'a':'')));
    h += '<div class="card'+(i===0?' open':'')+'" data-card="'+i+'">'
      +  '<div class="card-head"><span class="card-tag '+tagCls+'">'+c.tag+'</span>'
      +  '<span class="card-t">'+c.title+'</span><span class="card-toggle">+</span></div>'
      +  '<div class="card-body">'+c.body
      +    (c.analogy ? '<div class="block analogy"><span class="lbl">用你熟悉的东西打个比方</span><p class="txt">'+c.analogy+'</p></div>' : '')
      +    (c.pitfall ? '<div class="block pitfall"><span class="lbl">常见误区</span><p class="txt">'+c.pitfall+'</p></div>' : '')
      +  '</div></div>';
  });

  /* --- 模拟器 --- */
  if(l.sim){
    h += '<div class="sec"><span class="ico">🔬</span><span>动手：拧一下旋钮</span><span class="rule"></span><span class="cnt">交互式</span></div>';
    h += '<div class="sim"><div class="sim-top"><span class="dot"></span>'
      +  '<span class="nm">'+l.sim.name+'</span><span class="hint">'+l.sim.hint+'</span></div>'
      +  '<div class="sim-body" id="simbox"></div></div>';
  }

  /* --- 实验 --- */
  if(l.labs && l.labs.length){
    h += '<div class="sec"><span class="ico">🧪</span><span>动手：把代码跑起来</span><span class="rule"></span><span class="cnt">离线 · 零依赖</span></div>';
    l.labs.forEach(function(lb){
      h += '<div class="lab"><div class="ic">▸</div><div class="bd">'
        + '<div class="fn">python '+lb.file+'</div>'
        + '<div style="font-family:var(--f-display);font-size:16px;color:#e8f4ff;margin:3px 0 6px">'+lb.title+'</div>'
        + '<div class="ds">'+lb.what+'</div>'
        + '<div class="ds" style="margin-top:6px;color:var(--paper-3)"><b class="hl-a">你会看到：</b>'+lb.expect+'</div>'
        + '</div></div>';
    });
  }

  /* --- 测验 --- */
  h += '<div class="sec"><span class="ico">🎯</span><span>通关小测</span><span class="rule"></span><span class="cnt" id="qcnt">0 / '+l.quiz.length+'</span></div>';
  h += '<div id="quizbox"></div>';

  /* --- 带走 --- */
  h += '<div class="take"><div class="lbl">一句话带走</div><div class="tx">'+l.takeaway+'</div></div>';

  h += '<div class="nextbar">'
    + '<button class="btn ghost" data-a="home">← 返回总览</button>'
    + '<span style="flex:1"></span>'
    + '<button class="btn" id="nextbtn">'+(id<LV.length?'下一关 →':'重新开始')+'</button>'
    + '</div>';

  stage.innerHTML = '<div class="stagger">'+h+'</div>';
  stage.scrollTop = 0;
  document.getElementById('main').scrollTop = 0;
  markCur(id);

  /* 卡片折叠 */
  Array.prototype.forEach.call(stage.querySelectorAll('[data-card]'), function(c){
    c.querySelector('.card-head').onclick = function(){ c.classList.toggle('open'); };
  });

  /* 模拟器挂载 */
  if(l.sim && window.SIMS[l.sim.type]){
    try{ window.SIMS[l.sim.type](document.getElementById('simbox')); }
    catch(e){ document.getElementById('simbox').innerHTML = '<div class="small">模拟器加载失败：'+e.message+'</div>'; }
  }

  /* 测验 */
  buildQuiz(l, qstate);

  /* 底部按钮 */
  stage.querySelector('[data-a=home]').onclick = function(){ go(0); };
  document.getElementById('nextbtn').onclick = function(){
    if(id < LV.length){ go(id+1); } else { go(0); }
  };
}

function buildQuiz(l, qstate){
  var box = document.getElementById('quizbox');
  box.innerHTML = '';
  l.quiz.forEach(function(q, qi){
    var done = qstate[qi] !== undefined;
    var d = document.createElement('div');
    d.className = 'quiz';
    var h = '<div class="qn">Q'+(qi+1)+' / '+l.quiz.length+'</div><div class="q">'+q.q+'</div>';
    q.opts.forEach(function(o, oi){
      var cls = 'opt';
      if(done){
        if(oi === q.a) cls += ' right';
        else if(oi === qstate[qi]) cls += ' wrong';
        cls += ' dead';
      }
      h += '<button class="'+cls+'" data-o="'+oi+'"><span class="kk">'+'ABCD'[oi]+'</span><span>'+o+'</span></button>';
    });
    h += '<div class="explain'+(done?' show':'')+'"><b>解析：</b>'+q.why+'</div>';
    d.innerHTML = h;
    box.appendChild(d);

    Array.prototype.forEach.call(d.querySelectorAll('.opt'), function(b){
      b.onclick = function(){
        if(S.quiz[l.id] && S.quiz[l.id][qi] !== undefined) return;
        var oi = +b.dataset.o;
        S.quiz[l.id] = S.quiz[l.id] || [];
        S.quiz[l.id][qi] = oi;
        var right = oi === q.a;
        if(right){
          S.xp += 10;
          toast('✔ 答对了  +10 XP');
        } else {
          toast('✘ 再想想 —— 看下面的解析');
        }
        save(S); refreshHud();
        // 就地刷新这一题
        Array.prototype.forEach.call(d.querySelectorAll('.opt'), function(x, xi){
          x.classList.add('dead');
          if(xi === q.a) x.classList.add('right');
          else if(xi === oi) x.classList.add('wrong');
        });
        d.querySelector('.explain').classList.add('show');
        updateCount(l);
      };
    });
  });
  updateCount(l);
}

function updateCount(l){
  var st = S.quiz[l.id] || [];
  var answered = st.filter(function(x){ return x !== undefined; }).length;
  var cnt = document.getElementById('qcnt');
  if(cnt) cnt.textContent = answered + ' / ' + l.quiz.length;
  if(answered === l.quiz.length && !isDone(l.id)){
    // 通关
    var correct = st.filter(function(x, i){ return x === l.quiz[i].a; }).length;
    if(correct === l.quiz.length){
      S.done.push(l.id);
      S.xp += 40;
      save(S); refreshHud(); buildRail(); markCur(l.id);
      toast('★ 第 ' + l.id + ' 关通关  +40 XP');
      var chip = stage.querySelector('.lv-meta');
      if(chip && !chip.querySelector('.done-chip')){
        var s = document.createElement('span');
        s.className = 'chip done-chip';
        s.style.borderColor = 'var(--green)'; s.style.color = 'var(--green)';
        s.textContent = '✔ 已通关';
        chip.appendChild(s);
      }
    } else {
      toast('答对 ' + correct + ' / ' + l.quiz.length + ' —— 全部答对才能通关，可重看解析');
    }
  }
}

/* ---------- 路由（支持 #L3 这样的地址，可直接收藏/刷新回到某一关） ---------- */
function setHash(id){
  // replaceState 不触发 hashchange，也不会重新加载页面；file:// 下若被拒就静默忽略
  try{ history.replaceState(null, '', '#' + (id===0 ? '' : 'L'+id)); }catch(e){}
}
function hashLevel(){
  var m = /L?(\d+)/.exec(String(location.hash || '').replace(/^#/, ''));
  return m ? +m[1] : 0;
}
function go(id, force){
  setHash(id);
  if(id === 0){ renderHome(); return; }
  // 从地址栏直接进来的关卡视为用户主动选择，不再拦截（方便收藏某一关）
  if(!force && !unlocked(id)){ toast('先通过第 '+(id-1)+' 关'); return; }
  var st = S.quiz[id] || [];
  // 每次进入给一次「阅读奖励」，但不重复给
  if(!S.seen) S.seen = [];
  if(S.seen.indexOf(id) < 0){ S.seen.push(id); S.xp += 10; save(S); refreshHud(); }
  renderLevel(id);
  save(S);
}

/* ---------- 启动 ---------- */
document.getElementById('resetbtn').onclick = function(){
  if(!confirm('确定要清空全部进度、XP 和答题记录吗？')) return;
  S = { xp:0, done:[], quiz:{}, unlocked:false, seen:[] };
  save(S); buildRail(); refreshHud(); go(0); toast('进度已重置');
};
document.getElementById('homebtn').onclick = function(){ go(0); };
window.addEventListener('hashchange', function(){ go(hashLevel(), true); });

buildRail();
refreshHud();
go(hashLevel(), true);

})();
