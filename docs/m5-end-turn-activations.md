# M5-13d-02l-05c：主动与异阶段结束能力公共入口

原随从残骸门禁在执行时重核实际来源、空位/复生/召唤对象，再沿原完整支付分支；原目标伤害与三个真实选项保持引用和信息边界，见[残骸触发与选择契约](m3-corpse-trigger-choices.md)。

2026-10-03。本增量已通过内部验收。运行时 `prototype-v101` / `core-effects-v101`、snapshot schema98；`representative-m5-v61`、302条完整原始代表记录、303定义、14个choice-only保持，无新增真实卡。观察51、命令7、外层replay1保持。R-146是内部候选契约，依赖已有[R-143主体](m5-end-turns.md)和[R-144次数计划](m5-end-turn-repeats.md)，尚未国服校准。

## 调用、主体与来源分别建模

`TriggerEndTurnEffects(player_id, request, source_id=None, cause=None)`是可信行为返回的公共效果。它执行声明为 `EndTurnSpec` 的结束能力，不发出 `turn_ended`，不调用普通结束监听，不推动owner时钟、刷新资源、休眠唤醒或抽取下一回合牌。玩家命令保持现有出牌、使用技能、结束回合和选择接口，不能直接提交这个效果。省略source时使用明确player_id的英雄作为issuer。

`EndTurnSelector(mode, player_ids, carrier_kinds, entity_ids=(), player_effect_ids=())`选择物理主体；`EndTurnRequest(selector, profile_id='end_turn.effect')`选择资格政策。支持单方或双方，载体为 `minion`、`weapon`、`hero_power`、`location`、`player_effect`。休眠随从仅接受其活跃休眠能力；普通随从能力、有限次能力、被动技能及玩家效果按各自现有生命周期读取。没有显式结束声明的普通 `turn_ended` 监听不会因为同事件名成为主体。秘密、任务和牌库/手牌不属于这些载体。

owner模式覆盖指定玩家的指定载体；selected模式取指定实体／玩家效果ID与玩家／载体范围的交集，允许空集。选择ID是集合，执行顺序仍按原监听接受顺序：当前行动玩家先，其后入场/实例顺序；不能用调用者传入ID的排列重排。未知实体ID与未分配的玩家效果ID明确拒绝；已存在但不在适用区的实体或已移除的旧玩家实例可以产生空集。这不等于正式随机生成候选政策。

调用issuer、主体所属玩家/捕获控制者、附件授予来源、玩家实例来源及重复次数来源均分别冻结。调用player_id不会改写主体owner、伤害来源或主体回调的player_id。主动选择敌方主体也使用敌方适用的重复来源，不能借用调用者光环。

| 物理载体 | 本批接受的能力 | 首次执行检查 |
| --- | --- | --- |
| 普通随从 | 活跃普通结束trigger或有限次结束能力 | 普通保留接受；有限次复核相同活体附件并消费 |
| 休眠随从 | 活跃dormant_trigger | 保留接受，普通trigger及唤醒倒数不纳入 |
| 已装备武器 | 活跃普通结束trigger或有限次结束能力 | 普通保留接受；有限次复核存活耐久与相同附件 |
| 地标 | 活跃普通结束trigger | 保留接受；不使用地标、不消费耐久或改变冷却 |
| 在位英雄技能 | 活跃普通结束trigger | 复核相同安装实体/能力；不执行手动使用 |
| 玩家效果实例 | 注册规格中的显式结束trigger | 冻结所属玩家、完整实例及声明索引，不额外倒数 |

有限次静态定义沿用现有类型限制，仅允许随从／武器；地标、技能和玩家效果不能伪造有限次卡面。此矩阵不改变既有动态能力安装门槛，也不表示所有正式来源都已有适配。

## 资格profile与真实cause

`EndTurnActivationProfile(id, kind='effect', turn_scope='ignore', target_policy='none', cause_events=())`由注册表显式登记，进入注册表指纹。对局建立后随注册表冻结。kind可为effect或phase；turn_scope可为ignore或respect；target_policy可为none或cause。无法查询的profile、无效声明或不匹配的cause均明确拒绝。

预装 `end_turn.effect` 忽略自然turn_scope，cause可为空，target为None；预装 `end_turn.phase` 同样忽略自然turn_scope，但要求真实 `turn_started`。自定义respect profile依据真实cause.player_id检查主体 `EndTurnSpec.turn_scope`；必须有明确玩家的真实事件。ignore只略过自然控制者/对手回合范围，仍检查主体条件及有限次条件，结果必须为严格bool。条件在接受时基于原窗口判断，不在每次重复开始时重新筛选。

cause必须是本对局实际日志中的完整Event，不能改写kind/sequence/player来合成事件。非空cause_events对effect和phase均是硬约束。phase还要求cause属于当前真实回合的事件前缀，旧回合的开始不能触发当前phase。回调收到真实cause或None，绝不构造伪结束事件；target_policy=cause才把真实事件目标传给主体，否则target为None。具体真实producer应注册自己的profile，不能将默认profile自行解释为所有正式卡牌资格政策。

## 接受、守卫、重复与嵌套

自然、effect和phase共享完整主体/次数计划与独立捕获/执行历史。`EndTurnActivation`保存kind、完整request、issuer身份/卡面/玩家/区域修订/入场顺序、action、实际event_cursor以及父关系。`EndTurnBatch.event`在effect时可为None，在natural/phase时保存完整真实事件。自然批次仍与每个真实结束事件一一对应；同回合多个主动根可以具有相同action或cause。

一次调用先冻结全部主体和各自完整max来源计划，然后逐主体在首次及额外位置执行。首次普通/休眠/玩家效果使用原接受窗口；首次有限次使用一次真实消费后的旧窗口；首次英雄技能使用原安装身份守卫；额外开始时取得最新局面。接受之后，次数来源死亡/移除/转控不重算当前计划，新来源留给下一次接受。固定主动多轮特殊来源的独立轴不在本增量内；连续公共调用是独立接受根，不能用它冒充已冻结的固定多轮政策。

有限次与安装技能的主动守卫使用 `CheckActiveEndTurn`。有限能力须仍是相同捕获附件及相同用途状态，实际消费一次，并保存与真实 `limited_trigger_used` 事件绑定的私有守卫收据；失效、替换、转控或用途已被内层消费时整组skip，不借用新版附件。HP守卫复核相同在位实体/能力，不支付手动费用、不消费手动技能次数。普通、休眠及玩家效果不能伪装成此守卫指令。

HP检查和首次Invoke之间没有合法挂起点，拒绝从Check伪造的首次Invoke快照。有限次消费具有原有检查点，used-event监听可以在首次Invoke之前触发嵌套调用或选择；不能把有限检查一同当作无检查点的诊断控制。Invoke、主体Finish和批次Finish仍不添加游戏事件或玩法检查点。

`parent_id`指向最近正在执行的主体capture.id；`parent_batch_id`指向接受时最内层未结算的批次.id。二者不能互换：原守卫消费反应或自然尾部普通监听可能发生在主体尚未开始/已经完成时，此时只有parent_batch_id；最后额外主体capture.id也可能不同于batch.id。外层A主体运行、内层B刚消费尚未Invoke、B的used-event监听再启动C时，C的主体父关系仍是A，批次父关系则是B；只要求主体父批次属于B的完整祖先链。稳定边界验证完整嵌套链，子批次完成先于父批次，若存在正在运行的父主体，还必须先于该主体Finish。

同有限附件在内外两层分别合法消费时，每次使用均有独立真实收据。恢复时外层剩余用途必须扣除后续相同附件的实际守卫消费，并准确匹配consumed状态；不能把合法内层消费误判为损坏，也不能伪造恢复用途或省略收据。原自然批次中尚未执行的旧有限守卫也不能借用已经被主动内层消费后的新用途窗口。

## 严格恢复与信息边界

完整 `FinishEndTurnBatch` 保存接受前的issuer上下文证明，重算主体全集、资格和全部来源计划，直到本批所有载荷及反应结束。自然批次保留证明到尾部普通监听结束、原时钟继续之前。最后额外或嵌套选择仍须保留完整证明；同步裁剪待执行指令/历史/live计划不能绕过原接受全集。

schema98要求Batch.activation、Selector/Request/Activation全部字段（包括nullable父ID）在wire中显式存在，不能用默认值补损坏存档。state与frame使用相同Event对象编码，cause数据可包含已有字典/列表，不强迫转成可哈希tuple。旧schema1～97明确拒绝，外层replay1不意味着旧origin兼容。候选profile变化会改变注册表指纹；回放、恢复还需匹配规则和机制版本。

稳定恢复核对所有真实自然事件、实际cause前缀、批次嵌套、完整位置、待执行控制、运行Finish和逐项真实守卫收据。终局中断只影响未完成位置；工程预算在分配完整计划前检查，结算错误沿用事务回滚，选择不能重置已消耗预算。关闭历史只提供结构一致性，不认证所有过去证据被一同重写的存档；本项目没有存档签名机制。

全知接受状态、issuer/cause见证、私有收据和主体历史只供可信宿主使用，不进入玩家观察；`activated_end_turns`仍是宿主查询。选择继续通过所属玩家的现有PlayerPort处理，观察版本保持51。动态能力、主体和来源生命周期仍由公共内核负责，卡牌不直接改这些状态。

## 来源依据、实际验证与下一项

[1159条完整raw前置审计](../outputs/v105-end-turn-activation-pre-audit.json)及[独立重现](../outputs/v105-root-audit-check.json)保留原历史观察：21条精确引用分类、147项当时依赖指纹。审计生成于上一批仍在验证时，不能重新生成指纹来伪装为当前实现证据。广义文本扫描有未审查记录，不是完整语义范围或正式池分母。

CATA_472灵感之槌是后续主动producer候选；本批不接入该卡，也不把随机单个友方随从profile当作公共入口的全部范围。此次精确分类未建立非战棋异阶段producer证据，本批以合成真实turn_started场景验证phase；真实构筑producer和国服窗口仍保留缺口，战棋来源不混入构筑。

专项源码为[主动与异阶段测试](../tests/test_m5_end_turn_activations.py)，原生示例为[公共入口组合场景](../examples/end_turn_activations.py)。2026-10-03，91专项、1094相关回归、5468全量及89示例内部通过；专项61.959秒、相关回归506.731秒、全量1813.979秒，M5共4220、M4共503。旧摘要共同动作/事件/物理结果字段不变；原生独立扩展Registry恢复/回放及其模块CLI通过，均为内部证据。 见[验收摘要](../outputs/v105-verification.json)、[全量](../outputs/v105-full-tests.txt)、[示例比较](../outputs/v105-example-count-check.json)。

下一项 **M5-13d-02l-05d：主动producer主体资格/选择政策与必要CATA_472代表**。先明确随机友方随从及结束能力的候选口径与来源身份，再组合此入口；固定多轮、条件/种族/特殊来源、TIME_064混合继续保留M5。L05尚未整族完成，M0正式池、M6国服校准、M7批量接卡均未完成，长期目标保持active。

[05d只读预审](../outputs/v106-end-turn-producer-pre-audit.json)与[独立复核](../outputs/v106-root-audit-check.json)保留47条完整raw及30项本批验证期间的依赖观察，不刷新历史指纹。当前 `selected_subjects` 包含实际条件判断，不能充当纯结构性随机候选查询；是否有结束能力、当前条件是否成立、随机选中哪个载体与选后如何激活需要分别建模。休眠、耗尽及多能力载体政策尚未注册，完整producer来源图与国服口径尚未证明。

首轮87专项中的两个失败和一个错误来自夹具：重复两次移除技能、误禁已有公开event_cursor，以及最后期限边界本来只发expired而非ticked。修正这些夹具并补充守卫类型、耗尽状态及三层父关系恢复反例后，91专项实际通过（61.959秒）；[首轮日志](../outputs/v105-end-turn-activation-tests-initial.txt)保留。专项通过不代替全量终态。

原生摘要 `d1060721d94f8b3255899106ac53bfdfe85f63f608466a19099e0e3dd66e1b41`，10动作/148事件，独立扩展Registry恢复与回放内部通过；其模块命令 `python -m examples.end_turn_activations --replay outputs/v105-end-turn-activations-replay.json` 的[CLI日志](../outputs/v105-end-turn-activations-cli.txt)通过。该CLI显式使用示例自己的注册表，不表示hs_sim默认代表包可以自动选择这些合成profile。


## 当前英雄载体扩展

以上原批次数字与五类载体描述保留为历史。本轮公共权限增加当前英雄的普通分类结束能力与keyword=None有限触发；显式owner/selected及随机候选可选择 `hero`，原调用者范围不自动扩大。Hero的法术迸发/暴怒仍拒绝，重复来源仍只能是随从。消费前实际来源守卫、消费后接受主体、替换继承及原自然时钟保持各自既有政策，详见[英雄公共契约](m5-hero-classified-triggers.md)。当前prototype-v145/core-effects-v145、schema140新增玩家抉择政策/原接受字段，英雄权限扩展本身沿原布局；实际范围、证据及下一项只见两份最新台账。
