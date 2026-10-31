/** Attack/end-turn regression using visible seat DTO, normal controls and APIs. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {chromium} from 'file:///C:/Users/Administrator/.codex/skills/develop-web-game/node_modules/playwright/index.mjs';
const args=Object.fromEntries(process.argv.slice(2).reduce((r,v,i,a)=>{if(v.startsWith('--'))r.push([v.slice(2),a[i+1]]);return r;},[]));
const output=path.resolve(args.output||`outputs/web-ui-attack-20261014/browser-${Date.now()}`),base=args.url||'http://127.0.0.1:8765/';
await fs.mkdir(output,{recursive:true});
const files=['web_ui/server.py','web_ui/bot.py','web_ui/static/app.js','web_ui/static/style.css','web_ui/static/index.html','tools/test_web_ui_attack_browser.mjs'];
const hashes=async()=>Object.fromEntries(await Promise.all(files.map(async f=>[f,createHash('sha256').update(await fs.readFile(f)).digest('hex')])));
const report={started:new Date().toISOString(),checks:[],captures:[],actions:[],aiResponses:[],errors:[],expectedErrors:[],pageErrors:[],timings:[],sourceBefore:await hashes()};
const browser=await chromium.launch({headless:true});
let currentPage,scenario='',expectedStale=false;
const pages=[];
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const check=(name,details={})=>{report.checks.push({scenario,name,...details});console.log('PASS '+scenario+': '+name);};
const state=async p=>JSON.parse(await p.locator('#dto').textContent());
const own=m=>m.observation.players.find(p=>p.id===m.seat),foe=m=>m.observation.players.find(p=>p.id!==m.seat);
const byRef=(p,r)=>p.locator(`.card[data-ref="${r}"]`);
const green=p=>p.locator('#end').evaluate(n=>n.classList.contains('ready-to-end'));
async function idle(p){await p.waitForFunction(()=>document.body.dataset.busy!=='true');}
async function newGame(name,mode='human',motion='no-preference'){
  scenario=name;
  const context=await browser.newContext({viewport:{width:1280,height:720},reducedMotion:motion});
  await context.addInitScript(()=>{
    const log=window.__attackTrace={frames:[],animations:[],busy:[],resources:[],longTasks:[],violations:[]};
    const original=Element.prototype.animate;
    Element.prototype.animate=function(frames,options){const a=original.call(this,frames,options);const row={at:performance.now(),end:null,classes:this.className?.baseVal??this.className,duration:typeof options==='number'?options:options?.duration};log.animations.push(row);a.finished.then(()=>row.end=performance.now(),()=>row.end=performance.now());return a;};
    new PerformanceObserver(list=>{for(const e of list.getEntries())if(e.name.includes('/api/'))log.resources.push({url:new URL(e.name).pathname,at:e.startTime,end:e.responseEnd,duration:e.duration});}).observe({type:'resource',buffered:true});
    new PerformanceObserver(list=>{for(const e of list.getEntries())log.longTasks.push({at:e.startTime,duration:e.duration});}).observe({type:'longtask',buffered:true});
    document.addEventListener('DOMContentLoaded',()=>new MutationObserver(()=>log.busy.push({at:performance.now(),busy:document.body.dataset.busy==='true'})).observe(document.body,{attributes:true,attributeFilter:['data-busy']}));
    const rect=n=>{if(!n)return null;const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2};};
    function frame(){
      const attacker=document.querySelector('.fx-attacker');const trail=document.querySelector('.fx-attack-trail'),impact=document.querySelector('.fx-impact');
      if(attacker||trail||impact)log.frames.push({at:performance.now(),phase:attacker?.dataset.attackPhase||'',clone:rect(attacker),trail:rect(trail),impact:rect(impact),running:document.getAnimations().filter(a=>a.playState==='running').length,busy:document.body.dataset.busy==='true',green:document.getElementById('end')?.classList.contains('ready-to-end')});
      const end=document.getElementById('end');
      if(end?.classList.contains('ready-to-end')){try{const m=JSON.parse(document.getElementById('dto').textContent);if(document.body.dataset.busy==='true'||m.observation.pending_choice||m.observation.status!=='playing'||m.observation.active_player!==m.seat||!m.actions.some(a=>a.type==='end_turn')||m.actions.some(a=>!['end_turn','concede'].includes(a.type)))log.violations.push({at:performance.now(),busy:document.body.dataset.busy,types:m.actions.map(a=>a.type)});}catch{}}
      requestAnimationFrame(frame);
    }requestAnimationFrame(frame);
  });
  const p=await context.newPage();currentPage=p;pages.push({name,page:p});
  p.on('console',m=>{if(m.type()==='error'){const record={scenario:name,text:m.text()};(expectedStale&&/409/.test(m.text())?report.expectedErrors:report.errors).push(record);}});
  p.on('pageerror',e=>report.pageErrors.push({scenario:name,text:e.message}));
  p.on('request',r=>{if(r.url().endsWith('/api/action'))report.actions.push({scenario:name,type:r.postDataJSON().action.type,action:r.postDataJSON().action});});
  p.on('response',r=>{if(r.url().endsWith('/api/opponent/step'))report.aiResponses.push({scenario:name,status:r.status()});});
  await p.goto(base,{waitUntil:'networkidle'});await p.locator('#preset').selectOption('practice');await p.locator('#opponent-mode').selectOption(mode);await p.locator('#create').click();
  await p.waitForFunction(()=>document.getElementById('dto').textContent.startsWith('{')&&document.body.dataset.busy!=='true');return p;
}
async function finish(p,r){assert.equal(r.status(),200);const m=await r.json();if('accepted'in m)assert.equal(m.accepted,true,m.command_error);await p.waitForFunction(rev=>{try{return JSON.parse(document.getElementById('dto').textContent).revision===rev&&document.body.dataset.busy!=='true';}catch{return false;}},m.revision);return m;}
async function command(p,click,type){const pending=p.waitForResponse(r=>r.url().endsWith('/api/action')&&r.request().postDataJSON().action.type===type);await click();return finish(p,await pending);}
async function mana(p,value){const pending=p.waitForResponse(r=>r.url().endsWith('/api/test/mana'));if(value===10)await p.locator('#mana-ten').click();else{await p.locator('#test-mana').fill(String(value));await p.locator('#apply-mana').click();}return finish(p,await pending);}
async function capture(p,name,live=false){if(!live){await p.mouse.move(3,3);await wait(80);}const file=path.join(output,name+'.png');await p.screenshot({path:file,fullPage:true,animations:'allow'});report.captures.push({name,file});await fs.writeFile(path.join(output,name+'-visible.json'),await p.evaluate(()=>render_game_to_text()));}
async function ordinaryApi(p,endpoint,body){const token=await p.evaluate(()=>sessionStorage.getItem('hs-seat'));return p.request.post(base+'api/'+endpoint,{headers:{Authorization:'Bearer '+token},data:body});}
async function concede(p){await p.locator('#diagnostics > summary').click();await p.getByText('完整合法操作',{exact:false}).first().click();const button=p.locator('#actions button').filter({hasText:/^认输$/});await button.click();return command(p,()=>button.click(),'concede');}

try{
  const p=await newGame('end-readiness-and-human-attack');let m=await state(p);
  assert.equal(await green(p),false);check('initial playable cards do not make end turn green');
  m=await mana(p,0);assert.ok(m.actions.some(a=>a.type==='attack'));assert.equal(await green(p),false);check('zero mana still permits attack and does not make end turn green');
  let attack=m.actions.find(a=>a.type==='attack'&&a.defender===foe(m).hero.ref);assert.ok(attack);

  // Cause a real stale rejection by changing only this test session through the normal API.
  const changed=await ordinaryApi(p,'test/mana',{revision:m.revision,mana:10});assert.equal(changed.status(),200);assert.notEqual((await changed.json()).revision,m.revision);
  await byRef(p,attack.attacker).click();expectedStale=true;
  const rejected=p.waitForResponse(r=>r.url().endsWith('/api/action'));
  await byRef(p,attack.defender).click();const denied=await rejected;assert.equal(denied.status(),200);const denial=await denied.json();assert.equal(denial.accepted,false);assert.equal(denial.command_error,'stale_observation');await idle(p);await wait(80);expectedStale=false;
  assert.equal((await p.evaluate(()=>window.__attackTrace.frames)).length,0);
  await p.locator('#refresh').click();await idle(p);m=await state(p);assert.equal(foe(m).hero.health,30);
  check('a genuine stale command rejects without an attack animation or damage');
  m=await mana(p,0);attack=m.actions.find(a=>a.type==='attack'&&a.defender===foe(m).hero.ref);
  const originalRect=await byRef(p,attack.attacker).boundingBox();
  await byRef(p,attack.attacker).click();
  let release,arrive;const gate=new Promise(r=>release=r),arrived=new Promise(r=>arrive=r);
  const hold=async route=>{arrive();await gate;await route.continue();};await p.route('**/api/action',hold);
  const start=await p.evaluate(()=>performance.now()),oldCount=report.actions.filter(x=>x.type==='attack').length;
  const accepted=p.waitForResponse(r=>r.url().endsWith('/api/action'));
  await byRef(p,attack.defender).dblclick({delay:20});await arrived;await wait(120);
  assert.equal(await p.locator('.fx-attacker,.fx-attack-trail,.fx-impact').count(),0);
  assert.equal(await green(p),false);assert.equal(await p.locator('#end').isDisabled(),true);
  check('pending command stays locked without premature attack visuals');release();const acceptedResponse=await accepted;assert.equal(acceptedResponse.status(),200);
  await p.waitForFunction(()=>{const hit=document.querySelector('.fx-impact');return document.querySelector('.fx-attacker[data-attack-phase]')&&hit&&Number(getComputedStyle(hit).opacity)>.2&&document.getAnimations().some(a=>a.playState==='running');},null,{timeout:4000,polling:'raf'});
  assert.equal(await green(p),false);await capture(p,'human-attack-in-motion',true);
  m=await finish(p,acceptedResponse);await p.unroute('**/api/action',hold);await wait(90);
  assert.equal(report.actions.filter(x=>x.type==='attack').length-oldCount,1);assert.equal(foe(m).hero.health,27);assert.equal(own(m).mana,0);
  const afterRect=await byRef(p,attack.attacker).boundingBox();for(const key of ['x','y','width','height'])assert.ok(Math.abs(afterRect[key]-originalRect[key])<2,`Attacker did not return: ${key}`);
  assert.equal(await byRef(p,attack.attacker).isVisible(),true);assert.equal(await p.locator('.fx-attacker,.fx-attack-trail,.fx-impact').count(),0);
  const trace=await p.evaluate(()=>window.__attackTrace),frames=trace.frames.filter(x=>x.at>=start),phases=[...new Set(frames.map(x=>x.phase).filter(Boolean))];
  for(const phase of ['windup','lunge','impact','return'])assert.ok(phases.includes(phase),`Missing phase ${phase}`);
  assert.ok(frames.some(x=>x.trail&&x.trail.width>0&&x.running>0));assert.ok(frames.some(x=>x.impact&&x.impact.width>0));
  const cloneFrames=frames.filter(x=>x.clone),maxTravelPx=Math.max(...cloneFrames.map(x=>Math.hypot(x.clone.cx-(originalRect.x+originalRect.width/2),x.clone.cy-(originalRect.y+originalRect.height/2))));assert.ok(maxTravelPx>40);
  assert.ok(frames.every(x=>!x.green));
  const resource=trace.resources.filter(x=>x.url==='/api/action'&&x.at>=start).at(-1),end=trace.busy.find(x=>!x.busy&&x.at>resource.end)?.at;
  const visualBusyMs=end-resource.end;report.timings.push({name:'human-attack',requestMs:resource.duration,requestIncludesDeliberateGate:true,visualBusyMs});assert.ok(visualBusyMs<=850,`Visual lock too long: ${visualBusyMs}`);
  check('accepted attack lunges, collides and returns; double click submits once',{phases,visualBusyMs,maxTravelPx});
  assert.ok(m.actions.some(a=>a.type==='end_turn'));assert.ok(m.actions.every(a=>['end_turn','concede'].includes(a.type)));assert.equal(await green(p),true);check('only end turn and concede remaining makes end turn green');await capture(p,'green-end-turn');

  let releaseMana,arriveMana;const manaGate=new Promise(r=>releaseMana=r),manaArrived=new Promise(r=>arriveMana=r);
  const holdMana=async route=>{arriveMana();await manaGate;await route.continue();};await p.route('**/api/test/mana',holdMana);
  const manaPending=p.waitForResponse(r=>r.url().endsWith('/api/test/mana'));await p.locator('#mana-ten').click();await manaArrived;assert.equal(await green(p),false);assert.equal(await p.locator('#end').isDisabled(),true);releaseMana();m=await finish(p,await manaPending);await p.unroute('**/api/test/mana',holdMana);
  assert.equal(await green(p),false);assert.ok(m.actions.some(a=>a.type==='play_card'));check('busy lock clears green and restoring ten mana stays non-green');
  await mana(p,0);assert.equal(await green(p),true);await command(p,()=>p.locator('#end').click(),'end_turn');assert.equal(await green(p),false);assert.equal(await p.locator('#end').isDisabled(),true);check('opposing turn is disabled and not green');

  const choices=await newGame('choice-and-gameover');m=await state(choices);
  const visions=own(m).hand.find(c=>c.card_id==='UNG_029');m=await command(choices,()=>byRef(choices,visions.ref).click(),'play_card');assert.ok(m.observation.pending_choice);assert.equal(await green(choices),false);assert.equal(await choices.locator('#end').isDisabled(),true);check('pending discovery is not green');
  await choices.locator('#choice input[type=checkbox]').first().check();await command(choices,()=>choices.getByRole('button',{name:'确认选择',exact:true}).click(),'select_choice');
  m=await concede(choices);assert.notEqual(m.observation.status,'playing');assert.equal(await green(choices),false);assert.equal(await choices.locator('#end').isDisabled(),true);check('finished game is not green');

  const ai=await newGame('ai-public-attack','ai');
  const aiStart=await ai.evaluate(()=>performance.now());await command(ai,()=>ai.locator('#end').click(),'end_turn');
  await ai.waitForFunction(()=>{const hit=document.querySelector('.fx-impact');return document.querySelector('.fx-attacker[data-attack-phase]')&&hit&&Number(getComputedStyle(hit).opacity)>.2;},null,{timeout:25000,polling:'raf'});await capture(ai,'ai-attack-in-motion',true);
  await ai.waitForFunction(()=>{const m=JSON.parse(document.getElementById('dto').textContent);return m.observation.turn>=3&&m.observation.active_player===m.seat&&!m.observation.pending_choice&&document.body.dataset.busy!=='true';},null,{timeout:45000});
  const aiTrace=await ai.evaluate(()=>window.__attackTrace);const aiFrames=aiTrace.frames.filter(x=>x.at>=aiStart);
  assert.ok(aiFrames.some(x=>x.phase==='lunge'));assert.ok(aiFrames.some(x=>x.impact));assert.ok(aiFrames.every(x=>!x.green));assert.equal(await ai.locator('.fx-attacker,.fx-attack-trail,.fx-impact').count(),0);
  check('computer attacks show the public lunge and impact before returning control',{phases:[...new Set(aiFrames.map(x=>x.phase).filter(Boolean))],steps:report.aiResponses.length});await capture(ai,'ai-round-complete');

  const reduced=await newGame('reduced-motion','human','reduce');m=await state(reduced);attack=m.actions.find(a=>a.type==='attack'&&a.defender===foe(m).hero.ref);await byRef(reduced,attack.attacker).click();m=await command(reduced,()=>byRef(reduced,attack.defender).click(),'attack');assert.equal(foe(m).hero.health,27);assert.equal((await reduced.evaluate(()=>window.__attackTrace.frames)).length,0);assert.equal(await reduced.locator('.fx-attacker,.fx-attack-trail,.fx-impact').count(),0);check('reduced motion submits the same legal attack without attack effects');
  report.traces=[];for(const item of pages){const trace=await item.page.evaluate(()=>window.__attackTrace);assert.deepEqual(trace.violations,[]);report.traces.push({scenario:item.name,...trace});}
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.pageErrors,[]);assert.ok(report.aiResponses.every(x=>x.status===200));check('no incorrect green frames or unexpected console errors');
  report.sourceAfter=await hashes();assert.deepEqual(report.sourceAfter,report.sourceBefore);check('source bytes are stable');report.passed=true;
}catch(e){report.passed=false;report.failure={scenario,message:e.message,stack:e.stack};process.exitCode=1;console.error(e);if(currentPage){await currentPage.screenshot({path:path.join(output,'failure.png'),fullPage:true});await fs.writeFile(path.join(output,'failure-visible.json'),await currentPage.evaluate(()=>render_game_to_text()));}}
finally{report.sourceAfter=await hashes();report.sourcesStable=JSON.stringify(report.sourceAfter)===JSON.stringify(report.sourceBefore);report.finished=new Date().toISOString();await fs.writeFile(path.join(output,'browser-regression.json'),JSON.stringify(report,null,2));await browser.close();console.log('Report: '+output);}
