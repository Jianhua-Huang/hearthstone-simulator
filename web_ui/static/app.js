'use strict';
const $=id=>document.getElementById(id);
const artwork={"BT_733": "BT_733.webp", "CS2_024": "CS2_024.webp", "CS2_029": "CS2_029.webp", "CS2_106": "CS2_106.webp", "CS2_117": "CS2_117.webp", "CS2_122": "CS2_122.webp", "CS2_179": "CS2_179.webp", "CS2_182": "CS2_182.webp", "CS2_188": "CS2_188.webp", "CS2_222": "CS2_222.webp", "EX1_010": "EX1_010.webp", "EX1_019": "EX1_019.webp", "EX1_096": "EX1_096.webp", "EX1_608": "EX1_608.webp", "FP1_007": "FP1_007.webp", "FP1_021": "FP1_021.webp", "GAME_005": "GAME_005.webp", "HERO_01": "HERO_01.webp", "HERO_01bp": "HERO_01bp.webp", "HERO_08": "HERO_08.webp", "HERO_08bp": "HERO_08bp.webp", "ULD_205": "ULD_205.webp", "ULD_208": "ULD_208.webp", "UNG_029": "UNG_029.webp"};
const types={play_card:'出牌',attack:'攻击',use_hero_power:'英雄技能',end_turn:'结束回合',concede:'认输',select_choice:'提交选择',use_hand_action:'手牌主动操作',use_location:'使用地标',use_minion_ability:'随从能力',launch_starship:'发射星舰',use_interactable:'交互物'};
const errors={invalid_action:'操作不合法，请按当前合法操作重新选择。',stale_observation:'局面已变化，旧操作已拒绝；请根据刷新后的局面重选。',unsupported_rule:'此来源的规则尚未支持玩家接口。',unsupported_target_domain:'此目标范围尚未支持玩家接口。',enumeration_limit:'选择组合超出枚举预算，请使用上方选择面板。',rule_error:'引擎无法枚举此局面的完整操作。',resolution_failed:'引擎结算失败，本次操作已回滚。',seat_session_required:'原对局会话已失效，请点击创建新局。',host_error:'本地服务处理失败，请查看服务与演示配置。',origin_rejected:'请使用 127.0.0.1 的本地页面。'};
let resetArmed=false, concedeArmed=false, selected=null;
let token=sessionStorage.getItem('hs-seat')||'', message=null, busy=false;
function notice(s){$('error').textContent=s||'';}
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function button(text,fn){const n=node('button',text);n.onclick=fn;return n;}
function clearView(){selected=null;message=null;resetArmed=false;concedeArmed=false;for(const id of ['players','logs','actions','choice','source','type'])$(id).replaceChildren();$('dto').textContent='';$('game').hidden=true;$('curtain').hidden=true;$('welcome').hidden=false;}
async function api(path,body={}){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){if(data.error==='seat_session_required'){token='';sessionStorage.removeItem('hs-seat');clearView();throw new Error('原对局会话已失效。点击「创建 / 重置对局」即可开始新局，无需重启服务。');}throw new Error(errors[data.error]||data.error);}return data;}
function saveToken(t){token=t;sessionStorage.setItem('hs-seat',t);}
async function work(fn){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{notice('');await fn();}catch(e){notice(e.message);}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);if(message&&!message.handoff)updateEnd();}}
function name(c){return c?message.names?.[c.card_id]||c.card_id||'未知牌背':'无';}
function entities(){const map={};for(const p of message.observation.players)for(const c of [p.hero,p.hero_power,p.weapon,...p.additional_hero_powers,...p.board,...p.hand,...p.quests,...p.secrets])if(c)map[c.ref]=c;return map;}
function source(a){return a.card||a.attacker||a.power||a.location||a.minion||a.starship||a.object||'';}
function ref(r){if(!r)return '无';const c=entities()[r];return c?`${name(c)} (${r})`:r;}
function actionLabel(a){let s=types[a.type]||a.type;if(source(a))s+=' · '+ref(source(a));if(a.target)s+=' → '+ref(a.target);if(a.defender)s+=' → '+ref(a.defender);if(a.position!=null)s+=` · 第${a.position+1}个位置`;if(a.side)s+=' · '+(a.side==='enemy'?'对方战场':'己方战场');if(a.branch)s+=' · 分支 '+a.branch;if(a.action_id||a.ability_id)s+=' · '+(a.action_id||a.ability_id);if(a.magnetic_target)s+=' · 磁力 '+ref(a.magnetic_target);if(a.body_targets||a.body_route)s+=' · '+JSON.stringify(a.body_targets||a.body_route);return s;}
async function submit(a){await work(async()=>{if(a.type==='concede'&&!concedeArmed){concedeArmed=true;notice('再次点击认输将结束当前座位的对局。');return;}concedeArmed=false;const data=await api('action',{revision:message.revision,action:a});render(data);if(!data.accepted)notice(errors[data.command_error]||data.command_error);});}
function card(c){
    const n=node('button',null,'card');n.dataset.ref=c.ref;n.dataset.kind=c.kind||'unknown';n.dataset.zone=c.zone||'';
    n.setAttribute('aria-label',name(c)+' '+c.ref);n.title=name(c)+(c.keywords?.length?' · '+c.keywords.join(' / '):'');
    if(artwork[c.card_id]){const img=node('img');img.src='/assets/'+artwork[c.card_id];img.alt='';img.className='portrait';img.draggable=false;n.append(img);}
    n.append(node('strong',name(c),'card-name'));
    if(c.cost)n.append(node('span',String(c.cost.amount),'cost-orb'));
    if(c.attack!=null&&['hero','minion'].includes(c.kind)){if(c.attack>0||c.kind==='minion')n.append(node('span',String(c.attack),'attack-orb'));n.append(node('span',String(c.health),'health-orb'));}
    if(c.armor)n.append(node('span',String(c.armor),'armor-orb'));
    if(c.durability)n.append(node('span',String(c.durability),'health-orb'));
    const flags=[...(c.keywords||[]),c.frozen?'冻结':'',c.silenced?'沉默':'',c.dormancy?'休眠 '+c.dormancy.remaining_turns:'',c.location?`冷却 ${c.location.cooldown_remaining}`:''].filter(Boolean);
    if(flags.length)n.append(node('small',flags.join(' · '),'card-flags'));
    n.onclick=()=>clickEntity(c.ref);
    const d=node('details',null,'entity-detail');d.append(node('summary','详情'),node('pre',JSON.stringify(c,null,2)));
    const wrap=node('div',null,'entity-wrap');wrap.append(n,d);return wrap;
}
function zone(label,cards,owner=null){const wrap=node('div',null,'card-zone'+(label.startsWith('英雄')?' hero-zone':label.startsWith('战场')?' board-zone':''));wrap.append(node('div',label,'hint'));const row=node('div',null,'zone');cards.filter(Boolean).forEach((c,i)=>{if(owner!==null)row.append(positionButton(owner,i));row.append(card(c));});if(owner!==null)row.append(positionButton(owner,cards.filter(Boolean).length));if(!row.children.length)row.append(node('span','空','hint'));wrap.append(row);return wrap;}
function player(p){
    const own=p.id===message.seat;
    const section=node('section',null,'player '+(own?'friendly':'enemy')+(p.id===message.observation.active_player?' active':''));
    const info=node('div',null,'player-info');info.append(node('span',`玩家${p.id} · ${own?'你的回合座位':'对手'} · 牌库 ${p.deck_count} / 手牌 ${p.hand.length}`));
    const mana=node('div',null,'mana-display');mana.append(node('strong',`${p.mana}/${p.max_mana}`));
    for(let i=0;i<Math.min(p.max_mana,10);i++)mana.append(node('span','◆',i<p.mana?'mana-crystal':'mana-crystal spent'));
    if(p.overload_locked||p.overload_owed)mana.append(node('small',`过载 ${p.overload_locked} / ${p.overload_owed}`));
    if(Object.values(p.resources).some(Boolean))mana.append(node('small',JSON.stringify(p.resources)));
    info.append(mana);section.append(info);
    const heroRow=node('div',null,'hero-row');const weapon=node('div',null,'weapon-slot');if(p.weapon)weapon.append(card(p.weapon));
    const hero=node('div',null,'hero-slot');hero.append(card(p.hero));
    const powers=node('div',null,'powers-slot');for(const c of [p.hero_power,...p.additional_hero_powers].filter(Boolean))powers.append(card(c));heroRow.append(weapon,hero,powers);
    const board=zone('',p.board,p.id);board.classList.add('battle-row');
    if(own){section.append(board,heroRow);const hand=zone('你的手牌 · 点击出牌',p.hand);hand.classList.add('hand');section.append(hand);}
    else{const backs=node('div',null,'opponent-hand');for(const c of p.hand){const b=node('div',null,'card-back');b.title=c.card_id?name(c):'对方手牌';if(c.card_id)b.append(node('small',name(c)));backs.append(b);}section.append(backs,heroRow,board);}
    if(p.secrets.length||p.quests.length)section.append(zone('奥秘 / 任务',[...p.secrets,...p.quests]));
    if(p.pending_plays.length)section.append(zone('结算中的出牌',p.pending_plays));
    return section;
}
function renderActions(){const actions=(message.actions||[]).filter(a=>a.type!=='select_choice'&&(!$('type').value||a.type===$('type').value)&&(!$('source').value||source(a)===$('source').value));$('actions').replaceChildren(...actions.map(a=>button(actionLabel(a),()=>submit(a))));if(!actions.length)$('actions').append(node('p','当前筛选没有合法操作。','hint'));}
function updateEnd(){$('end').disabled=!(message.actions||[]).some(a=>a.type==='end_turn');}
function render(data){selected=null;message=data;$('welcome').hidden=true;$('curtain').hidden=!data.handoff;$('game').hidden=!!data.handoff;if(data.handoff){$('handoff-title').textContent=`请玩家${data.seat}接手`;return;}const o=data.observation;$('status').textContent=`第 ${o.turn} 回合 · 行动方 玩家${o.active_player} · 当前座位 玩家${data.seat} · ${o.status==='playing'?(o.opening_stage==='complete'?'对战中':o.opening_stage||'对战中'):o.winner?'玩家'+o.winner+'获胜':'对局结束 / 平局'}`;$('players').replaceChildren(...[...o.players].sort((a,b)=>(a.id===data.seat)-(b.id===data.seat)).map(player));$('type').replaceChildren(new Option('所有操作',''),...Object.keys(types).map(t=>new Option(types[t],t)));const map=entities();$('source').replaceChildren(new Option('所有来源',''),...Object.keys(map).map(r=>new Option(ref(r),r)));$('action-count').textContent=`(${data.actions?.length??'未完整枚举'})`;$('fallback').hidden=!data.error;renderActions();renderChoice();paintSelection();$('logs').replaceChildren(...data.events.map(e=>node('p',`${e.sequence} · ${e.kind}${e.player_id?' · 玩家'+e.player_id:''}${e.source?' · '+name(e.source):''}${e.target?' → '+name(e.target):''}${e.amount!=null?' · '+e.amount:''}`)));$('logs').scrollTop=$('logs').scrollHeight;$('dto').textContent=JSON.stringify(data,null,2);if(data.error)notice(errors[data.error]||data.error);updateEnd();}
function renderChoice(){const c=message.observation.pending_choice;$('choice').hidden=!c;$('choice').replaceChildren();if(!c)return;if(!c.options){$('choice').append(node('h2',`等待玩家${c.player_id}选择，请交接座位。`));return;}$('choice').append(node('h2',c.purpose==='mulligan'?'换牌：勾选要换掉的手牌':c.prompt),node('p',`选择 ${c.min_count}–${c.max_count} 项。${c.purpose==='mulligan'?'未勾选的手牌会保留。':''}`));for(const o of c.options){const label=node('label',null,'choice-option');const input=node('input');input.type='checkbox';input.value=o.ref;label.append(input,document.createTextNode(' '+o.label+(o.card_id?' · '+name(o):'')));if(o.preview)label.append(node('pre',JSON.stringify(o.preview,null,2)));$('choice').append(label);}$('choice').append(button('确认选择',()=>{const options=[...$('choice').querySelectorAll('input:checked')].map(n=>n.value);if(options.length<c.min_count||options.length>c.max_count)return notice(`请选择 ${c.min_count}–${c.max_count} 项。`);submit({type:'select_choice',choice:c.ref,options});}));}
$('create').onclick=()=>work(async()=>{if(message&&!resetArmed){resetArmed=true;notice('再次点击创建 / 重置对局将重新开局。');return;}resetArmed=false;const d=await api('create',{preset:$('preset').value});saveToken(d.token);render(await api('view'));});
$('refresh').onclick=()=>work(async()=>render(await api('view')));
$('switch').onclick=()=>work(async()=>{const d=await api('handoff');saveToken(d.token);selected=null;message=null;$('players').replaceChildren();$('logs').replaceChildren();$('dto').textContent='';$('actions').replaceChildren();$('choice').replaceChildren();$('source').replaceChildren();$('type').replaceChildren();$('interaction-hint').textContent='等待接手';$('interaction-options').replaceChildren();render(d);});
$('ready').onclick=()=>work(async()=>render(await api('ready')));
$('end').onclick=()=>submit({type:'end_turn'});$('fallback').onclick=$('end').onclick;
$('source').onchange=renderActions;$('type').onchange=renderActions;
if(token)work(async()=>render(await api('view')));



// Direct interaction projects exact engine actions; it never calculates legality.
function targetOf(a){return a.type==='attack'?a.defender:a.target;}
function simple(a){return !a.body_targets&&!a.body_route;}
function modeKey(a){return JSON.stringify([a.type,a.branch||null,a.action_id||null,a.ability_id||null,a.side||'friendly']);}
function currentActions(){return selected?selected.actions:[];}
function chooseMode(actions){selected={actions};paintSelection();}
function clickEntity(r){
    if(busy||!message||message.handoff)return;
    if(selected&&!selected.groups){
        const matches=currentActions().filter(a=>targetOf(a)===r);
        if(matches.length){advance(matches);return;}
    }
    const available=(message.actions||[]).filter(a=>source(a)===r&&simple(a));
    if(!available.length){notice(selected?'这不是当前操作的合法目标。请点击高亮目标，或取消选择。':'当前实体没有可用操作（可能费用不足、尚不能攻击或正在等待选择）。');return;}
    notice('');
    const groups=new Map();for(const a of available){const k=modeKey(a);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(a);}
    selected={actions:available,groups:groups.size>1?[...groups.values()]:null};paintSelection();
}
function advance(actions){
    // Never guess a target, position or branch. Unique complete action is exact.
    if(actions.length===1){submit(actions[0]);return;}
    selected={actions};paintSelection();
}
function positionButton(owner,index){
    const b=button('+',()=>{
        const actions=currentActions().filter(a=>a.position===index&&(a.side==='enemy'?3-message.seat:message.seat)===owner);
        if(actions.length)advance(actions);
    });b.className='position-slot';b.dataset.owner=owner;b.dataset.position=index;
    b.setAttribute('aria-label',`在玩家${owner}战场第${index+1}个位置出牌`);b.hidden=true;return b;
}
function paintSelection(){
    const actions=currentActions();const choosingMode=!!selected?.groups;
    $('interaction-options').replaceChildren();$('cancel-selection').hidden=!selected;
    const positions=!choosingMode&&actions.some(a=>a.position!=null)&&new Set(actions.map(a=>JSON.stringify([a.position,a.side||'friendly']))).size>1;
    const targets=!choosingMode&&!positions?new Set(actions.map(targetOf).filter(Boolean)):new Set();
    for(const n of document.querySelectorAll('.card[data-ref]')){
        const r=n.dataset.ref;
        n.classList.toggle('selected-source',!!selected&&actions.some(a=>source(a)===r));
        n.classList.toggle('valid-target',targets.has(r));
        n.classList.toggle('can-act',!selected&&(message.actions||[]).some(a=>source(a)===r&&simple(a)));
        n.setAttribute('aria-pressed',String(!!selected&&actions.some(a=>source(a)===r)));
    }
    for(const b of document.querySelectorAll('.position-slot')){
        b.hidden=!positions||!actions.some(a=>a.position===Number(b.dataset.position)&&(a.side==='enemy'?3-message.seat:message.seat)===Number(b.dataset.owner));
    }
    if(!selected){$('interaction-hint').textContent=message.observation.pending_choice?'请在选择面板完成当前选择。':'点击亮起的手牌出牌，或点击己方随从 / 英雄发起攻击。';return;}
    const first=actions[0];const label=name(entities()[source(first)]);
    if(choosingMode){
        $('interaction-hint').textContent=`已选 ${label}，请选择操作 / 分支。`;
        for(const group of selected.groups){const a=group[0];$('interaction-options').append(button((types[a.type]||a.type)+(a.branch?' · '+a.branch:'')+(a.action_id?' · '+a.action_id:'')+(a.ability_id?' · '+a.ability_id:'')+(a.side?' · '+(a.side==='enemy'?'对方战场':'己方战场'):''),()=>chooseMode(group)));}
    }else if(positions){document.querySelector('.position-slot:not([hidden])')?.scrollIntoView({block:'nearest'});$('interaction-hint').textContent=`已选 ${label}，点击战场上的「+」选择入场位置。`;}
    else if(targets.size){document.querySelector('.valid-target')?.scrollIntoView({block:'nearest'});$('interaction-hint').textContent=`已选 ${label}，点击绿色高亮目标${first.type==='attack'?'进行攻击':'施放'}。`;
        // A nullable target is a distinct engine choice, not an automatic default.
        const untargeted=actions.filter(a=>!targetOf(a));if(untargeted.length)$('interaction-options').append(button('不选择目标',()=>advance(untargeted)));
    }else if(actions.length===1){$('interaction-hint').textContent=`已选 ${label}，点击确认执行。`;$('interaction-options').append(button('确认'+(types[first.type]||'操作'),()=>submit(first)));}
    else{$('interaction-hint').textContent='该操作有额外参数，请选择具体方案。';for(const a of actions)$('interaction-options').append(button(actionLabel(a),()=>submit(a)));}
}
$('cancel-selection').onclick=()=>{selected=null;notice('');paintSelection();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&message&&!message.handoff){selected=null;paintSelection();}});
