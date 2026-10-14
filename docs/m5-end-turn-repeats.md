# M5-13d-02l-05a：自然结束重复公共机制

2026-10-03。本增量已通过内部验收。本增量运行版本为 `prototype-v100` / `core-effects-v100`、snapshot schema97、`representative-m5-v60`；观察51、命令7、外层replay1保持。300条原始代表记录、301定义、14个choice-only保持，没有新增真实卡。R-144是内部次数、执行窗口与期限政策，尚未国服校准。

## 来源与主体范围

本增量扩展[自然结束主体](m5-end-turns.md)，只重复已经显式接受的自然结束能力。普通 `turn_ended` 监听、倒数/到期、进度、休眠唤醒、临时法力、刷新/过载、解冻及下一回合流程不成为重复主体。自然结束事件仍只发出一次。

`EndTurnRepeatSpec(repetitions=2, scope='all'|'minion')`是设定次数的公共声明，次数必须为严格整数且至少2，不能接受bool。场上来源使用活跃、存活、由主体捕获控制者控制的随从及其 `end_turn_repeat` 能力；公共 `GrantEndTurnRepeatAura` 安装独立附件。玩家来源使用所属玩家的 `PlayerEffectSpec.end_turn_repeats`，支持持久和有期限实例。来源声明本身不成为自然结束主体。

每个主体独立冻结适用来源与次数。`all`匹配该玩家的显式自然主体，`minion`匹配物理随从载体上的主体；玩家效果即使源自随从，也不因此成为随从主体。物理载体、附件来源与玩家效果来源卡分别保存，不能通过同名或行为ID合并。实体主体使用捕获控制者，玩家效果主体使用实例所属玩家；不能总用结束回合的玩家。

`EndTurnRepeatContributor`冻结场上载体、完整能力及规格，或所属玩家、完整玩家实例、声明索引及规格。场上键为 `(carrier_id, ability.id)`，玩家键为 `(owner, instance.id, spec_index)`。同载体多个声明、较小或相等次数的全部适用来源均须保留。`EndTurnRepeatPlan`采用内部 `max(1, 各来源设值)`，空来源为一次；完整主体列表与各计划在同一个原自然接受窗口冻结，后续来源死亡、沉默、转控、变形、替换、到期或移除不重算本批计划，新来源等待下一次自然接受。

上述来源门槛、广义主体范围和max合并属于内部候选政策；原始文字与现有其他机制不能证明它们已经得到官方或国服时序校准。

## 旧槽位、守卫与执行窗口

每个主体在其原混合监听槽位局部展开全部位置，例如 `A0 A1 / 普通监听O / B0 B1`。不得把额外执行移到全部监听之后，也不得先执行所有首次位置再执行额外位置。普通监听、玩家效果、有限次及英雄技能守卫保留原交错位置。

首次普通/休眠/玩家效果载荷保留原捕获局面；有限次首次载荷保留旧消费后局面，原 `limited_trigger_used` 事件与旧检查点只发生一次；英雄技能首次载荷保留旧安装身份守卫及原捕获局面。一个自然主体只经过一次原守卫，额外位置共享首次收据，不再消费有限用途或重查已安装技能槽。

首次守卫失败时整组位置均记为skipped，没有实际执行顺序；尚未开始的同组额外Invoke从当前队列移除，不能留下等待选择的无效控制。首次通过后，已接受的额外载荷继续按冻结能力执行；普通主体也不增加新的存活守卫。

guard_passed与guard_id的结构相等还不足以证明有限次守卫真的发生。分类有限次原有的 `limited_trigger_used` 事件增加全知内部数据 `end_turn_guard_id`（首capture.id）与 `end_turn_ability_id`（附件.id）；未分类有限次事件保持原样。`EndTurnRecord.guard_event`保存这个完整真实Event并传播整组。在真实事件已经append、used-event监听尚未capture之前，通过内部emit参数保存收据，不改变旧消费后上下文或检查点。稳定边界核对事件实际存在、序号唯一、主体/source/player/amount/action/自然batch及两个内部ID全部对应；同载体另一未分类有限能力的used-event不能借作本守卫证明。玩家信息事件沿用allowlist，仅投影trigger_keyword与amount等既有字段，两个内部ID及全知收据不进入观察，观察51保持。

英雄技能Check通过只改诊断相位，不改变物理局面、发事件或请求选择；此前正常检查点已经结算死亡和手牌。标准自然路径中，从首次HP Check通过到首次Invoke开始之间不存在合法waiting边界，因此稳定挂起快照拒绝该首次HP Invoke阶段；原HP Check及额外HP Invoke仍允许。这项门禁防止直接把尚未执行的Check替换为Invoke并伪造guard_passed。有限次守卫有真实used-event反应和选择，使用上述事件收据而不能套用该不可达阶段门禁。

额外位置排队时仍保存原接受上下文；实际开始先记录执行事实，再取得当时最新局面，前一个载荷及其反应已经结算。原自然事件、主体控制者/所属玩家、能力、计划和位置保持冻结。额外最新上下文可以合法缺少原能力或玩家实例；只对已开始的额外位置放宽该成员关系，排队Invoke必须拒绝伪装成已开始的fresh上下文。首次原窗口及额外最新窗口的差别是内部契约，尚待M6校准。

Invoke、Finish及批次完成是诊断控制，仍计入工程预算，不添加玩法检查点或游戏事件。结束重复与载荷主动激活的亡语重复是不同轴；例如CATA_150的结束载荷可以调用原有亡语机制，但不能再次创建真实死亡事实或混并两类次数。

## 完整位置与挂起证明

`EndTurnBatch.subjects`保存完整原主体列表，`plans`按主体一一对应；`total`为各主体次数之和，`position`映射完整重复位置。`EndTurnCapture.index`是主体下标，`repeat_index`从0开始，保存该主体完整plan；捕获ID按各主体完整跨度连续分配。`EndTurnRecord.guard_id`指向该主体首位置，guard_passed与有限次guard_event传播整组并与首收据一致；每个实际位置独立记录实际顺序、completed、skipped或interrupted。`RuleContext.end_turn`直接携带当前位置事实。

宿主构造的单位计划默认值不能成为损坏存档的退路。constructor可便利地为省略的Batch.plans填单位计划、为board Contributor派生spec、为Record派生guard_id；严格state parser与FrameCodec在调用constructor之前要求saved wire显式保存这些字段，检查plans与subjects长度精确相等、Contributor.spec非null、Record.guard_id为非null正整数。不能在构造器已经补齐后才检查，否则原来缺失或空值的证据会被规范化掩盖。快照还拒绝未知字段、缺字段、非严格整数、错跨度、重复来源或错来源规格。持续存活的相同附件ID或玩家实例须保持不可变规格和来源身份；合法用途消费、剩余期限减少和已移除实例按其生命周期处理。

`FinishEndTurnBatch`持续保存原接受局面证明，重算全部主体和全部来源计划，直到旧反应结束、自然时钟继续之前。最后额外载荷或尾部普通监听仍等待选择时，完整证明必须仍在队列；裁剪末尾Invoke/记录，再同步缩减live与各上下文计划，不能绕过原接受全集。

稳定边界核对全部批次、完整位置、原守卫相位、排队Invoke、运行Finish和批次证明。通用捕获state可以早于本批诊断事实建立；这与稳定恢复边界要求完整历史/队列不同。终局只中断尚未完成的位置，已经完成或跳过的事实保持；仍在playing的组不能伪造为interrupted来删除待执行工作。关闭后的历史仅承诺结构关系一致，不认证所有物理证据同步改写的过去；没有签名存档机制。

## 玩家期限、预算与信息边界

玩家来源沿用既有PlayerEffectSpec选定的owner自然边界；有期限规格可以使用 `turn_ended` 或 `turn_started`，重复声明不会改写它的时钟。对结束倒数来源，真实边界之前冻结旧实例与剩余值，全部结束载荷及旧反应完成后只倒数一次；剩余1的来源覆盖本次已经接受的全部重复，再按原时钟到期。开始倒数来源仍走原owner开始流程，不因本次结束重复额外倒数。对手回合触发的己方主体使用己方来源计划，但不会使己方期限额外倒数。本次边界反应中新建或替换的实例不加入该边界冻结倒数，留待后续规格所选owner边界；到期载荷也不被重新归为本次自然主体。

次数与完整位置必须在分配队列前受公共预算限制，不能先建立巨大tuple再检查，不能静默截断。预算还应计入Invoke、BehaviorCall、Finish及原守卫工作；效果展开继续使用已有全局工程预算。选择/恢复保留已经消耗的steps，不能在主体或重复边界重置。工程错误按既有事务回滚历史、时钟、随机和信息记录，不冒充游戏平局。

来源、接受证明、全知局面和历史查询是可信宿主信息，不进入玩家观察或命令。玩家端口仍只提供正常结束回合及选择操作，不新增重复或结束主体主动API。

## 证据、验证与下一项

来源候选及未定政策见[只读前置审计](../outputs/v103-end-turn-repeat-pre-audit.json)。其中30条catalog.raw都是完整原始记录并带canonical hash；这不是完整卡池分母、实现结果或国服规则证明。ICC_901与CORE_ICC_901保持独立，战棋次数记录不混入构筑；CATA_480原文中的`@`及标签3只是后续期限profile候选。

2026-10-03，83专项、887相关回归、5343全量及87示例内部通过；专项59.603秒、相关回归356.968秒、全量1755.742秒，M5共4095、M4共503。旧摘要共同动作/事件/物理结果字段不变；全新合成注册表原生恢复/回放、示例自有CLI与既有代表hs_sim CLI通过，均为内部证据。 见[验收摘要](../outputs/v103-verification.json)、[全量](../outputs/v103-full-tests.txt)、[示例比较](../outputs/v103-example-count-check.json)。上一批内部证据见[v102验收摘要](../outputs/v102-verification.json)。本轮日志约定为`outputs/v103-end-turn-repeat-tests.txt`、`outputs/v103-end-turn-repeat-regression.txt`、`outputs/v103-full-tests.txt`、`outputs/v103-examples-run.txt`及`outputs/v103-example-count-check.json`；close仅在根代理显式传入动态数量/原生摘要且证据达到终态后登记。

原生示例使用独立合成Registry并自行验证fresh-registry恢复/回放；运行入口为 `python -m examples.end_turn_repeats --replay <file>`，close保存实际native_cli_command。示例自有CLI与既有代表end_turn_subjects的hs_sim CLI证据分别记录，不能宣称通用hs_sim CLI会自动选择这个合成Registry；本轮没有新增真实代表。

下一项 **M5-13d-02l-05b：ICC_901与CATA_480必要代表**，在公共机制验收后接入独立原始pins和明确本地期限profile。效果主动调用、异阶段调用、条件/种族/特殊来源及TIME_064四类混合声明继续后置，不能宣称L05或整个结束族完成。M0正式池、M6国服校准和M7批量卡牌仍未完成。

[下一项只读预审](../outputs/v104-end-turn-representatives-pre-audit.json)在本批全量验证期间生成；根代理核对20条完整raw和134个当时依赖指纹。它只建议两张必要代表，保持独立CORE与附魔证据，场景和期限配置只是待执行候选，不是05b实现或国服验证结果。

原生摘要 `82dbdd3e127e97252c3431f2d358ae0b6de30860cb4db1b254d41ab560b2a1ea`，15动作/66事件，全新合成Registry恢复与回放内部通过；示例自有模块命令 `python -m examples.end_turn_repeats --replay outputs/end-turn-repeats-replay.json` 的[CLI日志](../outputs/v103-end-turn-repeats-cli.txt)。另核对既有代表end_turn_subjects的[hs_sim CLI日志](../outputs/v103-end-turn-subjects-cli.txt)；通用hs_sim CLI不自动选择此合成Registry。

更新：02l-05b自然结束重复必要代表已内部验收，34专项、1176相关回归、5377全量及88示例内部通过，见[代表契约](m5-end-turn-representatives.md)。只接ICC_901/CATA_480，内核100/schema97保持；R-145代表profile不替代R-144公共依赖的国服校准。下一项05c主动/异阶段入口保留scope，TIME_064混合更后，L05未整族完成。

更新：02l-05c主动与异阶段结束能力公共入口已内部验收，91专项、1094相关回归、5468全量及89示例内部通过，见[公共入口契约](m5-end-turn-activations.md)。自然原混合槽位、守卫/收据与owner时钟保持；内核101/schema98、代表包61，无新真实卡。下一项05d主动producer资格/选择政策与必要CATA_472代表；固定多轮与TIME_064混合后置，R-146未CN校准，L05未整族完成。
