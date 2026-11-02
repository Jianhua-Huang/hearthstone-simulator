'use strict';
const $=id=>document.getElementById(id);
let report=null,polling=false;
const ready=new Set();
const labels={ready:'准备就绪',running:'运行中',pausing:'等待当前动作结束',paused:'已暂停',finished:'本批完成',error:'异常停止',completed:'对局结束',turn_limit:'达到回合上限',step_limit:'达到动作上限',stopped:'已停止'};
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const ms=v=>v==null?'—':v>=1000?(v/1000).toFixed(2)+'秒':Math.round(v)+'毫秒';
async function command(path){const r=await fetch('/audit/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!r.ok)throw Error('控制请求失败');await refresh();}
$('start').onclick=()=>command('start').catch(showError);$('pause').onclick=()=>command('pause').catch(showError);
function showError(e){$('error').textContent=e.message;}
$('export').onclick=()=>{if(!report)return;const u=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=node('a');a.href=u;a.download='shaman-priest-audit.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
async function updateBoard(env){if(!ready.has(env))return;const seat=$('seat-'+env).value;const r=await fetch(`/audit/view?env=${env}&seat=${seat}`);if(!r.ok)throw Error('场面读取失败');const d=await r.json();if(d.data)$('board-'+env).contentWindow.postMessage({type:'lab:preview',request:report?.action_count,data:d.data},location.origin);}
for(const env of ['A','B'])$('seat-'+env).onchange=()=>updateBoard(env).catch(showError);
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.data?.type!=='lab:ready')return;for(const env of ['A','B'])if(e.source===$('board-'+env).contentWindow){ready.add(env);void updateBoard(env);}});
function paint(){
 const r=report,finished=r.games.filter(g=>g.status!=='running').length;
 $('summary').replaceChildren(...[[labels[r.status]||r.status,'测试状态'],[r.action_count,'已执行动作'],[finished+' / '+(r.games.length||'—'),'已结束 / 已启动对局'],[ms(r.timing.p95_ms),'命令耗时 P95'],[r.anomalies.length,'已记录异常']].map(([value,label])=>{const n=node('div',null,'metric');n.append(node('b',String(value)),node('span',label));return n;}));
 const p=r.phase,elapsed=p.started_at?Math.max(0,Date.now()/1000-p.started_at):0;
 $('phase').textContent=p.game_id?`${p.game_id} · 第 ${p.step+1} 个动作 · 座位 ${p.actor} · ${p.stage}${r.status==='running'?' · 当前阶段 '+elapsed.toFixed(1)+'秒':''}`:'两个环境按顺序运行，以减少相互争用CPU。';
 $('start').disabled=['running','finished','error','pausing'].includes(r.status);$('pause').disabled=r.status!=='running';
 $('games').replaceChildren(...r.games.map(g=>{const n=node('div',null,'row'+(g.status==='error'?' bad':''));n.append(node('span',`${g.id} · 种子 ${g.seed} · ${g.turn}回合 / ${g.steps}动作`),node('small',labels[g.status]||g.status));return n;}));
 $('findings').replaceChildren(...r.anomalies.slice().reverse().map(f=>{const n=node('div',null,'row '+(f.accepted?'warn':'bad'));n.append(node('span',`${f.id} · ${f.card_name||f.action_type} · ${f.reason}`),node('small',`结算 ${ms(f.timings.submit_ms)} / 查询 ${ms(f.timings.query_ms)}`));return n;}));
 $('coverage').replaceChildren(node('p',`描述片段：通过 ${r.effect_components.pass||0}，待核验 ${r.effect_components.needs_review||0}，明确失败 ${r.effect_components.fail||0}`,'coverage-note'),...r.coverage.map(c=>{const n=node('div',null,'row');n.append(node('span',c.name),node('small',c.actions?`${c.plays} 次出牌 · ${c.checks.pass||0} 片段通过 / ${c.checks.needs_review||0} 待核验`:'尚未出场'));return n;}));
 if(!$('decks').children.length)for(const [key,d]of Object.entries(r.decks)){const section=node('section');section.append(node('h2',(key==='shaman'?'兆示萨满':'控制牧师')+' · 30张'));for(const card of d.rows){const tile=node('div',null,'deck-card');tile.append(node('b',`${card.count} × ${card.name}`),node('p',card.text.replace(/<[^>]*>/g,'').replace(/\[x\]/g,'')));section.append(tile);}$('decks').append(section);}
 $('scope').textContent=JSON.stringify({target:r.target,run:r.run_id,limits:r.limits},null,2);
}
async function refresh(){if(polling)return;polling=true;try{const r=await fetch('/audit/status');if(!r.ok)throw Error('测试服务读取失败');report=await r.json();paint();await Promise.all(['A','B'].map(updateBoard));$('error').textContent='';}catch(e){showError(e);}finally{polling=false;}}
window.render_game_to_text=()=>JSON.stringify(report?{status:report.status,games:report.games,actions:report.action_count,timing:report.timing,effects:report.effect_components,anomalies:report.anomalies.length}:{});
window.advanceTime=async()=>{};
setInterval(()=>void refresh(),1500);void refresh();
