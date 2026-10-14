# 随机强制攻击的角色受击范围

本项修正原 `RandomForceAttack` 的候选范围，复用原 `ForceAttack` 和战斗窗口。实际进度、测试结果及下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

## 公共输入与候选

```python
RandomForceAttack(
    attacker_ids=(source_id,),
    defender_ids=(enemy.hero_id, *enemy.board),
    source_id=source_id,
)
```

输入、字段和构造校验保持原样。攻击者仍须为活跃、存活、未标记消灭的场上随从；英雄不能作为该效果的攻击者。受击者可以是符合相同存活条件的场上随从或当前英雄。手牌、牌库、武器、惰性物体、休眠、已离场及未知引用不进入池；未知非空来源引用仍明确报错。

每个原攻击者/受击者物理配对保留一个权重，配对按实体 ID 排序后只调用一次原 RNG choice。输入不重复，原 `combat_relation` 继续排除自身并限制双方关系；`friendly_minions` 仍只允许同控制者不同随从，不会因英雄范围扩大而允许己方英雄。空池不抽样、不推进 RNG，也不发布随机或攻击事件；单一配对仍沿原 choice 推进 RNG。

筛选采用原活跃角色与关系政策，不调用玩家普通攻击合法性。原已用次数、冻结和入场等待不阻止强制攻击；原嘲讽、潜行、免疫等选择/战斗政策继续沿旧路径，精确国服资格仍需校准。效果输入只含随从受击者时，其候选、顺序和抽样保持。

## 战斗、恢复与信息

原 `random_choice` 继续以 `target_id` 保存攻击者，以 data 中的 `defender_id` 保存受击者。抽样后生成原 `ForceAttack`，再打开 `forced=True` 的原攻击窗口；伤害、反击、护甲、死亡、终局和攻击完成沿共享管线，强制攻击不额外消费普通攻击次数。

待选保存已抽中的原引用、窗口、队列与随机状态，恢复/clone/replay不会重抽。选中英雄在窗口中替换后，旧引用失效并沿原战斗取消路径处理，不把新英雄自动塞回原抽样。即时错误与失败选择由原事务回滚到原状态、事件、付款与随机状态。

引入时 `prototype-v201 / core-effects-v195 / schema189`，旧 schema 1～188 仍拒绝。仅规则与处理器语义版本变化，存档结构没有变化；旧 v200/v194 语义描述不能作为当前存档恢复。观察74、命令11和回放外层1保持。没有新状态字段、缓存、效果类型、动作、事件或机制模块。玩家只得到原公开攻击和生命结果、原受限选择与日志，不提供全知状态、内部窗口/队列或 RNG。

## 必要代表与证据边界

仅隔离验证 `BAR_020` 钢鬃掠夺者，暴怒主体通过原 `LimitedTriggerSpec.frenzy` 返回上述效果。原能力的一次消费、存活判断、控制者和生命周期由[有限触发模块](m5-limited-triggers.md)处理，没有新增暴怒执行器或“暴怒＋攻击”专用组合。

[本地完整 raw/pin](../data/support/random-forced-hero-basics.json)为5费5/6、中立普通野猪人；FRENZY=1是存在标签。[2021年官方贫瘠之地公告](https://hearthstone.blizzard.com/en-gb/news/23622608)描述暴怒存活触发及钢鬃掠夺者随机攻击敌人，历史图注为5/5，与本地原始生命6不同。隔离卡面采用本地完整数据，不把历史5/5当作当前卡面。官方卡库[直接页](https://hearthstone.blizzard.com/en-us/cards/62701-razormane-raider/)目前只返回动态外壳；[来源分级](../outputs/random-forced-hero-basics-20261010/official-evidence.json)明确区分历史文案、本地材料和内部资格政策。

英雄受击、候选资格、随机/强制攻击窗口及原暴怒时序仍为 M6 待校准。当前国服合法身份和正式可达池属 M0，完整来源接入属 M7。随机改打已接受攻击目标是另一项表达核查，不把新建一次强制攻击当作目标替换；完整 U44 和基础目标继续开放。

随机改打错误敌人已用原抽样/零项自动回调与RedirectAttack表达，见[独立表达契约](m2-wrong-enemy-attacks.md)。不请求玩家作选择，内部计数/choice_skipped保留；原接口与上述历史阶段证据保持，该历史批次核心为prototype-v201/core-effects-v195/schema189，现行版本见两份主台账。精确CN待校准。
