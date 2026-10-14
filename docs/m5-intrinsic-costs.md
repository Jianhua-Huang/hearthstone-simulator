# 条件式固有费用与完整手牌付款证明

本文保留 `prototype-v113` / `core-effects-v113`、snapshot schema110 的历史开发 API；当前有限场面数量阶段见文末及[费用基础契约](m3-board-minion-costs.md)。内部验收状态、实际执行结果和下一项以[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)为准；开发接口不代表最新正式卡池或国服时序已通过校准。

## 声明及适用对象

`CardDefinition.intrinsic_costs` 是有序不可变 `tuple[IntrinsicCostSpec,...]`，默认 `()`。本次只有 `previous_owner_turn_type` 条件，历史 profile固定 `owner-turn.latest-closed-v1`，费用 profile固定 `cost.intrinsic.before-local-v1`；未知 condition/profile 明确拒绝。

非空声明要求可从手牌打出的 MINION 或 SPELL。随从根据定义中的明确种族与最近已关闭自身回合提交的随从种族匹配，法术根据明确单学派匹配；完整 frozen true/false 行使用 [自身回合历史](m5-owner-turn-history.md) 的公共查询。武器/英雄/地标不因拥有完整付款证明而自动获得这个 type 条件声明能力。无声明的旧定义仍有明确空阶段，不触发种族查询，不把未知元信息默认为已知空。

每条声明可设 `set_to`、`delta`、`minimum`。成立时，若该条有 `set_to`，直接取 `max(set_to, minimum)`，不叠加该条 `delta`；否则应用 `delta`，负 `delta` 的下限为 `min(进入该条的金额, minimum)`，不会抬高已经更低的金额，非负 `delta` 则按该 `minimum` 钳制。不成立保存 unchanged 操作事实。独立多条声明按定义元组顺序执行，复用同一完整原历史匹配事实；不重复消费来源。

```python
from hs_sim.engine import CardDefinition, CardType, IntrinsicCostSpec
from hs_sim.engine.model import CardClass, CardMetadata

definition = CardDefinition(
    'synthetic.history-dragon', '历史条件示例', CardType.MINION,
    cost=5, attack=3, health=3,
    metadata=CardMetadata(False, (CardClass.MAGE,), None, tribes=('dragon',)),
    intrinsic_costs=(IntrinsicCostSpec(delta=-3),),
)
```

这是合成定义片段，不是新增真实卡。真正 Registry 仍需显式注册全部引用定义/行为。

## 报价阶段

| 输入 | 顺序 |
| --- | --- |
| 物理手牌 | 原当前 base → 定义顺序 intrinsic → 原本地附魔顺序 → 外部 modifier/aura 全局ID顺序 → 最终手牌下限 |
| 生成报价 | 印刷 base → 相同 intrinsic → initial CostSpec → 外部层 → 调用方最低费用 |

印刷费用独立保存，实体 base与当前卡面分别明确；intrinsic 不写 Entity 派生缓存，不安装附件、不分配ID、不消费有限用途或RNG。生成报价使用 `GeneratedCostQuoteInput` / `GeneratedCostQuoteFact` 保存假设对象与完整阶段，不创建假物理实体。

旧费用条件的 `local` 在此阶段之后读取本地结果，`printed`仍为印刷，`submitted_quote`仍为原付款报价，`window_quote`仍为原接受窗口指定profile报价。actual_payment 不支持，报价不能冒作账户余额差；有限外部用途只在真正付款按既有支付机制消费。

## 冻结事实及原边界

`OwnerTurnQueryBoundaryFact` 保存原 turn/action/status、owner与play完整前缀长度、完整last区间，以及开局阶段和first player。last和选中closed区间的全部 start/publication/end/close/interruption动作都不能晚于原 boundary.action。开局没有实际区间时明确保持空，不补造场景区间。

`IntrinsicCostStageFact` 保存原payer/card/kind、printed/base/result、声明、完整匹配事实和逐操作 before/after。`CostQuoteFact.intrinsic`与`SpellCostFacts.intrinsic`始终必需，包括空规则。 frozen validator从完整 pinned Registry声明、全部true/false行及有序操作重算；unknown完整遍历后再聚合，金额0或前面已true不短路。原prepay/各重复接受窗口还绑定完整history前缀与真实source，不能用今日已增长的历史重判旧费用。

## 非 Spell 原付款义务

`PaidHandCostProof`用于MINION/WEAPON/HERO/LOCATION的真实手牌成功提交，与既有Spell严格proof共享完整纯付款投影。冻结submitted receipt在所有Combo/BC原快照之前安装。current_hand receipt必须同时绑定本次实际accepted card_id与完全相同turn/action；不能因新的paid close分支使原守卫不可达。rewind_root保留真正原报价与可能变化的当前接受卡面，其完整原付款证明另行认证；两种来源不能互换以绕过原窗口。原付款前状态、完整准备根、真实付款后尚未append的submission base进入 `FinishPaidHandAcceptance`；投影完整 append重建准确提交状态，不能凭cost整数或法力差认证。

诊断尾部在物理FinishPlay及其所有card_played反应之后关闭，没有新增玩法事件/checkpoint/预算charge。`completed=True`不等于付款证明已关闭；正常完成的牌仍可在card_played选择中pending。反制/无主体仍提交一次、付款一次；失败动作rollback不留下记录。真正Rewind分别保持原报价来源与实际重试卡面，丢弃尝试随timeline恢复；保留多结果不制造多次付款。

`PaidHandClose`保存真实action/event cursor，`PaidHandInterruption`绑定清队列之前实际game-ended事件。六族原接受证明只允许明确单调progress；不能擦已有close、回填早于原捕获的close，或借根/删尾部缩短原义务。其它卡来源、默认同外部动作多付费根限制与额外/跳过调度没有扩大。

## 每个真实选择的完整原证明

所有默认真实挂起请求都保存 required `PaidHandChoiceBoundaryProof`，包括合法空owed。原Event是在原normalize之后、append/Information/监听之前构造，保存完整原state与有序work；私有 `_paid_hand_choice_boundary`摘要绑定此完整FrameCodec编码，不新增事件或改变时机。

恢复对原request、pending、玩家/source、全部原work和原owed tails进行认证。挂起保存要求current action==request action，真实SelectChoice先验证精确+1再清理；新请求重新捕获。work限定Effect或BehaviorCall。required proof不能用None/空字典/借另一个choice替换，不能同时invent close/delete tail/clear IDs绕过完整原义务；合法completed+pending和同动作真实close继续支持。

## 私有 wire、注册表与玩家接口

schema110保存全部严格typed阶段、原付款/progress和required Frame证明；只接受严格int110，旧1～109及隔离schema拒绝，旧快照需原引擎。外层replay1保持，新origin使用110。没有隐式补空facts或升级存档。

CardDefinition默认新增空intrinsic，以及CostQueryProfile默认新增intrinsic_profile_id='cost.intrinsic.before-local-v1'，都进入完整asdict，因此旧Registry指纹改变；每个Registry还会自动注册repeat.cost.accepted_hand默认profile。必须捕获所有实际完整Registry payload，严格验证旧卡空元组的JSON空数组与profile精确policy后，才可只删除这两个新增叶并重算完整旧指纹。选择私有摘要改变raw events_hash，新增facts和Frame字段改变state_hash。验证要求完整实际payload/原捕获source逐字段重算，不能忽略这些hash。摘要用于内部一致性，不提供未签名存档在协同整体改写后的外部来源认证。

玩家仍用view55/action7和逐座位过滤事件。完整历史、费用操作数、prepay/choice proof及私有摘要不暴露；非行动方自己的合法价格仍可查询，敌方记住的牌身份不携带敌方当前cost。全知快照不能给玩家。

## 内部政策与后续范围

R-159是before-local固有阶段及其冻结证明的内部政策，依赖H1 R-158最近closed自身区间；两者未国服校准。原生合成示例为 `examples/intrinsic_costs.py`，正式实际结果必须以后验收台账为准，不能引用隔离104/8或修订114/独立三方法作正式full。原104源码中两处旧guard回归已由新的隔离修订恢复，旧报告和全部失败保留；正式源码仍须新门禁。

actual_payment条件轴、自动CAST费用匹配、额外/跳过回合、其他重复族费用匹配、其它历史条件、动态主体/固定多轮producer以及M0/M6/M7仍保留。没有新增真实卡，完整模拟器目标未完成。

## v147历史分支价格阶段

v147历史prototype-v147/core-effects-v147/schema142，在相同intrinsic之后、本地附魔之前增加[所选分支价格操作](m5-choose-branch-costs.md)。印刷/base/原历史条件保持；物理和生成输入明确branch_id/quote_basis。unselected基准不给未激活卡面猜分支，真正手牌与技能付款必须activation，并绑定完整原证明。上方schema110原批格式保留为历史。

## B23有限场面数量阶段

B23首次prototype-v182/core-effects-v176/schema171拒旧1～170，观察74/命令11/replay1保持。CardDefinition.board_minion_cost只接受BoardMinionCostSpec的friendly/all普通BOARD随从每个减一费、最低零；capture_intrinsic_stage先在base上应用纯数量操作数，再沿原定义顺序执行历史条件，本地/外部层继续原顺序。IntrinsicCostStageFact必须保存显式board_minions（无声明为None），非空包含双方完整目录、原分配上界、数量及before/after；历史验证使用原保存数量，完整原接受证明从付款前实际局面核对。物理来源与原手牌尚未入场的身份分别校验。所有定义新增默认None叶，因此普通注册表指纹也变化；没有Entity费用缓存、玩法事件或新外部动作。具体接口、生成报价、必要生命周期和内部政策见[场面费用契约](m3-board-minion-costs.md)。

上述v147分支专用扩展仅保留历史说明；用户要求撤下的抉择专用组合已实际移除，见[反向审计](mechanism-combination-audit.md)及[移除证据](../outputs/remove-speculative-choose-combinations-20261009/verification.json)。它不是当前基础API或开发前置。当前只逐项补真实基础输入，不扩展任意公式/组合；费用顺序、驻留政策、特殊来源与国服校准仍按主台账开放。

## 当前有限手牌数量阶段

当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。CardDefinition.hand_count_cost接受friendly_other/enemy每张减一费、最低零的HandCountCostSpec；物理quote_input传source_id，生成入口保留None，数量在base后及原条件/本地/外部前。IntrinsicCostStageFact必须保存显式hand_cards（无声明为None），冻结双方完整物理目录、原分配上界、物理/生成来源、数量/金额；物理和生成不能交换来源，真实手牌收据要求来源在原本人HAND，即便省略来源后数量相同也拒绝。原付款证明重新查询实际原状态，紧凑历史使用保存数量；后续合法手牌变化不重新扣款。默认hand_count_cost=None改变普通注册表指纹，无新Entity/Player字段或动作。范围、额外生成假设、隐藏信息和未校准政策见[手牌数量基础契约](m3-hand-count-costs.md)。

## 当前有限英雄缺口阶段

独立英雄缺失生命费用由hero_missing_health_costs.py提供当前payer英雄max_health-health每点减一费、最低零的纯操作数。复用原生命/上限政策及英雄替换，物理与生成报价一致；HeroMissingHealthCostFact冻结原英雄身份、归属、分配上界、健康数量与金额。原付款/恢复/回放/玩家价格共享，紧凑历史绑定保留原英雄身份并按旧数量重算，不从今天的健康重新定价。默认hero_missing_health_cost=None和显式hero_missing_health改变指纹/保存格式，无新Entity/Player字段、事件或动作。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-hero-missing-health-costs.md)，费用顺序/特殊复制/精确CN待校准。

## 当前有限本人本局施法数量阶段

独立本人本局施法数量费用由player_spell_count_costs.py复用原cast_history，按实际payer的原hand已接受主体根每次减一费、最低零。反制及repeat/effect/draw/history不加本人原根数量，获取前历史计入；精确未结窗和重复归属待CN校准。PlayerSpellCountCostFact冻结完整有序原施法行、游标、分配上界及数量金额，进入原固有报价/付款/恢复/回放/玩家价格；紧凑历史允许原自动主体合法推进，保持原身份和冻结数量，不以今天历史重新定价。默认player_spell_count_cost=None与显式player_spells改变指纹/保存格式，无新Entity/Player字段、事件或动作。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-player-spell-count-costs.md)，层顺序/特殊复制与CN仍开放。

## 当前有限本人技能次数阶段

独立本人本局技能次数费用由player_hero_power_count_costs.py复用原hero_power_history，按实际payer原manual接受根每次减一费、最低零。获取前/此前回合/旧技能使用保留，effect及自动失败不加手动量，完成/中断可正常推进。原完整行/游标/支付身份/分配上界和数量冻结进入player_hero_powers，共享报价/付款/恢复/回放/玩家价格，不按今天历史重新定价。默认player_hero_power_count_cost=None及显式player_hero_powers改变指纹/保存格式，无新Entity/Player字段、事件或动作。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-player-hero-power-count-costs.md)，未结窗/效果归属/层顺序/特殊复制/CN仍开放。

当前共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[本局实际法术法力费用](m3-player-spell-mana-costs.md)复用原物理出牌/付款，不改变本契约自身资格；精确CN仍待校准。

独立死亡随从次数费用由minion_death_costs.py复用完整原DeathRecord及DeathQuery，仅友方本局/双方本回合两个profile，每原死亡记录减一费、最低零。controller取死亡时归属；武器/地标销毁保留完整前缀但不计随从量，不按实体或卡牌ID去重。完整原turn/记录/selected/游标/分配上界和数量冻结进入minion_deaths，原付款/恢复/回放/玩家报价共享，后来死亡或回合推进不重价；序列化复用原_death_from_dict，不另造死亡结算/记录器。默认minion_death_cost=None及显式minion_deaths改变指纹/保存格式，无新Entity/Player字段、事件或动作。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-minion-death-costs.md)，精确死亡可见窗/层顺序/特殊复制及CN仍开放。

独立本局实际过载水晶量由overload_history.py在原overload_added发布处保存不可变OverloadRecord，只累加实际正量；初始余额/转锁/解锁/0量不增加，纯overloaded_crystals查询不改变账户。原玩家/owner回合/动作及mana_changed事件对和完整目录校验，玩家与pending两端严格int，拒绝数值相等的布尔/浮点冒充。player_overload_costs.py仅普通随从的cost.player-overload-v1，以实际payer本局水晶量减费、最低零；完整原记录/窗口/游标/分配与数量冻结进入player_overload，共享报价/付款/恢复/回放/玩家价格，后来真实过载不改原付款。GameState仅新增overload_history及next_overload_id两个字段；没有Player累计缓存、第二套法力执行器、新Entity/Player字段、玩法事件或外部动作。默认player_overload_cost=None及显式原量叶改变指纹/保存格式。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-player-overload-costs.md)，精确发布窗/费用层顺序/特殊来源与CN仍开放。

独立本局原职业出牌数量由play_history.py的played_cards单一card_class筛选和纯matches_played_class复用原完整FrozenPlayedFaceFact，用既有PoolQuery/matches_metadata明确排除中立，不以当前英雄或变形重判。player_played_class_costs.py仅单一可玩印刷职业的普通随从减费、最低零，完整原卡面/获取/窗口/有序游标/物理上界与selected冻结到player_played_class，原付款/恢复/replay/玩家价格共享，后来出牌不重价。原反制/未结手牌根计入本地profile，自动施法/召唤/技能不添根，新付款前自身不计入；精确CN时点/退款待校准。没有新GameState/Entity/Player字段、事件、动作、出牌台账或递归原报价；默认player_played_class_cost=None及显式数量叶改变指纹/保存格式。当前prototype-v190/core-effects-v184/schema179拒旧1～178，观察74/命令11/replay1保持。见[基础契约](m3-player-played-class-costs.md)，费用层顺序/特殊来源/正式卡面与CN仍开放。
