# M5-13d-01：战吼身份与手动激活记录

本批将战吼与通用 `on_play` 分开，建立实际激活历史。身份增量交付时为 `prototype-v73` / `core-effects-v73`、snapshot schema 72、representative-m5-v36；玩家观察 v43、命令 v7、外层 replay 1 保持。旧快照 1～71 明确拒绝，没有隐式迁移。后续场上重复已由 [13d-02a契约](m5-battlecry-repeats.md) 扩展；本篇保留身份基础的历史验证，不能把它称作整个战吼机制完成。

## 声明、主体与目标

`CardDefinition.battlecry` 是已注册行为 ID，可用于物理随从、武器和英雄牌。印刷声明安装为独立 `AbilityInstance(kind='battlecry')`，记录附件身份；通用 `on_play` 继续表示其他出牌主体。法术、地标、技能、choice-only 以及抉择/战吼混合声明明确拒绝。普通抉择随从不会因内部存在 `on_play` 而变成战吼。

```python
from hs_sim.engine import CardDefinition, CardType, TargetSpec, TargetMode

registry.register_card(CardDefinition(
    'sample_battlecry', '战吼示例', CardType.MINION, cost=2, attack=2, health=3,
    battlecry='sample.battlecry',
    targeting=TargetSpec(TargetMode.IF_AVAILABLE, kinds=(CardType.MINION,)),
))
```

行为须在注册表冻结前注册，返回公共效果。已有适配从 `on_play='...'` 显式迁为 `battlecry='...'`，不在运行时从客户端标签猜测身份。一个定义同时有普通出牌主体和战吼时，按普通主体、战吼的顺序执行；当前二者使用同一出牌目标，不能表达两个独立的手选目标。

费用、场位、目标域与无目标策略仍由共同出牌入口校验。战吼本身不再支付、不新增一次手牌出牌，不创建法术施放记录。随从普通召唤、复制入场和效果装备武器不会触发战吼；手动武器在装备后、英雄牌在替换后走战吼入口。休眠随从的手动出牌主体资格沿用已有约定。

## 捕获与结算

普通出牌在现有主体捕获点保存 `BattlecryPayload(ability_id, behavior_id, card_id)`，在 `BeginBattlecry` 开始执行时建立 `BattlecryRecord`。载体能力中的 `battlecry_card_id` 与 payload.card_id 指向声明该战吼的原始卡，记录顶层 card_id 则是实际打出的卡。记录还含实际主体/玩家、目标、手牌出牌 ID、激活时间以及完成/终局中断状态。`RuleContext.battlecry` 提供不可变记录，`RuleContext.play` 继续保留原始出牌条件。

开始记录后发出 `battlecry_started`，效果执行完成后更新记录并发出 `battlecry_finished`。事件提供 `battlecry_id` 与 `play_id`，监听能够读取相应捕获事实。当前这两个事件属于宿主诊断与规则调度，不进入玩家日志，也不新增玩家命令。回调依旧是纯效果规划，不可直接修改状态。

普通出牌已捕获的战吼不因提交反应中的沉默、死亡、回手、变形或转控而丢失，仍使用捕获玩家、原定义与目标。战吼开始事件的反应在主体效果前执行，主体上下文在开始时捕获。具体目标已离场或来源已变化时，各公共效果按自身生命周期规则处理，不从场上重新寻找一张同名牌。

巨型沿用现有入口：先结算附肢，再由 `ColossalBattlecry` 检查主体存续和捕获其出牌效果；此时捕获的当前控制者可与最初打出者不同。该历史类名并不是战吼声明，它现在同时调度普通出牌主体和明确战吼。普通来源与巨型的捕获窗口差异继续列为 R-113，不冒充已经统一国服时序。

复制保留能力但分配新附件身份，沉默清除能力，回手重打重新安装印刷能力；这些操作本身均不增加战吼记录。来源离场后已有记录保留，不读取当前卡面反推历史。

组合星舰复用既有组件安装契约：声明来源随每个印刷能力保存，不能用舰体模板代替组件校验。发射仍走`on_launch`，不虚构手牌战吼；回手重打则执行继承的明确战吼。重复组件拥有不同附件身份，分别记录激活。当前/基础复制、变形和组合重建沿用公共附件规则，相关正式时序仍待R-113校准。

## 回溯、恢复与查询

普通回溯重试撤销上一尝试的对局历史，再执行一次接受的原动作；只保留当前尝试的战吼记录，费用与手牌出牌不重复累计。

保留多种结果时，`RewindOutcomeRecord.battlecries` 冻结最初的能力集合，每一遍经正常战吼入口建立一条记录；用 `outcome_id` 与 `iteration` 区分实际执行。中途沉默/变形或来源离场不会重新获取能力，仍只支付和打出一次。这些累计结果不是本批已经实现的“双战吼”光环。

`activated_battlecries(state, player_id, successful=None, turn=None, before_id=None)` 是宿主查询；successful 表示整次主体完成，空效果也可完成，不表示效果对场面一定有影响。`battlecry_record(state, id)` 获取明确记录。它们不接受玩家提供的全知状态，也不通过公开 DTO 暴露隐藏历史。

内部选择可暂停，开始/结束标记、捕获上下文和累计结果进入快照。恢复检查记录与手牌出牌的关联、声明行为、时间、去重、附件范围、保留结果及队列关闭顺序。普通边界不能留下未完成战吼；终局将已开始但未结束的记录标记中断，未开始的队列不虚构激活。失败在共同事务边界回滚状态、RNG、费用、日志和记录。摘要用于损坏检测，不是文件真实性证明。

## 迁移与验证

本批未增加卡牌。冻结代表中 44 条现有战吼主体已逐项迁移，包括宝石甲虫、叫嚣的中士、埃索达、灾变战斧、吉姆·雷诺、死亡之翼、奥拉基尔及各类发掘/探底/灌注代表。269 条真实记录/270 个定义、十二项 choice-only 保持；既有 `battlecry` 机制扩展，追踪机制数仍为 100。

56 项[专项](../tests/test_m5_battlecries.py)覆盖身份区分、随从/武器/英雄、目标/支付、普通召唤、生命周期、巨型、选择、回溯/累计结果、终局/回滚、宿主查询、玩家边界和严格恢复。最终全量3729项（534.810秒）、56示例及36台账检查通过，见[项目状态](project-status.md)与[全量日志](../outputs/v73-full-tests-final.txt)。

```powershell
python -m unittest discover -s tests -p test_m5_battlecries.py -v
python -m examples.battlecry_activations
python -m hs_sim replay outputs/battlecry-replay.json --card-set representative
```

[人工代表场景](../examples/battlecry_activations.py)从宝石甲虫发现中途保存，恢复后由玩家接口打出灾变战斧，跨回合打出雷诺；6 动作/32 事件、3 条完成战吼、3 条出牌记录，恢复与完整回放一致。摘要 `8eab8cf8429ae9897b42a6087d61932cf117c6f4598871b37a6b32add5ee2f66`。场景指定战士，使用已适配的战士兆示士兵；它不是正式国服构筑证明。

## 证据与后续

[冻结调查](../outputs/m5-13d-battlecry-candidates.json)记录 3,336 条战吼标签、2,312 个可收藏标记、44 条现有代表和 8 个调查根，不是合法池或支持分母。[官方英雄牌介绍](https://hearthstone.blizzard.com/en-gb/news/20944006/hearthstone-update-august-8-8-8-2017dlc7xql)以及[迦拉克隆介绍](https://hearthstone.blizzard.com/en-us/blog/23190444/)支持英雄牌战吼与替换的基础定义，不证明当前国服的逐个结算窗口。

R-113 保留普通/巨型捕获点、控制者变化、来源死亡/沉默/变形、目标离场、开始/结束事件与其他反应顺序、休眠出牌、回溯/累计结果的国服校准。

M5 仍需：动态授予及多个战吼的目标/顺序契约；重复次数叠加和条件筛选；全局或定向抑制；间接激活/历史重演；玩家长期与一次性修正；抉择混合声明及特殊来源。下一项 13d-02 先补重复与抑制的公共政策，13d-03继续间接/历史来源，见[机制清单](mechanism-backlog.md)。

当前v75/schema74/代表包38补充：所有手动战吼通过独立批次调度；BattlecryRecord增加batch_id与repeat_index，原iteration继续只表示回溯结果遍数。普通/保留结果捕获同一次数计划，队列需在原完成标记之外闭合重复和批次。272真实记录/273定义；身份增量中的56专项与3729全量属于v73历史记录，本轮结果见项目状态。[13d-02a](m5-battlecry-repeats.md)明确完整当前行为与剩余缺口。

玩家有限次与期限政策由[13d-02b](m5-battlecry-modifiers.md)实现，观察v44新增受控用途/期限投影；整体战吼机制仍有抑制、反制和间接/历史来源缺口。

后续兼容说明（v76）：普通随从先在待结算区完成承诺与反制窗口，通过后入场并捕获战吼；因此card_committed反应现在发生在捕获前。本文件原批次验证保留为历史，入场后变形/沉默/死亡不改写已捕获计划的测试改用minion_summoned；反制/入场失败不消费玩家政策。见[整次反制契约](m5-minion-counters.md)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为battlecry_activations.py：6动作/34事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
