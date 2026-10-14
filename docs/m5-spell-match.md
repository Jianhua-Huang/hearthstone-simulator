# M5-13d-02m-01-A1：法术学派匹配与双窗口接受

2026-10-03，已内部验收，未国服校准。运行规则/效果104、snapshot schema101、玩家观察52；动作7、外层replay1保持。代表包63、304完整实验记录/305定义/14条choice-only保持，本增量不添加代表卡。旧schema1～100需对应原引擎，观察旧版本明确拒绝。

本增量按[机制清单](mechanism-backlog.md)继续机制优先。之前四族组合已通过5630项全量及91示例，见[v107验收](../outputs/v107-verification.json)；那些终态不代表本增量通过。A1的实际专项、相关回归、全量与示例结果在执行后登记于[项目状态](project-status.md)。R-149是本地内部契约，未国服校准。

## 接收对象与匹配

新增`RecipientMetadataFilter(basis='accepted_face_printed', spell_schools=())`及`RepeatMatchSpec(recipient_metadata=None)`，由`SpellRepeatSpec.match`引用。A1只开放接收法术的印刷学派，与已有`class_mode`取交集；没有种族、费用、持续来源条件、another关系或逐主体筛选的空实现字段。未知字段、未知枚举、错误类型和重复学派明确拒绝。

```python
SpellRepeatSpec(casts=2, class_mode='any', match=RepeatMatchSpec(
    RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,))))
```

学派列表内部为OR，学派与职业为AND。`match=None`、metadata=None或空学派元组保持没有学派限制。注册定义中的`spell_school=None`是已知无学派，不匹配非空学派筛选。职业other仍要求已知英雄职业和法术职业元数据，中立牌及包含本职业的多职业牌不匹配。未知定义和缺失所需职业事实明确报错，不当作普通白板。

两个窗口都用`PlayRecord.card_id`取得注册定义，不能改用结算期间变形后的实体卡面、重复来源的种族、授予者卡面或伤害包学派。纯matcher只读取明确传入的定义和该窗口英雄职业，不查询当前Game、执行效果、消费用途或使用随机。

场上`spell_repeat`附件及玩家`SpellRepeatModifier`均使用此条件。物理`card_spell_repeat`仍是提交时冻结的特定卡次数，明确要求`match=None`；其授予与创建API不因此获得条件筛选参数。

## 两个原有窗口

1. 付款并追加手牌PlayRecord后，提交窗捕获全部匹配玩家政策；有限来源各扣一次，较低及相同次数来源也保留。完整`SpellSubmissionReceipt`允许显式空集合，旧非空`SpellPolicyReceipt`账本继续保留。被反制也保留提交消费。
2. 目标与反制窗口关闭后，非反制根捕获全部合格场上附件、实际目标、有序行为及当前英雄职业。`SpellPayloadReceipt.casts`为物理特定卡、提交玩家政策和较晚场上来源的最大总次数。一次执行和空效果也有收据。
3. 被反制根记录真实关闭窗口后的resolution context，但没有payload接受收据，不运行场上次数匹配或主体。沿用原反制施法记录和一次FinishPlay。

新增筛选不提前场上窗口，不把玩家用途消费后移。已接受计划在后续沉默、离场、变形、转控、增加来源和英雄替换中保持；新的真实手牌根重新匹配。普通回溯重建提交与较晚窗口，保留多结果共享原接受事实。

## 可恢复的完整接受证明

`FinishSpellAcceptance(submission, resolution)`是整次手牌法术的透明尾部控制工项。提交原GameState在安装收据及消费前捕获，较晚原GameState在关闭窗口后、写payload收据和begin_played前捕获。resolution=None表示尚未到ResolveSpell；非None时按countered区分反制与真实主体接受，不能用空plan伪装反制。

ResolveSpell按play_id查找唯一原尾工项并原位补上resolution。其位置保持在原主体工作和FinishPlay之后，所有该根出牌完成反应及衍生结算先执行；不得追加到Rewind Offer之后。选择帧保存当前前缀和续接，恢复时继续同一证明。`PlayRecord.completed`不等于尾部已关闭；FinishPlay后的待选仍需唯一证明，最后写`spell_acceptance_closed=True`。

等待帧另存必需的`spell_acceptances`有序义务，不能仅凭当前PlayRecord关闭标记推断尾部是否存在。该字段与完整队列中的尾工项逐项一致，嵌套真实手牌根按内层先关闭；外层出牌完成后的选择分支可以支付并创建新的内层根，恢复仍保持原顺序。原提交context的target必须等于原PlayRecord.target；较晚resolution允许目标窗口中的合法重定向。已标记关闭的根不能仍保留明确指向该根的未闭合回调上下文。

恢复从两个原窗口重算完整匹配集合、max次数、目标和行为，不仅核对最大来源。还检查现存来源完整声明及物理载体归属，允许已移除来源、合法载体转控和后续消费；跨族身份冒充、重写spec/provenance或迁移附件到另一个载体应拒绝。紧凑收据和已有重复/施法/保留结果进度保持一致。

原GameState只在活动证明/选择帧中存在，已完成PlayRecord保存紧凑收据和关闭标记；不将完整状态递归嵌入历史。原context的GameState只做历史与类型不变量检查，live Game的稳定边界另检查完整接受义务，避免把提交前尚无收据的合法原状态当作损坏。无签名存档不能认证被协调重写的全部原状态与证据来自官方对局。

一次施放继续走原直接payload入口，不新增SpellRepeatRecord，不获得重复施法的选择缓存或死亡延后。两次及以上继续使用原重复记录、死亡延后、选择缓存、每遍独立施法记录、当前局面与RNG。新尾部证明不生成玩法事件或死亡检查点；仍计入工程结算预算。英雄终局可放弃未闭尾，不把它伪装成完成证明；事务和选择回滚沿用公共框架。

## 严格wire与玩家信息

新schema所有SpellRepeatSpec必须显式存`match=null`或完整typed object，三个PlayRecord接受字段及等待帧`spell_acceptances`也必须存在。缺字段不能用构造默认值静默还原无条件或无尾部义务。modifier、ability、收据与FrameCodec使用相同严格模型。

玩家政策及四类政策事件公开casts、class_mode、match、uses_remaining、expires_turn。match只包含静态basis与学派参数，不公开来源实体/附件ID、全知接受状态、主体行为、历史收据或帧。公开DTO结构因此升为player-view-v52；不能保留v51编号并静默改变格式。

## 门禁与后续

必要专项覆盖学派×职业交集、已知无学派、低/等/高来源完整性、双窗变化、一次/空/反制、生命周期、等待恢复、独立注册表回放、普通与保留回溯、预算/异常/终局和玩家隔离。门禁还包括既有法术与组合契约、全量及示例；本批实际结果见下方。

公共A1验收后才开始独立A2必要RLK_541实验适配。持续来源条件与另一物理实体、其余四族逐族匹配、费用依据、逐主体次数、周期计数、额外一次及Whenever CAST分别保留。自动/抽到/历史施法适用、正式国服规则、完整来源图、M0合法池和M6/M7不因A1完成而自动完成。

只读依据：[800 raw前审](../outputs/v108-conditional-repeat-pre-audit.json)、[合同草案](../outputs/v108-conditional-repeat-contract-draft.md)、[21项模型审查](../outputs/v108-spell-match-model-review.json)、[26项接受证明审查](../outputs/v108-spell-acceptance-proof-review.json)、[测试设计](../outputs/v108-spell-match-test-design.json)及[根复核](../outputs/v108-spell-match-root-audit.json)。这些历史观察保留当时指纹，不刷新成当前代码，也不当作测试终态。

[原生合成组合](../examples/spell_match.py)已首跑：6动作/37事件/6次施法，两次真实待选；max次数3、无匹配1、下一根2，原场上来源死亡后当前计划保持，低玩家政策各消费一次。两个waiting独立注册表恢复、clone及回放一致；这段保留首跑历史观察，最终执行结果见下方实际终态。运行`python -m examples.spell_match`，独立CLI用`python -m examples.spell_match --replay outputs/v108-spell-match-replay.json`。

实际终态：[验收证据](../outputs/v108-verification.json)。33专项、67信息/操作回归、892相关回归、5663全量及92示例内部通过；专项84.739秒、信息11.487秒、相关527.004秒、全量2274.395秒。原生合成6动作/37事件/6施法/2真实待选，max次数[3,1,2]、护甲8，waiting独立注册表恢复/clone/回放及模块CLI通过。88旧/89当前摘要的共同行为及字段保持；1129历史文件字节保留。较早schema99/core102的19新增字段及2控制清单经针对复核，前批迁移与A1变化分别登记。仅内部证据，R-149未国服校准。

首次892相关539.436秒仅旧错误提示断言失败；全量中断1580行成功，均非通过。只改旧测试的范围提示99→100，旧schema99负例及当前101正例保持；65组合59.628秒通过后复冻结。原33专项、92示例与独立审查的运行期指纹不刷新；唯一测试差异及相关/全量重跑另存，生产代码和示例保持。
