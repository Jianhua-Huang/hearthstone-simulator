/** Visual-card regression using visible seat DTOs and normal UI commands only. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {chromium} from 'file:///C:/Users/Administrator/.codex/skills/develop-web-game/node_modules/playwright/index.mjs';

const args=Object.fromEntries(process.argv.slice(2).reduce((rows,value,i,all)=>{if(value.startsWith('--'))rows.push([value.slice(2),all[i+1]]);return rows;},[]));
const base=args.url||'http://127.0.0.1:8765/';
const output=path.resolve(args.output||`outputs/web-ui-card-visuals-20261014/browser-${Date.now()}`);
const sources=['web_ui/server.py','web_ui/bot.py','web_ui/static/app.js','web_ui/static/style.css','web_ui/static/index.html','tools/test_web_ui_visual_cards_browser.mjs'];
sources.push(...['cards.json','registry-card-art-manifest.json','CORE_REV_990.webp','SC_403.webp','GDB_100.webp','EX1_332.webp','CS2_179.webp',...['a','b','c','d','f'].map(s=>'SC_403'+s+'.webp')].map(f=>'web_ui/static/assets/'+f));
const hashes=async()=>Object.fromEntries(await Promise.all(sources.map(async f=>[f,createHash('sha256').update(await fs.readFile(f)).digest('hex')])));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const redact=s=>String(s).replace(/Bearer\s+\S+/gi,'Bearer [REDACTED]');
const own=m=>m.observation.players.find(p=>p.id===m.seat),foe=m=>m.observation.players.find(p=>p.id!==m.seat);
const state=async p=>JSON.parse(await p.locator('#dto').textContent());
const card=(p,ref)=>p.locator(`.card[data-ref="${ref}"]`);
const report={started:new Date().toISOString(),checks:[],requests:[],captures:[],images:[],geometry:[],consoleErrors:[],pageErrors:[],privacyViolations:[]};
let scenario='',browser,currentPage;
const pendingAudits=[];
const check=(name,detail={})=>{report.checks.push({scenario,name,...detail});console.log(`PASS ${scenario}: ${name}`);};
async function settled(p){await p.waitForFunction(()=>document.body.dataset.busy!=='true',null,{timeout:25000});}
async function finish(p,r){assert.equal(r.status(),200,await r.text());const m=await r.json();if('accepted'in m)assert.equal(m.accepted,true,m.command_error);await p.waitForFunction(revision=>{try{return JSON.parse(document.getElementById('dto').textContent).revision===revision&&document.body.dataset.busy!=='true';}catch{return false;}},m.revision,{timeout:25000});return m;}
async function action(p,click,type){const r=p.waitForResponse(r=>r.url().endsWith('/api/action')&&r.request().postDataJSON()?.action?.type===type);await click();return finish(p,await r);}
function audit(m){
  if(!m.observation)return;
  for(const k of ['snapshot','history','rng_state','test_segments','bot_action','opponent_action'])assert.ok(!(k in m));
  for(const c of foe(m).hand)if(!c.card_id)for(const k of ['cost','attack','health','text'])assert.ok(!(k in c));
  const visible=new Set();function visit(v){if(Array.isArray(v))v.forEach(visit);else if(v&&typeof v==='object'){if(typeof v.card_id==='string')visible.add(v.card_id);Object.values(v).forEach(visit);}}
  visit(m.observation);visit(m.events);visit(m.actions);for(const id of Object.keys(m.card_texts||{}))assert.ok(visible.has(id));
}
async function newGame(name){
  scenario=name;const context=await browser.newContext({viewport:{width:1280,height:720}});const p=await context.newPage();currentPage=p;p.setDefaultTimeout(20000);
  p.on('console',m=>{if(m.type()==='error')report.consoleErrors.push({scenario:name,text:m.text()});});p.on('pageerror',e=>report.pageErrors.push({scenario:name,message:e.message}));
  p.on('request',r=>{if(r.url().includes('/api/')){const d=r.postDataJSON();report.requests.push({scenario:name,path:new URL(r.url()).pathname,type:d?.action?.type||null,card_id:d?.card_id||null});}});
  p.on('response',r=>{if(r.url().includes('/api/'))pendingAudits.push((async()=>{try{audit(await r.json());}catch(e){report.privacyViolations.push({scenario:name,message:e.message});}})());});
  await p.goto(base,{waitUntil:'networkidle'});await p.locator('#preset').selectOption('practice');await p.locator('#opponent-mode').selectOption('human');await p.locator('#create').click();await p.waitForFunction(()=>document.getElementById('dto').textContent.startsWith('{')&&document.body.dataset.busy!=='true');return p;
}
async function capture(p,name){await p.mouse.move(3,3);await pause(100);const file=path.join(output,name+'.png');await p.screenshot({path:file,fullPage:true});report.captures.push({name,file});await fs.writeFile(path.join(output,name+'-visible.json'),await p.evaluate(()=>render_game_to_text()));}
async function add(p,id){
  const before=await state(p),refs=new Set(own(before).hand.map(c=>c.ref));await p.locator('#open-card-lab').click();await p.waitForFunction(()=>document.getElementById('card-lab-count').textContent.startsWith('找到')&&document.body.dataset.busy!=='true');
  await p.locator('#card-search').fill(id);await p.waitForFunction(id=>{const i=document.querySelector(`#card-results article[data-card-id="${id}"] img`);return i?.complete&&i.naturalWidth>0;},id);const r=p.waitForResponse(r=>r.url().endsWith('/api/test/hand'));await p.locator(`#card-results button[data-add-card="${id}"]`).click();const m=await finish(p,await r);await p.locator('#close-card-lab').click();const c=own(m).hand.find(c=>!refs.has(c.ref));assert.equal(c?.card_id,id);return c;
}
async function manaTen(p){const r=p.waitForResponse(r=>r.url().endsWith('/api/test/mana'));await p.locator('#mana-ten').click();return finish(p,await r);}
async function exposed(p,ref){
  await p.mouse.move(3,3);await pause(160);
  const point=await card(p,ref).evaluate(n=>{const r=n.getBoundingClientRect();for(const yf of [.5,.3,.7,.15,.85])for(const xf of [.12,.25,.4,.5,.65,.8,.9]){const x=r.left+r.width*xf,y=r.top+r.height*yf;if(x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&document.elementFromPoint(x,y)?.closest('.card')===n)return{x,y};}return null;});assert.ok(point,`No exposed clickable point on ${ref}`);return point;
}
async function clickCard(p,ref){const point=await exposed(p,ref);await p.mouse.click(point.x,point.y);}
async function imageCheck(p,ref,preview=false){
  const n=card(p,ref);await n.locator('img.portrait').waitFor({state:'attached'});await p.waitForFunction(ref=>{const i=document.querySelector(`.card[data-ref="${ref}"] img.portrait`);return i?.complete&&i.naturalWidth>0;},ref);
  const row=await n.locator('img.portrait').evaluate(i=>{const r=i.getBoundingClientRect(),b=i.closest('.card').getBoundingClientRect();return{src:i.getAttribute('src'),naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight,width:r.width,height:r.height,cardWidth:b.width,cardHeight:b.height};});assert.ok(row.width<=row.cardWidth+1&&row.height<=row.cardHeight+1);report.images.push({scenario,ref,...row});
  if(preview){const point=await exposed(p,ref);await p.mouse.move(point.x,point.y);await p.locator('#card-preview').waitFor({state:'visible'});const image=p.locator('#card-preview img.portrait');await image.waitFor({state:'visible'});assert.ok(await image.evaluate(n=>n.complete&&n.naturalWidth>0));assert.equal(await image.getAttribute('src'),row.src);const f=path.join(output,'preview-'+scenario+'-'+ref.replace(/[^a-z0-9]/gi,'_')+'.png');await p.screenshot({path:f});report.captures.push({name:'preview-'+ref,file:f});await p.mouse.move(3,3);await p.locator('#card-preview').waitFor({state:'hidden'});}
  return row;
}
async function place(p,c){
  await manaTen(p);const m=await state(p);assert.ok(m.actions.some(a=>a.type==='play_card'&&a.card===c.ref&&a.position!=null));await clickCard(p,c.ref);const index=own(m).board.length;return action(p,()=>p.locator(`.position-slot[data-owner="${m.seat}"][data-position="${index}"]`).click(),'play_card');
}
async function cycleSeat(p){
  const before=await state(p);await action(p,()=>p.locator('#end').click(),'end_turn');await p.locator('#switch').click();await p.locator('#curtain').waitFor({state:'visible'});await settled(p);await p.locator('#ready').click();await p.waitForFunction(seat=>{try{return JSON.parse(document.getElementById('dto').textContent).seat!==seat&&document.body.dataset.busy!=='true';}catch{return false;}},before.seat);return state(p);
}
async function locationStatus(p,ref,cooldown,label){
  const m=await state(p),c=m.observation.players.flatMap(v=>v.board).find(v=>v.ref===ref),n=card(p,ref);assert.ok(c?.location);assert.equal(c.location.cooldown_remaining,cooldown);assert.equal(await n.getAttribute('data-cooldown'),String(cooldown));
  const text=await n.locator('.location-status').textContent();if(label)assert.equal(text,label);assert.equal(await n.locator('.durability-orb').textContent(),String(c.durability));assert.equal(await n.locator('.attack-orb').count(),0);assert.equal(await n.locator('.card-type').textContent(),'地标');assert.equal(await n.evaluate(n=>n.classList.contains('can-act')),m.actions.some(a=>a.type==='use_location'&&a.location===ref));return {ref,durability:c.durability,cooldown,text};
}
async function layout(p,width,height,name){
  await p.setViewportSize({width,height});await p.mouse.move(3,3);await pause(160);const details=await p.evaluate(()=>{
    const rect=n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
    const overlap=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y));
    const textRect=n=>{const range=document.createRange();range.selectNodeContents(n);return rect({getBoundingClientRect:()=>range.getBoundingClientRect()});};
    return{viewport:{width:innerWidth,height:innerHeight},documentWidth:document.documentElement.scrollWidth,cards:[...document.querySelectorAll('.battle-row .card')].map(n=>{const labels=[...n.querySelectorAll('.taunt-badge,.location-status')].filter(v=>getComputedStyle(v).display!=='none');const orbs=[...n.querySelectorAll('.attack-orb,.health-orb')].filter(v=>getComputedStyle(v).display!=='none');return{ref:n.dataset.ref,kind:n.dataset.kind,rect:rect(n),labels:labels.map(l=>({class:l.className,text:l.textContent,rect:rect(l),textRect:textRect(l),lineHeight:parseFloat(getComputedStyle(l).lineHeight),whiteSpace:getComputedStyle(l).whiteSpace,statOverlap:orbs.map(o=>({stat:o.className,number:o.textContent,rect:rect(o),textRect:textRect(o),area:overlap(textRect(l),textRect(o))}))})),shield:n.classList.contains('taunt-guard')?rect(n.querySelector('.taunt-frame')):null};})};
  });report.geometry.push({name,...details});assert.ok(details.documentWidth<=width);for(const c of details.cards){assert.ok(c.rect.x>=0&&c.rect.right<=width&&c.rect.y>=0&&c.rect.bottom<=height,`Board card clipped ${c.ref}`);if(c.shield)assert.ok(c.shield.x>=0&&c.shield.right<=width&&c.shield.y>=0&&c.shield.bottom<=height);for(const l of c.labels){assert.ok(l.textRect.height<=l.lineHeight+1,`${l.text} wraps to multiple lines at ${width}px`);for(const s of l.statOverlap)assert.ok(s.area<=1,`${l.text} overlaps ${s.stat} value by ${s.area}`);}}
  await capture(p,name);check('full board location and taunt labels preserve numeric stats within viewport',{width,height,count:details.cards.length});
}

await fs.mkdir(output,{recursive:true});report.sourceBefore=await hashes();browser=await chromium.launch({headless:true});
try{
  const p=await newGame('locations-and-full-board');let m=await state(p);const senjin=own(m).board.find(c=>c.card_id==='CS2_179');assert.ok(senjin);
  const depths=await add(p,'CORE_REV_990'),starport=await add(p,'SC_403'),arkonite=await add(p,'GDB_100');
  for(const c of [depths,starport,arkonite]){await imageCheck(p,c.ref,true);if(c.kind==='location')assert.equal(await card(p,c.ref).locator('.location-status').count(),0);}
  check('new location and minion art loads in hand and hovered previews; hand locations have no cooldown warning',{ids:[depths.card_id,starport.card_id,arkonite.card_id]});
  m=await place(p,depths);await locationStatus(p,depths.ref,0,'可使用');assert.equal(own(m).board.find(c=>c.ref===senjin.ref).attack,senjin.attack);check('targeted location places without activating or requesting its use target');
  const beforeUse=m,initialDurability=own(m).board.find(c=>c.ref===depths.ref).durability;await clickCard(p,depths.ref);const legalTargets=m.actions.filter(a=>a.type==='use_location'&&a.location===depths.ref).map(a=>a.target).sort();assert.deepEqual((await p.locator('.valid-target').evaluateAll(ns=>ns.map(n=>n.dataset.ref))).sort(),legalTargets);
  m=await action(p,()=>card(p,senjin.ref).click(),'use_location');const changed=own(m).board.find(c=>c.ref===senjin.ref);assert.equal(changed.attack,senjin.attack+2);assert.equal(changed.health,senjin.health-1);assert.equal(own(m).mana,own(beforeUse).mana);assert.equal(own(m).board.find(c=>c.ref===depths.ref).durability,initialDurability-1);await locationStatus(p,depths.ref,2,'冷却 2');assert.ok(!m.actions.some(a=>a.type==='use_location'&&a.location===depths.ref));check('targeted location click settles damage, buff, durability and two-turn cooldown using normal actions');
  m=await place(p,starport);const beforeStar=m;await locationStatus(p,starport.ref,0,'可使用');m=await action(p,()=>clickCard(p,starport.ref),'use_location');const summoned=own(m).board.find(c=>!own(beforeStar).board.some(v=>v.ref===c.ref));assert.ok(summoned&&['SC_403a','SC_403b','SC_403c','SC_403d','SC_403f'].includes(summoned.card_id));assert.equal(own(m).mana,own(beforeStar).mana);await locationStatus(p,starport.ref,2,'冷却 2');await imageCheck(p,summoned.ref);check('untargeted starport activates immediately once and its real random summoned piece has loaded art',{piece:summoned.card_id});await capture(p,'locations-cooldown-two');
  m=await cycleSeat(p);await locationStatus(p,depths.ref,2,'冷却 2');m=await cycleSeat(p);await locationStatus(p,depths.ref,1,'冷却 1');await locationStatus(p,starport.ref,1,'冷却 1');check('opponent turn does not tick location cooldown; next own turn remains cooling');await capture(p,'locations-cooldown-one');
  m=await cycleSeat(p);m=await cycleSeat(p);await locationStatus(p,depths.ref,0,'可使用');await locationStatus(p,starport.ref,0,'可使用');check('second own turn restores location availability from actual legal commands');
  m=await place(p,arkonite);assert.ok(own(m).board.find(c=>c.ref===arkonite.ref).keywords.includes('taunt'));assert.ok(await card(p,arkonite.ref).evaluate(n=>n.classList.contains('taunt-guard')));check('newly summoned taunt minion has a visible shield even while unable to attack');
  for(let i=0;i<2;i++){const extra=await add(p,'CS2_179');m=await place(p,extra);}assert.equal(own(m).board.length,7);for(const c of own(m).board)await imageCheck(p,c.ref);
  await layout(p,1280,720,'full-board-1280x720');await layout(p,980,872,'full-board-980x872');await layout(p,669,884,'full-board-669x884');
  assert.ok(foe(m).hand.every(c=>c.card_id==null));assert.equal(await p.locator('.opponent-hand img').count(),0);assert.ok((await p.locator('.opponent-hand .card-back').evaluateAll(ns=>ns.map(n=>n.title))).every(t=>t==='对方手牌'));check('opponent hidden hand remains generic backs with no portrait DOM or identity');

  const q=await newGame('taunt-and-silence');m=await cycleSeat(q);const guard=foe(m).board.find(c=>c.keywords.includes('taunt')),attacker=own(m).board.find(c=>m.actions.some(a=>a.type==='attack'&&a.attacker===c.ref));assert.ok(guard&&attacker);const enemyHero=foe(m).hero.ref;
  assert.ok(await card(q,guard.ref).locator('.taunt-frame').isVisible());assert.equal(await card(q,guard.ref).locator('.taunt-badge').textContent(),'嘲讽');await clickCard(q,attacker.ref);assert.deepEqual(await q.locator('.valid-target').evaluateAll(ns=>ns.map(n=>n.dataset.ref)),[guard.ref]);assert.ok(!m.actions.some(a=>a.type==='attack'&&a.attacker===attacker.ref&&a.defender===enemyHero));check('shield identifies the actual sole taunt blocker and direct attack highlights exclude enemy hero');await capture(q,'taunt-attack-target');await q.locator('#cancel-selection').click();
  const silence=await add(q,'EX1_332');await imageCheck(q,silence.ref,true);await clickCard(q,silence.ref);m=await action(q,()=>card(q,guard.ref).click(),'play_card');const silent=foe(m).board.find(c=>c.ref===guard.ref);assert.equal(silent.silenced,true);assert.ok(!silent.keywords.includes('taunt'));assert.equal(await card(q,guard.ref).locator('.taunt-frame,.taunt-badge').count(),0);assert.equal(await card(q,guard.ref).evaluate(n=>n.classList.contains('taunt-guard')),false);check('normal silence removes current taunt keyword and its shield and badge');
  await clickCard(q,attacker.ref);const valid=(await q.locator('.valid-target').evaluateAll(ns=>ns.map(n=>n.dataset.ref))).sort(),legal=m.actions.filter(a=>a.type==='attack'&&a.attacker===attacker.ref).map(a=>a.defender).sort();assert.deepEqual(valid,legal);assert.ok(valid.includes(enemyHero));await capture(q,'silenced-face-target');const heroBefore=foe(m).hero.health;m=await action(q,()=>card(q,enemyHero).click(),'attack');assert.equal(foe(m).hero.health,heroBefore-attacker.attack);check('after silence actual legal highlights include hero and normal face attack settles');
  await Promise.all(pendingAudits);assert.deepEqual(report.privacyViolations,[]);assert.deepEqual(report.consoleErrors,[]);assert.deepEqual(report.pageErrors,[]);check('no browser errors or undisclosed opponent information');
  report.sourceAfter=await hashes();assert.deepEqual(report.sourceAfter,report.sourceBefore);check('product and test sources plus art mapping, manifest and exercised portraits retain identical bytes',{count:sources.length});report.passed=true;
}catch(e){report.passed=false;report.failure={scenario,message:redact(e.message),stack:redact(e.stack)};process.exitCode=1;console.error(report.failure.stack);if(currentPage){await currentPage.screenshot({path:path.join(output,'failure.png'),fullPage:true});await fs.writeFile(path.join(output,'failure-visible.json'),await currentPage.evaluate(()=>render_game_to_text()));}}
finally{await Promise.allSettled(pendingAudits);report.sourceAfter=await hashes();report.sourcesStable=JSON.stringify(report.sourceBefore)===JSON.stringify(report.sourceAfter);report.finished=new Date().toISOString();report.elapsedSeconds=(Date.parse(report.finished)-Date.parse(report.started))/1000;await fs.writeFile(path.join(output,'browser-regression.json'),JSON.stringify(report,null,2));await browser.close();console.log('Report: '+output);}
