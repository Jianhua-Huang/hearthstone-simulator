'use strict';
const $=id=>document.getElementById(id);
const artwork={"AT_011":"AT_011.webp","AT_066":"AT_066.webp","AT_082":"AT_082.webp","AT_124":"AT_124.webp","AV_121":"AV_121.webp","AV_143":"AV_143.webp","AV_344":"AV_344.webp","AV_400":"AV_400.webp","BAR_021":"BAR_021.webp","BAR_024":"BAR_024.webp","BAR_025":"BAR_025.webp","BAR_078":"BAR_078.webp","BAR_306":"BAR_306.webp","BOT_035":"BOT_035.webp","BOT_107":"BOT_107.webp","BOT_251":"BOT_251.webp","BOT_411":"BOT_411.webp","BOT_548":"BOT_548.webp","BOT_563":"BOT_563.webp","BOT_911":"BOT_911.webp","BRM_004":"BRM_004.webp","BT_004":"BT_004.webp","BT_156":"BT_156.webp","BT_480":"BT_480.webp","BT_490":"BT_490.webp","BT_491":"BT_491.webp","BT_733":"BT_733.webp","BT_737":"BT_737.webp","CATA_150":"CATA_150.webp","CATA_150t":"CATA_150t.webp","CATA_150t1":"CATA_150t1.webp","CATA_151":"CATA_151.webp","CATA_151t":"CATA_151t.webp","CATA_151t1":"CATA_151t1.webp","CATA_153":"CATA_153.webp","CATA_153t":"CATA_153t.webp","CATA_153t1":"CATA_153t1.webp","CATA_154":"CATA_154.webp","CATA_154t":"CATA_154t.webp","CATA_154t1":"CATA_154t1.webp","CATA_155":"CATA_155.webp","CATA_155t":"CATA_155t.webp","CATA_155t1":"CATA_155t1.webp","CATA_158":"CATA_158.webp","CATA_158t":"CATA_158t.webp","CATA_160":"CATA_160.webp","CATA_190h":"CATA_190h.webp","CATA_190p":"CATA_190p.webp","CATA_190t10":"CATA_190t10.webp","CATA_190t11":"CATA_190t11.webp","CATA_190t12":"CATA_190t12.webp","CATA_190t13":"CATA_190t13.webp","CATA_190t14":"CATA_190t14.webp","CATA_472":"CATA_472.webp","CATA_480":"CATA_480.webp","CATA_497":"CATA_497.webp","CATA_525":"CATA_525.webp","CATA_525t":"CATA_525t.webp","CATA_530":"CATA_530.webp","CATA_565":"CATA_565.webp","CATA_565t":"CATA_565t.webp","CATA_580":"CATA_580.webp","CATA_580t":"CATA_580t.webp","CATA_722":"CATA_722.webp","CATA_725":"CATA_725.webp","CATA_725t":"CATA_725t.webp","CATA_726":"CATA_726.webp","CATA_726t":"CATA_726t.webp","CATA_726t1":"CATA_726t1.webp","CATA_780":"CATA_780.webp","CATA_780t":"CATA_780t.webp","CORE_REV_990":"CORE_REV_990.webp","CS1_112":"CS1_112.webp","CS1_129":"CS1_129.webp","CS2_007":"CS2_007.webp","CS2_009":"CS2_009.webp","CS2_024":"CS2_024.webp","CS2_028":"CS2_028.webp","CS2_029":"CS2_029.webp","CS2_032":"CS2_032.webp","CS2_082":"CS2_082.webp","CS2_101t":"CS2_101t.webp","CS2_106":"CS2_106.webp","CS2_117":"CS2_117.webp","CS2_118":"CS2_118.webp","CS2_122":"CS2_122.webp","CS2_125":"CS2_125.webp","CS2_127":"CS2_127.webp","CS2_179":"CS2_179.webp","CS2_182":"CS2_182.webp","CS2_188":"CS2_188.webp","CS2_203":"CS2_203.webp","CS2_222":"CS2_222.webp","CS2_236":"CS2_236.webp","DED_509":"DED_509.webp","DEEP_015":"DEEP_015.webp","DEEP_020":"DEEP_020.webp","DEEP_999t4":"DEEP_999t4.webp","DEEP_999t5":"DEEP_999t5.webp","DMF_073":"DMF_073.webp","DMF_073t":"DMF_073t.webp","DMF_124":"DMF_124.webp","DMF_124t":"DMF_124t.webp","DMF_248":"DMF_248.webp","DMF_248t":"DMF_248t.webp","DRG_008":"DRG_008.webp","EDR_105":"EDR_105.webp","EDR_445p":"EDR_445p.webp","EDR_445pt3":"EDR_445pt3.webp","EDR_448p":"EDR_448p.webp","EDR_449p":"EDR_449p.webp","EDR_451":"EDR_451.webp","EDR_464":"EDR_464.webp","EDR_519":"EDR_519.webp","EDR_847p":"EDR_847p.webp","EDR_847pt2":"EDR_847pt2.webp","EDR_850p":"EDR_850p.webp","EDR_851p":"EDR_851p.webp","EDR_851t":"EDR_851t.webp","EDR_852":"EDR_852.webp","END_000p":"END_000p.webp","END_003p":"END_003p.webp","END_036":"END_036.webp","ETC_325":"ETC_325.webp","EX1_010":"EX1_010.webp","EX1_012":"EX1_012.webp","EX1_019":"EX1_019.webp","EX1_059":"EX1_059.webp","EX1_096":"EX1_096.webp","EX1_124":"EX1_124.webp","EX1_130":"EX1_130.webp","EX1_130a":"EX1_130a.webp","EX1_131":"EX1_131.webp","EX1_131t":"EX1_131t.webp","EX1_134":"EX1_134.webp","EX1_145":"EX1_145.webp","EX1_154":"EX1_154.webp","EX1_158":"EX1_158.webp","EX1_158t":"EX1_158t.webp","EX1_164":"EX1_164.webp","EX1_169":"EX1_169.webp","EX1_178":"EX1_178.webp","EX1_238":"EX1_238.webp","EX1_279":"EX1_279.webp","EX1_287":"EX1_287.webp","EX1_289":"EX1_289.webp","EX1_294":"EX1_294.webp","EX1_308":"EX1_308.webp","EX1_332":"EX1_332.webp","EX1_350":"EX1_350.webp","EX1_563":"EX1_563.webp","EX1_581":"EX1_581.webp","EX1_591":"EX1_591.webp","EX1_608":"EX1_608.webp","EX1_610":"EX1_610.webp","EX1_611":"EX1_611.webp","EX1_613":"EX1_613.webp","FIR_900":"FIR_900.webp","FP1_007":"FP1_007.webp","FP1_007t":"FP1_007t.webp","FP1_017":"FP1_017.webp","FP1_021":"FP1_021.webp","FP1_031":"FP1_031.webp","GAME_005":"GAME_005.webp","GDB_100":"GDB_100.webp","GDB_100a":"GDB_100a.webp","GDB_100b":"GDB_100b.webp","GDB_100c":"GDB_100c.webp","GDB_100t2":"GDB_100t2.webp","GDB_100t4":"GDB_100t4.webp","GDB_100t5":"GDB_100t5.webp","GDB_100t6":"GDB_100t6.webp","GDB_100t7":"GDB_100t7.webp","GDB_100t8":"GDB_100t8.webp","GDB_100t9":"GDB_100t9.webp","GDB_101":"GDB_101.webp","GDB_109":"GDB_109.webp","GDB_111":"GDB_111.webp","GDB_120":"GDB_120.webp","GDB_466":"GDB_466.webp","GDB_873":"GDB_873.webp","GIL_820":"GIL_820.webp","HERO_01":"HERO_01.webp","HERO_01bp":"HERO_01bp.webp","HERO_02":"HERO_02.webp","HERO_03":"HERO_03.webp","HERO_03bp":"HERO_03bp.webp","HERO_04":"HERO_04.webp","HERO_04bp":"HERO_04bp.webp","HERO_05":"HERO_05.webp","HERO_06":"HERO_06.webp","HERO_06bp":"HERO_06bp.webp","HERO_08":"HERO_08.webp","HERO_08bp":"HERO_08bp.webp","HERO_09":"HERO_09.webp","HERO_11":"HERO_11.webp","ICC_091":"ICC_091.webp","ICC_820":"ICC_820.webp","ICC_901":"ICC_901.webp","JAIL_123":"JAIL_123.webp","JAM_005":"JAM_005.webp","JAM_017":"JAM_017.webp","LOE_029":"LOE_029.webp","LOE_077":"LOE_077.webp","LOE_119":"LOE_119.webp","LOOT_517":"LOOT_517.webp","MAW_006":"MAW_006.webp","NEW1_023":"NEW1_023.webp","OG_044":"OG_044.webp","OG_141":"OG_141.webp","REV_019":"REV_019.webp","REV_019t":"REV_019t.webp","REV_601":"REV_601.webp","REV_601t":"REV_601t.webp","REV_956":"REV_956.webp","REV_956t":"REV_956t.webp","REV_957":"REV_957.webp","REV_957t":"REV_957t.webp","RLK_051":"RLK_051.webp","RLK_518":"RLK_518.webp","RLK_541":"RLK_541.webp","RLK_843":"RLK_843.webp","RLK_912":"RLK_912.webp","SCH_182":"SCH_182.webp","SCH_231":"SCH_231.webp","SCH_242":"SCH_242.webp","SCH_248":"SCH_248.webp","SC_400":"SC_400.webp","SC_400p":"SC_400p.webp","SC_401":"SC_401.webp","SC_403":"SC_403.webp","SC_403a":"SC_403a.webp","SC_403b":"SC_403b.webp","SC_403c":"SC_403c.webp","SC_403d":"SC_403d.webp","SC_403f":"SC_403f.webp","SC_403t":"SC_403t.webp","SC_404":"SC_404.webp","SC_405":"SC_405.webp","SC_406":"SC_406.webp","SC_407":"SC_407.webp","SC_409":"SC_409.webp","SC_410":"SC_410.webp","SC_411":"SC_411.webp","SC_999t":"SC_999t.webp","SW_094":"SW_094.webp","SW_115":"SW_115.webp","SW_428":"SW_428.webp","SW_428t":"SW_428t.webp","SW_428t2":"SW_428t2.webp","SW_428t4":"SW_428t4.webp","SW_450t4":"SW_450t4.webp","TID_003":"TID_003.webp","TID_099":"TID_099.webp","TID_700":"TID_700.webp","TID_703":"TID_703.webp","TID_710":"TID_710.webp","TID_711":"TID_711.webp","TID_711t":"TID_711t.webp","TID_711t2":"TID_711t2.webp","TID_711t3":"TID_711t3.webp","TID_711t4":"TID_711t4.webp","TID_711t5":"TID_711t5.webp","TID_711t6":"TID_711t6.webp","TIME_000":"TIME_000.webp","TIME_064":"TIME_064.webp","TIME_EVENT_999":"TIME_EVENT_999.webp","TOY_528":"TOY_528.webp","TRL_092":"TRL_092.webp","TRL_506":"TRL_506.webp","TSC_032":"TSC_032.webp","TSC_032t":"TSC_032t.webp","TSC_032t2":"TSC_032t2.webp","TSC_071":"TSC_071.webp","TSC_216":"TSC_216.webp","TSC_216t":"TSC_216t.webp","TSC_639":"TSC_639.webp","TSC_639t":"TSC_639t.webp","TSC_639t2":"TSC_639t2.webp","TSC_639t3":"TSC_639t3.webp","TSC_647":"TSC_647.webp","TTN_042":"TTN_042.webp","TTN_042t":"TTN_042t.webp","TTN_087":"TTN_087.webp","TTN_724":"TTN_724.webp","TTN_724t":"TTN_724t.webp","TTN_903":"TTN_903.webp","TTN_903t":"TTN_903t.webp","TTN_903t2":"TTN_903t2.webp","TTN_903t3":"TTN_903t3.webp","TTN_903t4":"TTN_903t4.webp","ULD_155":"ULD_155.webp","ULD_155p":"ULD_155p.webp","ULD_205":"ULD_205.webp","ULD_208":"ULD_208.webp","ULD_291p":"ULD_291p.webp","UNG_029":"UNG_029.webp","WW_001":"WW_001.webp","WW_001t17":"WW_001t17.webp","WW_001t18":"WW_001t18.webp","WW_001t23":"WW_001t23.webp","WW_001t24":"WW_001t24.webp","WW_001t25":"WW_001t25.webp","WW_001t26":"WW_001t26.webp","WW_001t27":"WW_001t27.webp","WW_001t5":"WW_001t5.webp","WW_434":"WW_434.webp","WW_823":"WW_823.webp","tt_010":"tt_010.webp","tt_010a":"tt_010a.webp"};
// Printed text from the same pinned representative records; not dynamic effect calculations.
const printedText={"CS2_182": "", "CS2_179": "嘲讽", "CS2_029": "造成6点伤害。", "EX1_096": "亡语：抽一张牌。", "FP1_007": "亡语：召唤一个4/4的蛛魔。", "CS2_122": "你的其他随从拥有+1攻击力。", "ULD_205": "复生", "ULD_208": "嘲讽，复生。亡语：为你的英雄恢复3点生命值。", "CS2_188": "战吼：在本回合中，使一个随从获得+2攻击力。", "EX1_019": "战吼：使一个友方随从获得+1/+1。", "CS2_024": "对一个角色造成3点伤害，并使其冻结。", "EX1_010": "潜行", "CS2_222": "你的其他随从拥有+1/+1。", "CS2_106": "", "FP1_021": "亡语：对所有随从造成1点伤害。", "HERO_08bp": "英雄技能\n造成1点伤害。", "HERO_01bp": "英雄技能\n获得2点护甲值。", "GAME_005": "在本回合中，获得一个\n法力水晶。", "EX1_608": "你的法术的法力值消耗减少（1）点（但不能少于1点）。", "BT_733": "所有随从受到的法术伤害翻倍。", "CS2_117": "战吼：\n恢复3点生命值。", "HERO_08": "", "HERO_01": "", "UNG_029": "从你的牌库中发现一张法术牌的复制。"};
const types={play_card:'出牌',attack:'攻击',use_hero_power:'英雄技能',end_turn:'结束回合',concede:'认输',select_choice:'提交选择',use_hand_action:'手牌主动操作',use_location:'使用地标',use_minion_ability:'随从能力',launch_starship:'发射星舰',use_interactable:'交互物'};
const errors={invalid_action:'操作不合法，请按当前合法操作重新选择。',stale_observation:'局面已变化，旧操作已拒绝；请根据刷新后的局面重选。',unsupported_rule:'此来源的规则尚未支持玩家接口。',unsupported_target_domain:'此目标范围尚未支持玩家接口。',enumeration_limit:'选择组合超出枚举预算，请使用上方选择面板。',rule_error:'引擎无法枚举此局面的完整操作。',resolution_failed:'引擎结算失败，本次操作已回滚。',seat_session_required:'原对局会话已失效，请点击创建新局。',host_error:'本地服务处理失败，请查看服务与演示配置。',origin_rejected:'请使用 127.0.0.1 的本地页面。'};
let resetArmed=false, concedeArmed=false, selected=null;
let previewTimer=null;
let cardCatalog=null;
let labReadOnly=false,labRequest=null;
const cardKindNames={minion:'随从',spell:'法术',weapon:'武器',location:'地标',hero:'英雄',hero_power:'英雄技能',enchantment:'附魔'};
const handReasons={game_not_playing:'对局已结束，请创建新局。',opening_pending:'完成双方换牌后可加牌。',choice_pending:'请先完成当前选择。',not_your_turn:'自己的回合才能加牌。',handoff_pending:'请先完成座位交接。',hand_full:'手牌已满，请先打出一些牌。',choice_only:'此项是选择专用定义，不能直接加入手牌。',card_not_hand_playable:'此类型不能直接加入手牌。',unknown_card:'当前模拟器尚未接入这张牌。'};
handReasons.special_card_template='此项需要专用场景生成，不能直接加入手牌。';
Object.assign(errors,{unknown_card:handReasons.unknown_card,card_not_hand_playable:handReasons.card_not_hand_playable,choice_only:handReasons.choice_only,hand_full:handReasons.hand_full,special_card_template:handReasons.special_card_template});
errors.test_hand_adjustment_unavailable='当前局面无法加入卡牌，原局面已保留。';
let botTimer=null, botGeneration=0, botPaused=false, pauseAfterWork=false, botClientError='';
const runningAnimations=new Set();
let token=sessionStorage.getItem('hs-seat')||'', message=null, busy=false;
const manaReasons={game_not_playing:'对局已结束，请创建新局。',opening_pending:'完成换牌后可调整法力。',choice_pending:'完成当前选择后可调整法力。',not_your_turn:'交接到当前回合的玩家后可调整法力。',special_mana_active:'当前有过载或临时法力，结清后可调整。'};
Object.assign(errors,{invalid_mana:'请输入 0–10 之间的整数。',mana_above_cap:'不能超过当前对局的法力上限。',test_adjustment_unavailable:'当前局面无法调整法力，原局面已保留。',...manaReasons,handoff_pending:'请先完成座位交接。'});
Object.assign(errors,{stale_opponent_step:'托管状态已更新，请按最新局面重试。',invalid_opponent:'请选择电脑托管或双人手动。',opponent_controls_seat:'请先暂停托管，再交接座位。',opponent_disabled:'对手托管已关闭。',opponent_paused:'对手托管已暂停。',opponent_not_acting:'当前不需要对手操作。',enumeration_failed:'当前规则无法完整列出操作，可切换手动查看。',choice_unavailable:'当前选择无法自动完成，可切换手动查看。',action_budget_exhausted:'本轮自动操作达到上限，可重试或手动接管。',command_rejected:'操作未被接受，可刷新后重试。',opponent_failed:'操作结算失败，可重试或手动接管。',no_legal_actions:'当前没有可继续的合法操作。'});
function notice(s){$('error').textContent=s||'';}
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function button(text,fn){const n=node('button',text);n.disabled=busy;n.onclick=fn;return n;}
function clearView(){closeBranchChoice();closeCardLab(true);cardCatalog=null;stopBotTimer();botPaused=false;pauseAfterWork=false;botClientError='';hidePreview();clearTargetLine();clearEffects();$('interaction-hint').textContent='';$('interaction-options').replaceChildren();$('cancel-selection').hidden=true;selected=null;message=null;$('diagnostics').open=false;$('mana-feedback').textContent='';resetArmed=false;concedeArmed=false;for(const id of ['players','logs','actions','choice','source','type'])$(id).replaceChildren();$('dto').textContent='';$('game').hidden=true;$('curtain').hidden=true;$('welcome').hidden=false;}
async function api(path,body={}){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){if(data.error==='seat_session_required'){token='';sessionStorage.removeItem('hs-seat');clearView();throw new Error('原对局会话已失效。点击「创建 / 重置对局」即可开始新局，无需重启服务。');}const error=new Error(errors[data.error]||data.error);error.code=data.error;throw error;}return data;}
function saveToken(t){token=t;sessionStorage.setItem('hs-seat',t);}
async function work(fn){if(busy||labReadOnly)return;clearEffects();stopBotTimer();busy=true;document.body.dataset.busy='true';document.querySelectorAll('button').forEach(b=>b.disabled=true);$('test-mana').disabled=true;if(message&&!message.handoff)updateEnd();updateCardLabControls();updateBotControls();try{notice('');await fn();}catch(e){notice(e.message);}finally{busy=false;document.body.dataset.busy='false';document.querySelectorAll('button').forEach(b=>b.disabled=false);if(message&&!message.handoff){updateEnd();updateTestControls();}updateBotControls();if(pauseAfterWork&&message&&!message.handoff){pauseAfterWork=false;void setOpponent('human');}else scheduleBot();}}
function name(c){return c?message.names?.[c.card_id]||c.card_id||'未知牌背':'无';}
function entities(){const map={};for(const p of message.observation.players)for(const c of [p.hero,p.hero_power,p.weapon,...p.additional_hero_powers,...p.board,...p.hand,...p.quests,...p.secrets])if(c)map[c.ref]=c;return map;}
function source(a){return a.card||a.attacker||a.power||a.location||a.minion||a.starship||a.object||'';}
function ref(r){if(!r)return '无';const c=entities()[r];return c?`${name(c)} (${r})`:r;}
function actionLabel(a){let s=types[a.type]||a.type;if(source(a))s+=' · '+ref(source(a));if(a.target)s+=' → '+ref(a.target);if(a.defender)s+=' → '+ref(a.defender);if(a.position!=null)s+=` · 第${a.position+1}个位置`;if(a.side)s+=' · '+(a.side==='enemy'?'对方战场':'己方战场');if(a.branch)s+=' · 分支 '+a.branch;if(a.action_id||a.ability_id)s+=' · '+(a.action_id||a.ability_id);if(a.magnetic_target)s+=' · 磁力 '+ref(a.magnetic_target);if(a.body_targets||a.body_route)s+=' · '+JSON.stringify(a.body_targets||a.body_route);return s;}
async function submit(a){
    await work(async()=>{
        if(a.type==='concede'&&!concedeArmed){concedeArmed=true;notice('再次点击认输将结束当前座位的对局。');return;}
        concedeArmed=false;hidePreview();clearTargetLine();
        const before=capturePresentation();
        const data=await api('action',{revision:message.revision,action:a});
        const attacked=data.accepted?await animateIntent(a,before,data):false;
        render(data);
        if(data.accepted)await animateOutcome(before,data,attacked?{type:'attack'}:a);
        else notice(errors[data.command_error]||data.command_error);
    });
}
const keywordNames={taunt:'嘲讽',divine_shield:'圣盾',charge:'冲锋',rush:'突袭',windfury:'风怒',mega_windfury:'超级风怒',stealth:'潜行',poisonous:'剧毒',lifesteal:'吸血',reborn:'复生',immune:'免疫',deathrattle:'亡语',battlecry:'战吼',spell_damage:'法术伤害',frozen:'冻结'};
const imbuedPowerIds=new Set(['EDR_847p','EDR_850p','EDR_851p','EDR_445p','EDR_449p','EDR_448p','END_000p','END_003p']);
function powerImbue(c){
    if(c?.kind!=='hero_power'||!imbuedPowerIds.has(c.card_id))return null;
    const owner=message?.observation?.players.find(p=>p.id===c.controller);
    if(!owner||![owner.hero_power,...(owner.additional_hero_powers||[])].some(p=>p?.ref===c.ref))return null;
    const progress=owner.imbue;
    return Number.isInteger(progress?.level)&&progress.level>=0?progress:null;
}
function cardText(c,imbue=powerImbue(c)){
    const text=message.card_texts?.[c.card_id]??printedText[c.card_id];
    // These eight R-100 adapters all use the owner's public max(1, level) amount.
    // This formats the known card's text only; actions and resolution stay in the engine.
    return imbuedPowerIds.has(c.card_id)&&imbue&&text?text.replace(/\$?@/g,String(Math.max(1,imbue.level))):text;
}
function tauntFrame(){
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('class','taunt-frame');svg.setAttribute('viewBox','0 0 100 120');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
    const shape='M 50 5 L 87 12 L 94 31 L 91 84 Q 83 103 50 115 Q 17 103 9 84 L 6 31 L 13 12 Z';
    for(const [color,width] of [['#27313a',11],['#d3e0e3',8],['#687d89',4],['#f6f8e9',1]]){
        const path=document.createElementNS(ns,'path');path.setAttribute('d',shape);path.setAttribute('fill','none');path.setAttribute('stroke',color);path.setAttribute('stroke-width',width);path.setAttribute('stroke-linejoin','round');svg.append(path);
    }
    return svg;
}
function card(c){
    const n=node('button',null,'card');n.type='button';n.disabled=busy;n.dataset.ref=c.ref;n.dataset.kind=c.kind||'unknown';n.dataset.zone=c.zone||'';
    const imbue=powerImbue(c);
    n.setAttribute('aria-label',name(c)+(imbue?`，灌注 ${imbue.level} 阶`:''));
    const art=node('span',null,'card-art');
    if(artwork[c.card_id]){const img=node('img');img.src='/assets/'+artwork[c.card_id];img.alt='';img.className='portrait';img.draggable=false;art.append(img);}
    else art.append(node('span',c.kind==='secret'?'?':'✦','art-fallback'));
    const body=node('span',null,'card-body');body.append(node('strong',name(c),'card-name'));
    const text=cardText(c,imbue);
    if(text)body.append(node('span',text,'card-text'));
    const onBoard=c.zone==='board',keywords=c.keywords||[],hasTaunt=c.kind==='minion'&&keywords.includes('taunt');
    const flags=[...keywords.filter(k=>!(hasTaunt&&k==='taunt')).map(k=>keywordNames[k]||k),c.frozen?'冻结':'',c.silenced?'沉默':'',c.dormancy?(c.dormancy.remaining_turns==null?'休眠':'休眠 '+c.dormancy.remaining_turns):''].filter(Boolean);
    if(flags.length)body.append(node('small',[...new Set(flags)].join(' · '),'card-flags'));
    n.append(art,body,node('span',({minion:'随从',spell:'法术',weapon:'武器',hero_power:'英雄技能',location:'地标',hero:'英雄'})[c.kind]||'','card-type'));
    if(c.cost)n.append(node('span',String(c.cost.amount),'cost-orb'));
    if(['hero','minion','weapon'].includes(c.kind)&&c.attack!=null){
        if(c.attack>0||c.kind!=='hero')n.append(node('span',String(c.attack),'attack-orb'));
        n.append(node('span',String(c.kind==='weapon'?c.durability:c.health),'health-orb'+(c.kind==='weapon'?' durability-orb':'')));
    }else if((c.kind==='location'&&c.durability!=null)||c.durability)n.append(node('span',String(c.durability),'health-orb durability-orb'));
    if(c.armor)n.append(node('span',String(c.armor),'armor-orb'));
    n.classList.toggle('frozen',!!c.frozen);n.classList.toggle('taunt',hasTaunt);
    if(hasTaunt){
        // This badge describes the visible keyword; legal target highlights still come from actions.
        const inactive=!!c.dormancy||!!c.starship?.building||keywords.includes('stealth')||keywords.includes('immune');
        n.classList.toggle('taunt-guard',onBoard&&!inactive);n.classList.toggle('taunt-inactive',inactive);
        n.append(tauntFrame(),node('span','嘲讽','taunt-badge'));
    }
    if(c.kind==='location'&&onBoard&&c.location){
        const cooldown=c.location.cooldown_remaining,usable=(message.actions||[]).some(a=>a.type==='use_location'&&a.location===c.ref);
        n.dataset.cooldown=String(cooldown);n.classList.toggle('location-cooling',cooldown>0);n.classList.toggle('location-open',!!c.location.open);
        const status=node('span',cooldown>0?`冷却 ${cooldown}`:usable?'可使用':c.location.open?'已开启':'已关闭','location-status');
        status.title=cooldown>0?`还需经过本方 ${cooldown} 次回合开始`:'点击亮起的地标，再按提示选择目标';
        n.append(status);n.querySelector('.durability-orb')?.setAttribute('title','剩余耐久');
    }
    n.classList.toggle('sleeping',!!c.dormancy||!!(c.summoned_this_turn&&c.zone==='board'));
    n.classList.toggle('power-used',c.kind==='hero_power'&&c.uses_this_turn>=c.use_limit);
    if(imbue){
        n.dataset.imbueLevel=String(imbue.level);
        const badge=node('span',`灌注 ${imbue.level} 阶`,'imbue-badge');
        badge.title=`当前灌注 ${imbue.level} 阶`+(Number.isInteger(imbue.count)?`；累计灌注 ${imbue.count} 次`:'');
        n.append(badge);
    }
    n.onclick=()=>clickEntity(c.ref);
    n.onfocus=()=>schedulePreview(c,n);n.onblur=hidePreview;
    const wrap=node('div',null,'entity-wrap');wrap.append(n);
    // Keep hover stable when a fanned card lifts away from the pointer.
    wrap.onpointerenter=()=>schedulePreview(c,n);wrap.onpointerleave=hidePreview;
    return wrap;
}
function zone(label,cards,owner=null){
    const wrap=node('div',null,'card-zone');wrap.append(node('div',label,'hint'));
    const row=node('div',null,'zone');const visible=cards.filter(Boolean);row.style.setProperty('--hand-count',visible.length);
    visible.forEach((c,i)=>{
        if(owner!==null)row.append(positionButton(owner,i));
        const entity=card(c);entity.dataset.index=i;entity.dataset.count=visible.length;
        const offset=i-(visible.length-1)/2;
        entity.style.setProperty('--card-index',i);entity.style.setProperty('--hand-count',visible.length);
        entity.style.setProperty('--card-angle',`${offset*Math.min(3,14/Math.max(1,visible.length))}deg`);
        entity.style.setProperty('--card-lift',`${Math.abs(offset)*2}px`);
        row.append(entity);
    });
    if(owner!==null)row.append(positionButton(owner,visible.length));
    wrap.append(row);return wrap;
}
function player(p){
    const own=p.id===message.seat;
    const section=node('section',null,'player '+(own?'friendly':'enemy')+(p.id===message.observation.active_player?' active':''));
    const info=node('div',null,'player-info');info.append(node('span',`${own?'我方':'对手'} · 牌库 ${p.deck_count} / 手牌 ${p.hand.length}`));
    const mana=node('div',null,'mana-display');mana.append(node('strong',`${p.mana}/${p.max_mana}`));
    for(let i=0;i<Math.min(p.max_mana,10);i++)mana.append(node('span','◆',i<p.mana?'mana-crystal':'mana-crystal spent'));
    if(p.overload_locked||p.overload_owed)mana.append(node('small',`过载 ${p.overload_locked} / ${p.overload_owed}`));
    if(Object.values(p.resources).some(Boolean))mana.append(node('small',JSON.stringify(p.resources)));
    info.append(mana);section.append(info);
    const deck=node('div',null,'deck-pile');deck.setAttribute('aria-label',`牌库剩余 ${p.deck_count} 张`);deck.append(node('span',String(p.deck_count),'deck-count'));section.append(deck);
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
function updateEnd(){
    const button=$('end'),observation=message?.observation;
    const complete=Array.isArray(message?.actions)&&message.error===null;
    const actions=complete?message.actions:[];
    const ownTurn=!!observation&&!message.handoff&&observation.status==='playing'&&observation.active_player===message.seat&&!observation.pending_choice;
    const enabled=ownTurn&&complete&&actions.some(action=>action.type==='end_turn');
    const ready=!busy&&enabled&&!actions.some(action=>action.type!=='end_turn'&&action.type!=='concede');
    button.disabled=busy||!enabled;
    button.classList.toggle('ready-to-end',ready);
    button.textContent=observation&&observation.status!=='playing'?'对局结束':observation&&observation.active_player!==message.seat?'对手回合':'结束回合';
    const hint=ready?'没有其他可用操作，点击结束回合':busy?'操作处理中':message?.handoff?'请先完成座位交接':observation?.status!=='playing'?'当前无法结束回合':observation.pending_choice?'请先完成当前选择':!ownTurn?'等待对手操作':!complete?'合法操作尚未完整加载':enabled?'结束当前回合':'当前无法结束回合';
    button.title=hint;
    button.setAttribute('aria-label',button.textContent+'，'+hint);
}
function updateTestControls(){
    const enabled=!!message?.test_controls?.mana_enabled&&!busy;
    for(const id of ['test-mana','apply-mana','mana-ten'])$(id).disabled=!enabled;
    const reason=message?.test_controls?.mana_reason;
    $('mana-help').textContent=manaReasons[reason]||'同时设置可用法力和法力上限；出牌后正常扣费。';
    updateCardLabControls();
}
function closeCardLab(clear=false){
    if($('card-lab').open)$('card-lab').close();
    $('card-lab-feedback').textContent='';
    if(clear){$('card-search').value='';$('card-results').replaceChildren();$('card-lab-count').textContent='';$('card-lab-window').textContent='';}
}
async function openCardLab(){
    if(busy||!message||message.handoff)return;
    selected=null;paintSelection();hidePreview();notice('');
    $('card-lab-feedback').textContent='';$('card-lab').showModal();
    await work(async()=>{
        try{
            if(!cardCatalog){
                cardCatalog=await api('catalog');
                $('card-kind').replaceChildren(new Option('所有类型',''),...[...new Set(cardCatalog.cards.map(c=>c.type))].sort().map(t=>new Option(cardKindNames[t]||t,t)));
            }
            $('card-lab-scope').textContent=`已接入 ${cardCatalog.total} 项实验定义，其中 ${cardCatalog.addable_count} 项可加入手牌。${cardCatalog.scope_note}`;
            renderCardCatalog();
        }catch(e){if($('card-lab').open)$('card-lab-feedback').textContent=e.message;throw e;}
    });
    if($('card-lab').open)$('card-search').focus();
}
function renderCardCatalog(){
    if(!cardCatalog)return;
    const query=$('card-search').value.trim().toLocaleLowerCase(),kind=$('card-kind').value;
    const matches=cardCatalog.cards.filter(c=>(!kind||c.type===kind)&&(!$('card-addable-only').checked||c.can_add)&&(!query||`${c.name} ${c.id} ${c.text}`.toLocaleLowerCase().includes(query)));
    $('card-lab-count').textContent=`找到 ${matches.length} 项`;
    $('card-results').replaceChildren();
    for(const c of matches){
        const tile=node('article',null,'lab-card');tile.dataset.cardId=c.id;
        const heading=node('div',null,'lab-card-heading');
        const cost=node('span',c.cost==null?'—':String(c.cost),'lab-cost');cost.title=c.cost_resource&&c.cost_resource!=='mana'?c.cost_resource:'印刷费用';
        if(artwork[c.id]){const art=node('img',null,'lab-card-portrait');art.src='/assets/'+artwork[c.id];art.alt='';art.loading='lazy';art.decoding='async';heading.append(art);}
        const title=node('div');title.append(node('h3',c.name),node('small',`${cardKindNames[c.type]||c.type} · ${c.id}`));
        heading.append(cost,title);tile.append(heading,node('p',c.text||'无印刷效果文字。','lab-card-text'));
        if(c.note){const details=node('details',null,'lab-card-note');details.append(node('summary','实验范围说明'),node('p',c.note));tile.append(details);}
        const add=button('加入手牌',()=>addTestCard(c));add.type='button';add.dataset.addCard=c.id;add.dataset.addable=String(c.can_add);add.setAttribute('aria-label',`加入手牌：${c.name}`);
        if(!c.can_add){add.textContent=handReasons[c.disabled_reason]||'不能直接加入手牌';add.title=c.disabled_reason||'';}
        tile.append(add);$('card-results').append(tile);
    }
    if(!matches.length)$('card-results').append(node('p','没有匹配项。试试其他名称或 ID，或取消「可加入手牌」筛选。尚未接入的正式卡牌不在此目录中。','lab-empty'));
    updateCardLabControls();
}
function updateCardLabControls(){
    const controls=message?.test_controls;
    $('open-card-lab').disabled=busy||!message||!!message.handoff||!controls||!Object.hasOwn(controls,'hand_enabled');
    for(const b of $('card-results').querySelectorAll('button[data-add-card]'))b.disabled=busy||!controls?.hand_enabled||b.dataset.addable!=='true';
    const own=message?.observation?.players.find(p=>p.id===message.seat);
    $('card-lab-window').textContent=own?(controls?.hand_enabled?`加入我方手牌 · 当前 ${own.hand.length} 张`:(handReasons[controls?.hand_reason]||'当前不能加入手牌。')):'';
    // Closing a read-only catalog is safe even while an accepted request finishes.
    $('close-card-lab').disabled=false;
}
async function addTestCard(c){
    if(busy||!message?.test_controls?.hand_enabled||!c.can_add)return;
    await work(async()=>{
        $('card-lab-feedback').textContent=`正在加入「${c.name}」…`;
        try{
            const data=await api('test/hand',{revision:message.revision,card_id:c.id});render(data);
            $('card-lab-feedback').textContent=`已加入「${c.name}」。可继续选牌，或返回对战从手牌打出。`;
        }catch(e){
            if(message&&!message.handoff)render(await api('view'));
            if($('card-lab').open)$('card-lab-feedback').textContent=handReasons[e.code]||e.message;
            throw e;
        }
    });
}
async function setTestMana(value){
    if(!Number.isInteger(value)||value<0||value>10)return notice(errors.invalid_mana);
    await work(async()=>{
        try {
            const data=await api('test/mana',{revision:message.revision,mana:value});
            render(data);
            $('mana-feedback').textContent=`已设为 ${value}/${value} 法力`;
        } catch(e) {
            if(message&&!message.handoff)render(await api('view'));
            throw e;
        }
    });
}
function stopBotTimer(){clearTimeout(botTimer);botTimer=null;botGeneration++;}
function updateBotControls(){
    const opponent=message?.opponent, ai=opponent?.mode==='ai';
    const failed=!!(opponent?.error||botClientError);
    if(opponent)$('opponent-mode').value=opponent.mode;
    $('opponent-mode').disabled=busy||!!message?.handoff;
    $('switch').hidden=ai;
    $('bot-control').hidden=!ai||!!message?.handoff;
    $('bot-control').textContent=pauseAfterWork?'正在暂停…':botPaused?'重试暂停':failed?'重试托管':'暂停托管';
    // Pausing is local and immediate, even while the current request animates.
    $('bot-control').disabled=pauseAfterWork||(busy&&(failed||botPaused));
}
async function setOpponent(mode){
    if(!message||message.handoff)return;
    await work(async()=>{
        try{
            const data=await api('opponent',{revision:message.revision,ticket:message.opponent.ticket,mode});
            botClientError='';botPaused=false;pauseAfterWork=false;render(data);
        }catch(e){
            botClientError=e.message;
            if(message&&!message.handoff)render(await api('view'));
            throw e;
        }
    });
}
function scheduleBot(){
    stopBotTimer();
    if(busy||botPaused||botClientError||!message||message.handoff||message.opponent?.mode!=='ai'||!message.opponent.can_step||message.opponent.error)return;
    const generation=botGeneration;
    botTimer=setTimeout(()=>{botTimer=null;if(generation===botGeneration)void stepOpponent();},450);
}
async function stepOpponent(){
    if(busy||botPaused||!message?.opponent?.can_step||message.handoff)return;
    await work(async()=>{
        try{
            const before=capturePresentation();
            const data=await api('opponent/step',{revision:message.revision,ticket:message.opponent.ticket});
            const attacked=data.opponent_acted?await animateIntent(null,before,data):false;
            render(data);
            // Only completed attacks already disclosed in this seat's events animate.
            if(data.opponent_acted)await animateOutcome(before,data,attacked?{type:'attack'}:null);
            if(data.opponent.error)notice(botErrorText(data.opponent.error));
        }catch(e){
            if(['stale_observation','stale_opponent_step'].includes(e.code)&&message){render(await api('view'));return;}
            botClientError=e.message;notice('托管已暂停：'+e.message);
        }
    });
}
function botErrorText(code){return '托管已暂停：'+(errors[code]||'当前操作无法继续。可重试托管，或切换双人手动。');}
function render(data){
    if(data.card_art)Object.assign(artwork,data.card_art);
    closeBranchChoice();hidePreview();clearTargetLine();selected=null;message=data;
    $('mana-feedback').textContent='';
    $('welcome').hidden=true;$('curtain').hidden=!data.handoff;$('game').hidden=!!data.handoff;
    if(data.handoff){closeCardLab(true);$('handoff-title').textContent=`请玩家${data.seat}接手`;return;}
    const o=data.observation;
    const phase=o.status!=='playing'?(o.winner?'玩家'+o.winner+'获胜':'对局结束 / 平局'):o.opening_stage&&o.opening_stage!=='complete'?'起手换牌':o.active_player===data.seat?'你的回合':data.opponent?.mode==='ai'?'电脑回合':'对手回合 · 请交接座位';
    $('status').textContent=`第 ${o.turn} 回合 · ${phase} · 座位 ${data.seat}`;
    $('test-mana').value=o.players.find(p=>p.id===data.seat).mana;
    $('players').replaceChildren(...[...o.players].sort((a,b)=>(a.id===data.seat)-(b.id===data.seat)).map(player));
    $('type').replaceChildren(new Option('所有操作',''),...Object.keys(types).map(t=>new Option(types[t],t)));
    const map=entities();$('source').replaceChildren(new Option('所有来源',''),...Object.keys(map).map(r=>new Option(ref(r),r)));
    $('action-count').textContent=`(${data.actions?.length??'未完整枚举'})`;$('fallback').hidden=!data.error;
    renderActions();renderChoice();paintSelection();
    $('logs').replaceChildren(...data.events.map(e=>node('p',`${e.sequence} · ${e.kind}${e.player_id?' · 玩家'+e.player_id:''}${e.source?' · '+name(e.source):''}${e.target?' → '+name(e.target):''}${e.amount!=null?' · '+e.amount:''}`)));
    $('logs').scrollTop=$('logs').scrollHeight;$('dto').textContent=JSON.stringify(data,null,2);
    if(data.error)notice(errors[data.error]||data.error);
    updateEnd();updateTestControls();updateBotControls();
    if(data.opponent?.error)notice(botErrorText(data.opponent.error));
    if(window.parent!==window)void publishLabRender();
}
function renderChoice(){
    const c=message.observation.pending_choice;
    $('choice').hidden=!c;$('choice').replaceChildren();if(!c)return;
    if(!c.options){
        if(message.opponent?.mode==='ai'){$('choice').hidden=true;return;}
        $('choice').append(node('h2',`等待玩家${c.player_id}选择。`),button('交接座位',()=>$('switch').click()));return;
    }
    $('choice').append(node('h2',c.purpose==='mulligan'?'换牌：勾选要换掉的手牌':c.prompt),node('p',`选择 ${c.min_count}–${c.max_count} 项。${c.purpose==='mulligan'?'未勾选的手牌会保留。':''}`));
    for(const o of c.options){
        const label=node('label',null,'choice-option');const input=node('input');input.type='checkbox';input.value=o.ref;
        label.append(input,document.createTextNode(' '+o.label+(o.card_id?' · '+name(o):'')));
        if(artwork[o.card_id]){const img=node('img');img.src='/assets/'+artwork[o.card_id];img.alt='';img.className='choice-art';label.prepend(img);}
        $('choice').append(label);
    }
    $('choice').append(button('确认选择',()=>{const options=[...$('choice').querySelectorAll('input:checked')].map(n=>n.value);if(options.length<c.min_count||options.length>c.max_count)return notice(`请选择 ${c.min_count}–${c.max_count} 项。`);submit({type:'select_choice',choice:c.ref,options});}));
}
$('create').onclick=()=>work(async()=>{if(message&&!resetArmed){resetArmed=true;notice('再次点击创建 / 重置对局将重新开局。');return;}resetArmed=false;const d=await api('create',{preset:$('preset').value,opponent:$('opponent-mode').value});saveToken(d.token);botPaused=false;pauseAfterWork=false;botClientError='';render(await api('view'));});
$('opponent-mode').onchange=()=>{if(message&&!message.handoff)void setOpponent($('opponent-mode').value);};
$('bot-control').onclick=()=>{
    if(botPaused){void setOpponent('human');return;}
    if(message?.opponent?.error||botClientError){void setOpponent('ai');return;}
    botPaused=true;pauseAfterWork=busy;stopBotTimer();updateBotControls();
    if(!busy)void setOpponent('human');
};
$('mana-form').onsubmit=e=>{e.preventDefault();if($('test-mana').reportValidity())setTestMana(Number($('test-mana').value));};
$('mana-ten').onclick=()=>setTestMana(10);
$('open-card-lab').onclick=openCardLab;
$('close-card-lab').onclick=()=>closeCardLab();
$('card-search').oninput=renderCardCatalog;
$('card-kind').onchange=renderCardCatalog;
$('card-addable-only').onchange=renderCardCatalog;
$('card-lab').addEventListener('cancel',()=>{$('card-lab-feedback').textContent='';});
$('refresh').onclick=()=>work(async()=>render(await api('view')));
$('switch').onclick=()=>work(async()=>{const d=await api('handoff');saveToken(d.token);$('diagnostics').open=false;hidePreview();clearTargetLine();clearEffects();selected=null;message=null;$('players').replaceChildren();$('logs').replaceChildren();$('dto').textContent='';$('actions').replaceChildren();$('choice').replaceChildren();$('source').replaceChildren();$('type').replaceChildren();$('interaction-hint').textContent='等待接手';$('interaction-options').replaceChildren();render(d);});
$('ready').onclick=()=>work(async()=>render(await api('ready')));
$('end').onclick=()=>submit({type:'end_turn'});$('fallback').onclick=$('end').onclick;
$('source').onchange=renderActions;$('type').onchange=renderActions;
if(token)work(async()=>render(await api('view')));



// Direct interaction projects exact engine actions; it never calculates legality.
function targetOf(a){return a.type==='attack'?a.defender:a.target;}
function simple(a){return !a.body_targets&&!a.body_route;}
function modeKey(a){return JSON.stringify([a.type,a.branch||null,a.action_id||null,a.ability_id||null,a.side||'friendly']);}
function currentActions(){return selected?selected.actions:[];}
function chooseMode(actions){if(busy)return;closeBranchChoice();if(actions.length===1&&immediate(actions[0])){submit(actions[0]);return;}selected={actions};paintSelection();}
function branchLabel(a){return entities()[source(a)]?.choose_one?.find(b=>b.id===a.branch)?.label||a.branch;}
function closeBranchChoice(){const d=$('branch-choice');if(d.open)d.close();$('branch-options').replaceChildren();$('branch-title').textContent='';}
function renderBranchChoice(){
    const groups=selected?.groups;
    if(!groups||!groups.every(g=>g[0].branch)){closeBranchChoice();return false;}
    const c=entities()[source(groups[0][0])];
    $('branch-title').textContent=name(c)+' · 选择效果';
    $('branch-options').replaceChildren(...groups.map(group=>{
        const a=group[0],b=button('',()=>chooseMode(group));b.className='branch-option';b.dataset.branch=a.branch;
        if(artwork[c?.card_id]){const img=node('img');img.src='/assets/'+artwork[c.card_id];img.alt='';b.append(img);}
        b.append(node('strong',branchLabel(a)));return b;
    }));
    if(!$('branch-choice').open)$('branch-choice').showModal();
    return true;
}
function immediate(a){return !targetOf(a)&&a.position==null&&!a.magnetic_target&&simple(a)&&['play_card','use_hero_power','use_location','use_minion_ability','use_interactable','use_hand_action'].includes(a.type);}
function clickEntity(r){
    if(busy||!message||message.handoff)return;
    if(selected&&!selected.groups&&(selected.positionChosen||!currentActions().some(a=>a.position!=null))){
        const matches=currentActions().filter(a=>targetOf(a)===r);
        if(matches.length){advance(matches,selected.positionChosen,true);return;}
    }
    const own=message.observation.players.find(p=>p.id===message.seat);
    if(own.weapon?.ref===r&&(message.actions||[]).some(a=>a.type==='attack'&&a.attacker===own.hero.ref))r=own.hero.ref;
    const available=(message.actions||[]).filter(a=>source(a)===r&&simple(a));
    if(!available.length){notice(selected?'这不是当前操作的合法目标。请点击高亮目标，或取消选择。':'当前没有可用操作。可悬停查看卡牌。');return;}
    notice('');hidePreview();
    if(available.length===1&&immediate(available[0])){submit(available[0]);return;}
    const groups=new Map();for(const a of available){const k=modeKey(a);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(a);}
    selected={actions:available,groups:groups.size>1?[...groups.values()]:null};paintSelection();
}
function advance(actions,positionChosen=selected?.positionChosen,targetChosen=false){
    // A unique legal target still needs an explicit click after placement.
    if(actions.length===1&&(!targetOf(actions[0])||targetChosen)&&(actions[0].position==null||positionChosen)){submit(actions[0]);return;}
    selected={actions,positionChosen};paintSelection();
}
function positionButton(owner,index){
    const b=button('+',()=>{
        const actions=currentActions().filter(a=>a.position===index&&(a.side==='enemy'?3-message.seat:message.seat)===owner);
        if(actions.length)advance(actions,true);
    });b.className='position-slot';b.dataset.owner=owner;b.dataset.position=index;
    b.setAttribute('aria-label',`在玩家${owner}战场第${index+1}个位置出牌`);b.hidden=true;return b;
}
function paintSelection(){
    clearTargetLine();hidePreview();
    const actions=currentActions();const choosingMode=!!selected?.groups;
    $('interaction-options').replaceChildren();$('cancel-selection').hidden=!selected;
    const branchDialog=renderBranchChoice();
    const positions=!choosingMode&&!selected?.positionChosen&&actions.some(a=>a.position!=null);
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
    if(!selected){
        const pending=message.observation.pending_choice;
        $('interaction-hint').textContent=message.opponent?.error||botClientError?'托管已暂停，可重试或切换双人手动。':pending?.player_id===message.seat?'请在选择面板完成当前选择。':message.opponent?.mode==='ai'&&message.opponent.can_step?(pending?'电脑正在完成选择…':'电脑正在操作…'):pending?'等待另一位玩家选择，请交接座位。':'点击亮起的手牌出牌，或点击己方随从 / 英雄发起攻击。';return;
    }
    const first=actions[0];const label=name(entities()[source(first)]);
    if(choosingMode){
        $('interaction-hint').textContent=branchDialog?`已选 ${label}，请在中央选择效果。`:`已选 ${label}，请选择操作 / 分支。`;
        if(!branchDialog)for(const group of selected.groups){const a=group[0];$('interaction-options').append(button((types[a.type]||a.type)+(a.branch?' · '+branchLabel(a):'')+(a.action_id?' · '+a.action_id:'')+(a.ability_id?' · '+a.ability_id:'')+(a.side?' · '+(a.side==='enemy'?'对方战场':'己方战场'):''),()=>chooseMode(group)));}
    }else if(positions){$('interaction-hint').textContent=`已选 ${label}，点击战场上的「+」选择入场位置。`;}
    else if(targets.size){drawTargetLine();$('interaction-hint').textContent=`已选 ${label}，点击绿色高亮目标${first.type==='attack'?'进行攻击':'施放'}。`;
        // A nullable target is a distinct engine choice, not an automatic default.
        const untargeted=actions.filter(a=>!targetOf(a));if(untargeted.length)$('interaction-options').append(button('不选择目标',()=>advance(untargeted)));
    }else if(actions.length===1){$('interaction-hint').textContent=`已选 ${label}，点击确认执行。`;$('interaction-options').append(button('确认'+(types[first.type]||'操作'),()=>submit(first)));}
    else{$('interaction-hint').textContent='该操作有额外参数，请选择具体方案。';for(const a of actions)$('interaction-options').append(button(actionLabel(a),()=>submit(a)));}
}
$('cancel-selection').onclick=()=>{selected=null;notice('');paintSelection();};
$('cancel-branch').onclick=()=>{if(!busy){selected=null;notice('');paintSelection();}};
$('branch-choice').addEventListener('cancel',e=>{e.preventDefault();if(!busy){selected=null;paintSelection();}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&message&&!message.handoff){selected=null;paintSelection();}});

// Test automation reads the same seat-limited view as the tabletop.
window.render_game_to_text=()=>{
    if(!message||message.handoff)return JSON.stringify({mode:message?.handoff?'handoff':'welcome'});
    const o=message.observation;
    const visibleCard=c=>c&&({name:name(c),ref:c.ref,kind:c.kind,cost:c.cost?.amount,attack:c.attack,health:c.health,armor:c.armor,keywords:c.keywords,durability:c.durability,location:c.location,dormancy:c.dormancy,imbue_level:powerImbue(c)?.level,text:cardText(c)});
    return JSON.stringify({mode:'battle',seat:message.seat,turn:o.turn,active_player:o.active_player,status:o.status,
        players:o.players.map(p=>({id:p.id,mana:p.mana,max_mana:p.max_mana,deck_count:p.deck_count,imbue:p.imbue,hero:visibleCard(p.hero),hero_power:visibleCard(p.hero_power),board:p.board.map(visibleCard),hand:p.hand.map(c=>c.card_id?visibleCard(c):{hidden:true})})),
        pending_choice:o.pending_choice,interaction:$('interaction-hint').textContent,branch_choice:{open:$('branch-choice').open,options:[...$('branch-options').children].map(n=>({id:n.dataset.branch,label:n.textContent}))},mana_enabled:message.test_controls?.mana_enabled,
        card_lab:{open:$('card-lab').open,hand_enabled:message.test_controls?.hand_enabled,query:$('card-search').value,results:$('card-lab-count').textContent,feedback:$('card-lab-feedback').textContent},
        opponent:message.opponent&&{mode:message.opponent.mode,seat:message.opponent.seat,can_step:message.opponent.can_step,error:message.opponent.error,paused:botPaused},
        diagnostic_open:$('diagnostics').open,error:$('error').textContent});
};
// Deterministic presentation hook; rules remain driven solely by server replies.
window.advanceTime=async()=>{for(const animation of [...runningAnimations])animation.finish();await Promise.resolve();};

// The workbench embeds this exact battle UI. Only this same-origin parent can
// load its new test session or a read-only, player-projected inspection frame.
function auditLabUI(){
    const issues=[];let checked=0,missingArt=0;
    if(!message?.observation)return{passed:false,checked:0,issues:['没有玩家画面。'],missing_art:0};
    for(const p of message.observation.players){
        const cards=[p.hero,p.hero_power,...p.additional_hero_powers,p.weapon,...p.board,...p.secrets,...p.quests,...p.pending_plays,...(p.id===message.seat?p.hand:[])].filter(c=>c?.card_id&&c?.ref);
        for(const c of cards){
            checked++;const n=document.querySelector('#players .card[data-ref="'+CSS.escape(c.ref)+'"]');
            if(!n){issues.push(name(c)+'：未显示卡面');continue;}
            const value=(selector,expected)=>{if(expected==null)return;const actual=n.querySelector(selector)?.textContent;if(actual!==String(expected))issues.push(name(c)+'：'+selector+' 显示 '+actual+'，应为 '+expected);};
            value('.card-name',name(c));
            if(c.cost)value('.cost-orb',c.cost.amount);
            if(['minion','weapon'].includes(c.kind)||c.kind==='hero'&&c.attack>0)value('.attack-orb',c.attack);
            if(['hero','minion'].includes(c.kind))value('.health-orb',c.health);
            if(['weapon','location'].includes(c.kind))value('.durability-orb',c.durability);
            if(c.kind==='minion'&&(c.keywords||[]).includes('taunt')&&!n.querySelector('.taunt-badge'))issues.push(name(c)+'：缺少嘲讽标记');
            if(!n.querySelector('.portrait'))missingArt++;
            if(n.getBoundingClientRect().width<1)issues.push(name(c)+'：卡面尺寸不可见');
        }
    }
    return{passed:issues.length===0,checked,issues,missing_art:missingArt};
}
async function publishLabRender(){
    const request=labRequest,current=message;
    if(labReadOnly){document.querySelectorAll('button,input,select').forEach(n=>n.disabled=true);notice('自动巡检快照。请在工作台点击「创建测试局面」进行手动操作。');}
    await Promise.all([...document.querySelectorAll('#players img')].map(img=>img.decode?.().catch(()=>{})));
    await new Promise(resolve=>requestAnimationFrame(resolve));
    if(current!==message)return;
    const audit=auditLabUI();
    if(!labReadOnly)window.parent.postMessage({type:'lab:state',data:message,token},location.origin);
    window.parent.postMessage({type:'lab:rendered',request,audit},location.origin);
}
window.addEventListener('message',async e=>{
    if(window.parent===window||e.origin!==location.origin||e.source!==window.parent)return;
    const d=e.data;if(!d||!['lab:load','lab:preview'].includes(d.type)||busy)return;
    labRequest=d.request;stopBotTimer();
    if(d.type==='lab:preview'){
        if(!d.data?.observation)return;
        labReadOnly=true;saveToken('');render(d.data);
    }else if(typeof d.token==='string'){
        labReadOnly=false;saveToken(d.token);botPaused=true;
        await work(async()=>render(await api('view')));
    }
});
if(window.parent!==window)window.parent.postMessage({type:'lab:ready'},location.origin);

function hidePreview(){
    clearTimeout(previewTimer);previewTimer=null;
    if($('card-preview')){$('card-preview').hidden=true;$('card-preview').replaceChildren();}
}
function schedulePreview(c,anchor){
    hidePreview();
    if(busy||selected||!c.card_id)return;
    previewTimer=setTimeout(()=>{
        const panel=$('card-preview');
        if(!panel||!anchor.isConnected||!message||message.handoff||busy||selected)return;
        const clone=anchor.cloneNode(true);clone.removeAttribute('data-ref');clone.removeAttribute('aria-pressed');
        clone.className='card preview-card';clone.tabIndex=-1;clone.disabled=false;
        panel.replaceChildren(clone);panel.hidden=false;
        const rect=anchor.getBoundingClientRect(),size=panel.getBoundingClientRect();
        const preferred=rect.left>innerWidth/2?rect.left-size.width-18:rect.right+18;
        panel.style.left=`${Math.max(8,Math.min(innerWidth-size.width-8,preferred))}px`;
        panel.style.top=`${Math.max(56,Math.min(innerHeight-size.height-8,rect.top-size.height/3))}px`;
    },280);
}
function clearTargetLine(){if($('target-line')){$('target-line').setAttribute('hidden','');$('target-line').replaceChildren();}}
function drawTargetLine(pointer){
    const svg=$('target-line');
    if(!svg||!selected||selected.groups||!document.querySelector('.valid-target'))return;
    const origin=document.querySelector('.selected-source');if(!origin)return;
    const r=origin.getBoundingClientRect();
    // A hidden SVG has no layout until shown.
    svg.removeAttribute('hidden');
    const b=svg.getBoundingClientRect();
    const start={x:r.left+r.width/2-b.left,y:r.top+r.height/2-b.top};
    const target=pointer||{clientX:r.left+r.width/2,clientY:r.top-65};
    const end={x:Math.max(0,Math.min(b.width,target.clientX-b.left)),y:Math.max(0,Math.min(b.height,target.clientY-b.top))};
    svg.setAttribute('viewBox',`0 0 ${b.width} ${b.height}`);
    const ns='http://www.w3.org/2000/svg';
    const path=document.createElementNS(ns,'path');path.setAttribute('class','aim-line');
    path.setAttribute('d',`M ${start.x} ${start.y} Q ${start.x} ${(start.y+end.y)/2} ${end.x} ${end.y}`);
    path.setAttribute('fill','none');path.setAttribute('stroke','#dd3d30');path.setAttribute('stroke-width','7');
    const angle=Math.atan2(end.y-start.y,end.x-start.x),len=20;
    const head=document.createElementNS(ns,'path');head.setAttribute('fill','#f44734');
    head.setAttribute('d',`M ${end.x} ${end.y} L ${end.x-len*Math.cos(angle-.45)} ${end.y-len*Math.sin(angle-.45)} L ${end.x-len*Math.cos(angle+.45)} ${end.y-len*Math.sin(angle+.45)} Z`);
    svg.replaceChildren(path,head);
}
document.addEventListener('pointermove',e=>{
    if(selected&&!busy)drawTargetLine(e);
});
document.addEventListener('contextmenu',e=>{
    if(selected&&e.target.closest('#battle-table')){e.preventDefault();selected=null;paintSelection();notice('');}
});
window.addEventListener('resize',()=>{hidePreview();clearTargetLine();});
function clearEffects(){
    for(const animation of runningAnimations)animation.cancel();runningAnimations.clear();
    $('fx-layer')?.replaceChildren();
}
function reducedMotion(){return window.matchMedia('(prefers-reduced-motion: reduce)').matches;}
function animateElement(el,keyframes,options={}){
    if(!el||reducedMotion()||!el.animate)return Promise.resolve();
    const animation=el.animate(keyframes,{duration:280,easing:'ease-out',...options});
    runningAnimations.add(animation);
    return animation.finished.catch(()=>{}).finally(()=>runningAnimations.delete(animation));
}
function capturePresentation(){
    const layer=$('fx-layer')||$('battle-table'),base=layer.getBoundingClientRect(),cards={};
    for(const el of document.querySelectorAll('#players .card[data-ref]')){
        const r=el.getBoundingClientRect();cards[el.dataset.ref]={el,x:r.left+r.width/2-base.left,y:r.top+r.height/2-base.top,width:r.width,height:r.height};
    }
    return {cards,entities:entities(),observation:message.observation};
}
function effectNode(cls,point,text){
    if(!$('fx-layer'))return null;
    const el=node('span',text,cls);el.style.left=`${point.x}px`;el.style.top=`${point.y}px`;
    if(cls==='fx-turn-banner'){el.style.left='50%';el.style.top='43%';}
    $('fx-layer').append(el);return el;
}
function completedAttacks(before,data){
    return (data.events||[]).filter(e=>e.sequence>before.observation.event_cursor&&e.kind==='attack_finished'&&e.source?.ref&&e.target?.ref).sort((a,b)=>a.sequence-b.sequence);
}
async function animateAttack(from,to){
    if(!from||!to||!from.el.isConnected||!to.el.isConnected||reducedMotion())return;
    const distance=Math.hypot(to.x-from.x,to.y-from.y);if(distance<1)return;
    const ux=(to.x-from.x)/distance,uy=(to.y-from.y)/distance;
    const travel=Math.max(0,distance-Math.min(32,(from.height+to.height)*.18)),dx=ux*travel,dy=uy*travel;
    const ghost=node('div',null,'fx-attacker '+(from.el.dataset.kind==='hero'?'hero-slot':'battle-row'));
    const clone=from.el.cloneNode(true);clone.removeAttribute('data-ref');clone.removeAttribute('id');clone.removeAttribute('aria-label');
    clone.classList.remove('can-act','selected-source','valid-target');clone.tabIndex=-1;clone.disabled=true;
    ghost.setAttribute('aria-hidden','true');ghost.dataset.attackPhase='windup';ghost.append(clone);
    Object.assign(ghost.style,{left:`${from.x-from.width/2}px`,top:`${from.y-from.height/2}px`,width:`${from.width}px`,height:`${from.height}px`});
    $('fx-layer').append(ghost);
    const trail=effectNode('fx-attack-trail',from),angle=Math.atan2(uy,ux)*180/Math.PI;
    trail.style.width=`${travel}px`;trail.style.transform=`translateY(-50%) rotate(${angle}deg)`;
    const visibility=from.el.style.visibility;from.el.style.visibility='hidden';
    const home='translate(0,0) scale(1)',windup=`translate(${-ux*11}px,${-uy*11}px) scale(1.1)`,contact=`translate(${dx}px,${dy}px) scale(1.06)`;
    let impact;
    try{
        await animateElement(ghost,[{transform:home},{transform:windup}],{duration:85,easing:'ease-out',fill:'forwards'});
        ghost.dataset.attackPhase='lunge';
        await Promise.all([
            animateElement(ghost,[{transform:windup},{transform:contact}],{duration:110,easing:'cubic-bezier(.6,0,1,.45)',fill:'forwards'}),
            animateElement(trail,[{opacity:0},{opacity:.85,offset:.6},{opacity:.25}],{duration:110,fill:'forwards'})
        ]);
        ghost.dataset.attackPhase='impact';impact=effectNode('fx-impact',to);
        const hit=Promise.all([
            animateElement(impact,[{transform:'translate(-50%,-50%) scale(.25)',opacity:0},{transform:'translate(-50%,-50%) scale(1.12)',opacity:1,offset:.25},{transform:'translate(-50%,-50%) scale(1.45)',opacity:0}],{duration:185}),
            animateElement(to.el,[{transform:'translate(0,0)',filter:'brightness(1)'},{transform:`translate(${ux*8}px,${uy*8}px) rotate(3deg)`,filter:'brightness(1.7)',offset:.3},{transform:'translate(0,0)',filter:'brightness(1)'}],{duration:165}),
            animateElement(trail,[{opacity:.25},{opacity:0}],{duration:100,fill:'forwards'})
        ]);
        await animateElement(ghost,[{transform:contact,filter:'brightness(1.2)'},{transform:contact,filter:'brightness(1)'}],{duration:35,fill:'forwards'});
        ghost.dataset.attackPhase='return';
        await Promise.all([hit,animateElement(ghost,[{transform:contact},{transform:'translate(0,0) scale(.97)',offset:.85},{transform:home}],{duration:150,easing:'ease-out',fill:'forwards'})]);
    }finally{
        from.el.style.visibility=visibility;ghost.remove();trail?.remove();impact?.remove();
    }
}
async function animateIntent(a,before,data){
    if(reducedMotion())return false;
    const attacks=completedAttacks(before,data);
    if(attacks.length){
        for(const event of attacks)await animateAttack(before.cards[event.source.ref],before.cards[event.target.ref]);
    }else{
        // A declared but cancelled attack has no completed collision to present.
        if(!a||a.type==='attack')return false;
        const from=before.cards[source(a)],to=before.cards[targetOf(a)];if(!from)return false;
        if(to){
        const projectile=effectNode('fx-projectile',from);
        await Promise.all([animateElement(from.el,[{filter:'brightness(1)'},{filter:'brightness(1.8)'},{filter:'brightness(1)'}]),
            animateElement(projectile,[{transform:'translate(-50%,-50%) scale(.45)',opacity:0},{opacity:1,offset:.15},{transform:`translate(calc(-50% + ${to.x-from.x}px),calc(-50% + ${to.y-from.y}px)) scale(1.3)`,opacity:1}],{duration:330,easing:'ease-in'})]);
        projectile?.remove();
        }else{
        await animateElement(from.el,[{filter:'brightness(1)',opacity:1},{filter:'brightness(1.65)',transform:'scale(1.1)',opacity:.8},{filter:'brightness(1)',opacity:1}],{duration:220});
        }
    }
    const remaining=new Set(data.observation.players.flatMap(p=>p.board.map(c=>c.ref)));
    await Promise.all(Object.entries(before.entities).filter(([id,c])=>c.zone==='board'&&!remaining.has(id)).map(([id])=>animateElement(before.cards[id]?.el,[{opacity:1,transform:'scale(1)'},{opacity:0,transform:'scale(.55) translateY(15px)'}],{duration:190})));
    return attacks.length>0;
}
async function animateOutcome(before,data,action){
    if(reducedMotion())return;
    const after=capturePresentation(),effects=[];
    for(const [id,c] of Object.entries(after.entities)){
        const old=before.entities[id],at=after.cards[id];if(!at)continue;
        if(!old||old.zone!==c.zone){
            effects.push(animateElement(at.el,[{transform:'translateY(18px) scale(.7)',opacity:0},{transform:'translateY(0) scale(1)',opacity:1}],{duration:320}));
        }
        if(old&&c.health!==old.health&&['hero','minion'].includes(c.kind)){
            const delta=c.health-old.health;
            const number=effectNode('fx-number'+(delta>0?' healing':''),at,(delta>0?'+':'')+delta);
            const floating=animateElement(number,[{transform:'translate(-50%,-25%) scale(.5)',opacity:0},{transform:'translate(-50%,-60%) scale(1.2)',opacity:1,offset:.25},{transform:'translate(-50%,-130%) scale(1)',opacity:0}],{duration:650}).then(()=>number?.remove());
            // Cosmetic attack numbers can finish after the card has returned.
            if(action?.type!=='attack'){
                effects.push(floating);
                effects.push(animateElement(at.el,[{filter:'brightness(2)',transform:'translateX(-3px)'},{filter:'brightness(1)',transform:'translateX(3px)',offset:.55},{transform:'translateX(0)'}],{duration:280}));
            }
        }
        if(old&&c.armor>old.armor){
            const number=effectNode('fx-number armor',at,'+'+(c.armor-old.armor));
            effects.push(animateElement(number,[{transform:'translate(-50%,0)',opacity:1},{transform:'translate(-50%,-70px)',opacity:0}],{duration:600}).then(()=>number?.remove()));
        }
    }
    if(data.observation.turn!==before.observation.turn){
        const banner=effectNode('fx-turn-banner',{x:0,y:0},data.observation.active_player===data.seat?'你的回合':'对手回合');
        effects.push(animateElement(banner,[{opacity:0,transform:'translate(-50%,-50%) scale(.8)'},{opacity:1,transform:'translate(-50%,-50%) scale(1)',offset:.25},{opacity:1,offset:.7},{opacity:0,transform:'translate(-50%,-50%) scale(1.05)'}],{duration:680}).then(()=>banner?.remove()));
    }
    await Promise.all(effects);
}
