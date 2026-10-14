# M5-13d-02l-05d：结束能力候选、随机选择与必要主动来源

2026-10-03。本增量已通过内部验收。运行时为 `prototype-v102` / `core-effects-v102`、snapshot schema99；实验代表包为 `representative-m5-v62`，303条完整原始记录、304定义、14个choice-only。观察51、命令7、外层replay1保持。R-147是内部候选契约，依赖[R-146主动入口](m5-end-turn-activations.md)、[R-143结束主体](m5-end-turns.md)与[R-144重复计划](m5-end-turn-repeats.md)，尚未国服校准。

本批先实现可复用的结构性候选查询和随机单载体producer，再接入必要代表CATA_472。候选查询、选择来源和实际能力资格分别建模；灵感之槌的友方随从profile不能代替五类载体公共范围。实现、内部测试、完整来源调查与国服规则校准分别登记。

## 结构性候选与实际资格

`end_turn_carriers(state, registry, selector, profile_id='end_turn.candidates')`是可信宿主的纯查询。它返回符合物理范围和结构性profile的 `EndTurnCarrier`，不调用结束能力条件或有限次条件，不消费用途、不抽随机数，也不修改状态。普通 `turn_ended` 监听、倒数时钟、唤醒动作和重复次数光环不能仅因事件名相同而成为结束能力。

复用 `EndTurnSelector` 的owner/selected范围，支持 `minion`、`weapon`、`hero_power`、`location`、`player_effect` 五类载体，可指定单方或双方。selected实体ID和玩家实例ID分别与玩家及载体范围取交集；空集合法，未知实体与尚未分配的玩家实例ID明确拒绝。已移出适用区的实体或已移除的旧实例可以返回空集。

查询顺序沿用原监听顺序：当前行动玩家在前，其后按入场/实例顺序及来源实体排序。selected参数中的ID排列不能重排候选。每个物理载体只占一个候选位置；多个相同或不同附件、多个结束主体和重复次数均不增加其抽取权重。

`EndTurnCandidateProfile(id, presence='has_body', basis='active', dormant='exclude', live_only=True, consumed='exclude')`由注册表显式登记，进入注册表指纹，并在对局绑定后冻结。未知profile或非法组合明确拒绝。预装profile为 `end_turn.candidates`，使用上述默认值。

| 字段 | 值与行为 |
| --- | --- |
| presence | `any`接收范围内载体；`has_body`要求有结构性结束声明；`lacks_body`要求没有结构性结束声明 |
| basis | `active`读取生命周期活跃且未消费的结束附件；`current`读取实体仍保存的分类附件；`printed`读取当前物理卡面定义中的普通、休眠和有限次结束声明 |
| dormant | `exclude`排除休眠实体；`include`允许两类实体；`only`仅保留休眠实体，并排除全部玩家实例 |
| live_only | 严格bool。为true时排除doomed实体、生命不大于零的随从、耐久不大于零的武器/地标；休眠由独立dormant字段决定 |
| consumed | `exclude`忽略已消费附件；`include`允许current读取仍保存的已消费附件。active只允许exclude；printed要求include，因为印刷定义不读取实际用途状态 |

current和printed只影响候选存在性，不授予实际执行资格。例如休眠期间仍存的普通结束附件可以满足显式current/休眠profile；后续实际接受仍只使用现有活跃能力。printed读取当前物理卡面，不自动借用磁力组件或附件授予者的印刷定义。

玩家效果的载体是独立 `PlayerEffect` 实例。其结构性声明在所有basis下均来自注册规格的triggers，物理来源的当前位置、类型、生命和休眠不决定实例是否存在。live_only不借用来源实体的生命或耐久，dormant=only排除玩家实例。同一来源的两个实例分别具有一个权重；来源为MINION的实例也属于player_effect，不能进入仅minion范围。

## 一次随机选择与完整接受

`EndTurnProducerRequest(selector, candidate_profile_id='end_turn.candidates', activation_profile_id='end_turn.effect')`分别保存候选范围、结构性政策和既有实际激活政策。`TriggerRandomEndTurnEffects(player_id, request, source_id=None, cause=None)`是可信行为返回的公共效果。它没有新的玩家命令，也没有固定多轮times参数；source省略时沿用明确player_id的英雄issuer。

处理器实际运行时，先在当前局面查询完整候选，再对非空有序tuple调用一次共享 `random.Random.choice`。只有一个候选时也调用choice。空池不调用随机数，选择结果为None。所选载体随后转为精确selected请求：实体与玩家实例ID分别保存，保留原玩家范围、载体范围及activation_profile_id，不能夹带第二载体或换用另一资格profile。

选择和原入口的全部主体/计划接受在同一处理器窗口完成。实现直接复用原接受内部函数，不先返回第二个 `TriggerEndTurnEffects` 排队；否则原解释器会在两个Effect之间执行检查点、死亡和监听，改变所选载体及接受局面。producer只增加全知历史见证，不发出 `random_choice`、跳过事件或伪 `turn_ended`。主体Invoke/Finish继续沿用原诊断控制，不新增玩法检查点。

候选存在性不执行能力条件，因此两个结构性载体中即使一个条件为false，仍各占一个候选位置。选到false载体时，实际接受可能为零主体；这仍是一次非空池抽取。真正空池则没有抽取。非bool条件只在实际能力接受时明确报错，不用其错误或false结果预先缩小随机池。

实际主体资格继续使用R-146的activation profile、严格bool条件、真实cause与target政策。选择一个载体后接受其全部合格分类主体，保持原能力/实例顺序及逐主体max计划；不是随机选择其中一个附件。普通、休眠与玩家效果保留原接受窗口，有限次与在位技能沿用各自原守卫及真实收据，额外执行读取最新局面。所选来源离场或被替换不重新抽取；守卫失败仍整组skip。

effect/phase源类型仍由已登记的activation profile决定。phase必须满足真实当前回合cause要求，非空cause_events是硬约束；本producer不会制造异阶段或自然结束事件。主动调用不推进owner倒数、临时mana、休眠、资源刷新或下一回合抽牌。

## 选择身份、RNG与挂起证明

`EndTurnCarrier(kind, source_id, player_id, card_id, entered_order, zone_epoch, player_effect=None)`冻结候选的载体类型、捕获所属玩家、卡面和物理身份。实体key为 `('entity', source_id)`，玩家实例key为 `('player_effect', instance.id)`；两种ID空间的相同数值不会合并。玩家实例保存完整PlayerEffect，与source/card/entered_order一致。候选载体身份与后续 `EndTurnSubject` 能力/声明身份分别保存。

`EndTurnSelection(request, candidates, selected, rng_before, rng_after)`保存原producer请求、有序完整候选、完整所选载体及共享RNG前后状态。非空池必须选中池内完整对象；空池必须selected=None且前后RNG相等。`EndTurnActivation`末尾保存selection及独立producer_mode：direct要求selection为空，random_one要求完整selection，自然批次只能direct。普通直接调用保留direct，producer同窗构造random_one；不能仅删除所有副本中的nullable选择字段就降级为旧直接入口。

RNG见证使用Python MT19937标准v3状态：不可变三元tuple、624个严格整数状态字及一个0～624索引、None或有限精确float高斯缓存。bool不能冒充整数，异常版本、长度、字值、索引或非有限缓存均拒绝。恢复在独立Random副本上复演一次choice，验证selected和after；空池不执行draw。验证不会消耗或改写宿主RNG。

不能要求挂起时的全局RNG等于这次rng_after：所选主体、有限次used-event监听、嵌套调用和其他后续工作可以合法再次随机。该见证校验一次选择的局部关系；原 `RuleContext.state` 不保存RNG，不能单独认证过去的共享RNG前态。关闭历史和协调改写的全部过去证据仍是结构一致性范围，本项目没有存档签名机制。

原 `FinishEndTurnBatch` 继续保存接受前的issuer上下文。每次实际完成及稳定waiting恢复时，从其state复算原producer完整候选池和精确resolved请求，再复算所选载体全部实际主体与max来源计划，并校验局部RNG关系。证明保持到最后额外主体和原反应结束；原双父身份继续覆盖普通尾部、有限次消费监听及三层嵌套。当前live载体可以已离场、变卡面、转控或实例到期，不能用当前池替换原接受池。

终局沿用原未完成位置中断政策；真实守卫收据、有限次递归用途和首次HP不可达Invoke门禁保持。工程预算在原完整计划展开中检查，错误沿用事务回滚；未提交操作也回滚共享RNG，选择恢复不重置预算。新的候选/选择/RNG及原接受全知状态不进入玩家观察，观察51保持。

schema99要求Activation的selection及producer_mode字段显式存在，即使selection值为null；新Request/Carrier/Selection的全部字段、候选数组和完整RNG状态也必须存在。旧schema1～98明确拒绝，不以constructor便利默认补旧wire。state使用标准JSON数组保存RNG；frame仅在typed EndTurnSelection的两个RNG字段接受专用 `end_turn_rng` 对象。普通frame primitive仍不接受float，高斯缓存的兼容不扩展到其他载荷字段。

## 必要代表与独立重复轴

仅新增独立CATA_472（灵感之槌），本地完整raw的dbf_id为123106、费用2、攻击2、WEAPON原始HEALTH为2；沿现有武器适配约定把该字段作为耐久，不改写原始记录。canonical SHA-256为 `43df6f13cb9f2d5cc6c02d39906c1c93e44df959f484bbc872b8314a4163f2e9`。其印刷亡语文字只确定随机友方随从与结束能力调用，不能据此确认所有候选和官方窗口。

必要代表采用显式本地 `CATA_472.end_turn_candidates` profile：active、has_body、排休眠、要求live、排consumed；request范围仅捕获producer所属玩家的minion，实际激活复用end_turn.effect。武器死亡/亡语的issuer和所属玩家来自原捕获上下文，不能改用当前行动玩家。选中随从后接受其全部合格结束主体；false条件、耗尽、印刷/授予、休眠及多附件的官方口径仍未国服校准。

外层每次实际亡语执行分别接受一次producer、查询当前池并重新抽取；已接受的内层结束主体额外次数共享原选择和原计划，不重抽。亡语固定次数/来源重复与内层结束重复保持独立轴。ICC_901与CATA_480只作为既有内层max来源组合，玩家期限仍沿原自然owner时钟；本批不修改其R-145 duration3本地政策。

303条完整support记录与304定义的增量只有CATA_472一条，旧302完整行保持。没有自动加入CORE、附魔、战棋倍数或TIME_064混合；正式卡池合法性、隐藏component图和完整producer范围仍未证明。

## 历史证据、验证与保留范围

[v106只读前审](../outputs/v106-end-turn-producer-pre-audit.json)及[独立复核](../outputs/v106-root-audit-check.json)保留47条完整raw与30项当时依赖观察。前审SHA-256为 `f99826601007529eeab6be88a87ec7f9cf1a870513401d2677cfbd95950212d8`，其v105-stage仍是历史validation_in_progress；不因v105后来闭合而重写，不要求当时依赖与本轮最新文件相等。冻结原始36022记录、既有历史审计和M0 baseline_*继续保持。

实现接入点为[候选与producer模块](../hs_sim/engine/end_turn_producers.py)、[结束接受/完整完成证明](../hs_sim/engine/end_turns.py)、[公共类型](../hs_sim/engine/model.py)、[注册表](../hs_sim/engine/registry.py)、[严格state解析](../hs_sim/engine/serialization.py)与[挂起codec](../hs_sim/engine/continuations.py)。专项为[结束producer测试](../tests/test_m5_end_turn_producers.py)。终态测试、全量、示例和原生CLI的实际证据已登记于本文末尾；本契约不把烟测、准备脚本或预期数量写成整批通过。

R-147为本地内部profile，历史官方修复仅提供调查动机，不能证明国服部署、精确随机窗口或完整合并政策。本批不增加固定多轮主动轴，不宣称真实非战棋phase producer范围完整。固定多轮特殊来源、条件/种族来源及TIME_064混合继续保留M5，后续增量按项目状态和机制清单核定；L05、M0正式池、M6国服校准及M7批量接卡均未完成，长期目标保持active。

实际终态：81专项、1316相关回归、5549全量及90示例内部通过；专项23.619秒、相关588.131秒、全量1883.387秒。原生8动作/53事件/3随机根/4位置/4选择，真实Maul外层两次独立抽选；全部waiting恢复、回放及模块CLI通过，owner时钟[3,3]。旧86示例摘要共同行为字段保持；仅内部证据，R-147未CN校准。

[专项](../outputs/v106-end-turn-producer-tests.txt)、[相关回归](../outputs/v106-end-turn-producer-regression.txt)、[全量](../outputs/v106-full-tests.txt)、[验收摘要](../outputs/v106-verification.json)。

首轮77专项中的11个错误来自重复注册到已冻结Registry、误用玩家效果删除参数及非有限JSON夹具；修正后81专项实际通过。首轮日志[保持](../outputs/v106-end-turn-producer-tests-initial.txt)，未覆盖失败记录。


## 当前英雄载体扩展

以上原批次数字与五类载体描述保留为历史。本轮公共权限增加当前英雄的普通分类结束能力与keyword=None有限触发；显式owner/selected及随机候选可选择 `hero`，原调用者范围不自动扩大。Hero的法术迸发/暴怒仍拒绝，重复来源仍只能是随从。消费前实际来源守卫、消费后接受主体、替换继承及原自然时钟保持各自既有政策，详见[英雄公共契约](m5-hero-classified-triggers.md)。当前prototype-v145/core-effects-v145、schema140新增玩家抉择政策/原接受字段，英雄权限扩展本身沿原布局；实际范围、证据及下一项只见两份最新台账。
