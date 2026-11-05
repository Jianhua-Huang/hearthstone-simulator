// UI checks for any isolated duel_audit_ui server; no hidden state sent to browser.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
const args=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,l)=>{if(v.startsWith('--'))a.push([v.slice(2),l[i+1]]);return a;},[]));
const output=path.resolve(args.output),server=JSON.parse(fs.readFileSync(args.server,'utf8'));
const expectedViews=JSON.parse(fs.readFileSync(args.views,'utf8')).views;
if(fs.existsSync(output))throw Error('Use a new output directory');fs.mkdirSync(output,{recursive:true});
const library=path.join(process.env.CODEX_HOME||path.join(os.homedir(),'.codex'),'skills/develop-web-game/node_modules/playwright/index.mjs');
const {chromium}=await import(pathToFileURL(library).href),browser=await chromium.launch({headless:true});
const checks=[],errors=[],bad=[];const assert=(v,m)=>{if(!v)throw Error(m);};
const state=page=>page.evaluate(()=>JSON.parse(window.render_game_to_text()));
const settle=page=>page.waitForFunction(()=>document.body.dataset.busy==='false'&&JSON.parse(window.render_game_to_text()).mode==='battle',{},{timeout:90000});
async function open(preset,opponent){
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();page.setDefaultTimeout(60000);
 page.on('pageerror',e=>errors.push({preset,error:String(e)}));page.on('console',m=>{if(m.type()==='error')errors.push({preset,error:m.text()});});
 page.on('response',r=>{if(r.status()>=400)bad.push({preset,path:new URL(r.url()).pathname,status:r.status()});});
 await page.goto(server.url,{waitUntil:'networkidle'});await page.locator('#preset').selectOption(preset);
 await page.locator('#opponent-mode').selectOption(opponent);await page.locator('#create').click();await settle(page);
 return{context,page};
}
async function capture(page,name){
 await page.evaluate(()=>window.advanceTime());await page.waitForTimeout(150);
 await page.evaluate(async()=>{
  const urls=new Set();
  for(const node of document.querySelectorAll('body *'))if(node.getBoundingClientRect().width&&node.getBoundingClientRect().height){
   for(const match of getComputedStyle(node).backgroundImage.matchAll(/url\(["']?([^"')]+)["']?\)/g))urls.add(match[1]);
  }
  await Promise.all([...urls].map(src=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>image.decode().then(resolve,reject);image.onerror=()=>reject(Error('Image unavailable: '+src));image.src=src;})));
  await Promise.all([...document.images].filter(img=>img.getBoundingClientRect().width&&img.getBoundingClientRect().height).map(img=>img.decode()));
 });
 const value=await state(page);assert(!value.error,'UI error: '+value.error);assert(!value.opponent?.error,'AI error');
 const other=value.players.find(p=>p.id!==value.seat);
 assert(other.hand.every(c=>c.hidden||['幸运币','The Coin'].includes(c.name)),'Opponent hand identity leaked');
 const visuals=await page.evaluate(()=>{
  const s=JSON.parse(window.render_game_to_text()),issues=[],cards=[];
  for(const p of s.players)for(const c of[p.hero,p.hero_power,...p.board,...(p.id===s.seat?p.hand:[])].filter(c=>c?.ref)){
   const node=document.querySelector('#players .card[data-ref="'+CSS.escape(c.ref)+'"]');if(!node){issues.push(c.name+': missing DOM');continue;}
   const portrait=node.querySelector('.portrait');cards.push({name:c.name,kind:c.kind,portrait:portrait?.src||null,natural_width:portrait?.naturalWidth||0});
   if(c.kind==='minion'&&c.keywords?.includes('taunt')&&!node.querySelector('.taunt-badge'))issues.push(c.name+': missing taunt UI');
   const health=['hero','minion'].includes(c.kind)?c.health:null;
   for(const [selector,value]of[['.health-orb',health],['.durability-orb',c.durability]])if(value!=null&&node.querySelector(selector)&&node.querySelector(selector).textContent!==String(value))issues.push(c.name+': wrong '+selector);
  }return{issues,cards,overflow:document.documentElement.scrollWidth>innerWidth+2};
 });assert(!visuals.issues.length,JSON.stringify(visuals));assert(!visuals.overflow,'Horizontal overflow');
 await page.screenshot({path:path.join(output,name+'.png')});fs.writeFileSync(path.join(output,name+'.json'),JSON.stringify(value,null,2));fs.writeFileSync(path.join(output,name+'-visual.json'),JSON.stringify(visuals,null,2));
 return{value,visuals};
}
function expectedAfter(value,preset){
 const s=expectedViews[preset].observation;
 assert(value.turn===s.turn&&value.active_player===s.active_player&&value.status===s.status,'Wrong after turn/status');
 for(const player of value.players){
  const p=s.players.find(p=>p.id===player.id),hero=p.hero;
  assert(player.mana===p.mana&&player.max_mana===p.max_mana,'Mana does not match native after');
  assert(player.hero.health===hero.health&&player.hero.armor===hero.armor,'Hero health/armor does not match native after');
  assert(player.board.length===p.board.length&&player.hand.length===p.hand.length&&player.deck_count===p.deck_count,'Zone count mismatch');
  for(let i=0;i<p.board.length;i++){
   const card=player.board[i],e=p.board[i];
   if(typeof card.health==='number')assert(card.health===e.health,'Wrong board health');
   if(typeof card.attack==='number')assert(card.attack===e.attack,'Wrong board attack');
  }
 }
 assert((value.pending_choice?.purpose||null)===(s.pending_choice?.purpose||null),'Wrong after choice');
}
try{
 for(const preset of Object.keys(server.presets).filter(k=>k.startsWith('pair-')&&(!args.pairs||args.pairs.split(',').includes(k)))){
  const {context,page}=await open(preset,'ai');assert((await state(page)).pending_choice?.purpose==='mulligan','Missing opening');
  await page.locator('#choice [data-choice-confirm]').click();await page.waitForFunction(()=>document.body.dataset.busy==='false'&&!JSON.parse(window.render_game_to_text()).pending_choice);
  await page.locator('#mana-ten').click();await settle(page);let current=await state(page);assert(current.players.find(p=>p.id===current.seat).mana===10,'10 mana setting failed');
  await page.locator('#end').click();await page.waitForFunction(()=>{const s=JSON.parse(window.render_game_to_text());return document.body.dataset.busy==='false'&&s.turn>=2&&s.active_player===s.seat&&!s.opponent?.can_step;},{},{timeout:90000});
  const wide=await capture(page,preset+'-1440');await page.setViewportSize({width:950,height:1000});await capture(page,preset+'-950');
  checks.push({preset,opening:true,both_mulligans_completed:true,mana10:true,ai_turn_completed:true,turn:wide.value.turn});await context.close();
 }
 for(const [preset,entry]of Object.entries(server.fixtures)){
  const fixture=JSON.parse(fs.readFileSync(entry.fixture,'utf8')),{context,page}=await open(preset,'human');
  const before=await capture(page,preset+'-before');
  const expectedTurn=expectedViews[preset].before_observation?.turn??fixture.scene?.turn;
  assert(before.value.seat===fixture.actor&&before.value.turn===expectedTurn,'Fixture seat/turn mismatch');
  const a=fixture.action;
  if(a.type==='play_card'){
   await page.locator('#players .card[data-ref="'+a.card+'"]').click();
   if(a.position!=null){
    const owner=a.side==='enemy'?3-before.value.seat:before.value.seat;
    await page.locator('#players .position-slot[data-owner="'+owner+'"][data-position="'+a.position+'"]:visible').click();
   }
   if(a.target)await page.locator('#players .card[data-ref="'+a.target+'"]:visible').click();
  }
  else if(a.type==='select_choice'){
   if(before.value.pending_choice?.purpose==='assemble'){
    await page.locator('#choice [data-assemble-half][data-choice-ref="'+a.options[0]+'"]').click();
    await page.locator('#choice [data-assemble-confirm]').click();
   }else await page.locator('#choice [data-choice-ref="'+a.options[0]+'"]').click();
  }else if(a.type==='end_turn')await page.locator('#end').click();else throw Error('Unhandled fixture gesture '+a.type);
  await settle(page);await page.waitForTimeout(150);const after=await capture(page,preset+'-after');expectedAfter(after.value,preset);
  checks.push({preset,seat:fixture.actor,real_action:a.type,native_after_visible_state_equal:true});await context.close();
 }
 assert(!errors.length&&!bad.length,JSON.stringify({errors,bad}));
 fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({success:true,checks,errors,bad},null,2));console.log(JSON.stringify({success:true,checks}));
}catch(e){fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({success:false,error:String(e),checks,errors,bad},null,2));throw e;}
finally{await browser.close();}
