# 起始套牌印刷费用奇偶条件

```python
DeckCondition(scope='starting', predicate='all_even_cost')
DeckCondition(scope='starting', predicate='all_odd_cost')
```

这两个有限值扩展原冻结 `DeckCondition`，仍只有 `scope`、`predicate` 两字段。两者仅接受 `starting` 范围；`current`、任意表达式和未知谓词明确拒绝。原无重复、无中立、无随从、空牌库、指定本地费用排除和法术派系声明保留各自范围及语义。查询和执行仍用原 `matches_deck_condition`、`CheckDeckCondition`。

## 事实与费用依据

查询指定玩家有构筑开局记录、由 `MatchSetup` 绑定的 `original_deck`。每条原始牌记录读取注册表中固定 `CardDefinition.cost`，先严格查验非负整数，再判断余数。所有原套牌牌型都参与，重复牌各自参与；零费是偶数，100、101等合法非负费用也参与，不按法力上限截断。仅需费用事实，不额外要求职业、稀有度或构筑别名元信息。

必须完整查验所有定义后汇总，前面的已知奇偶不符不能掩盖后面的未知牌。没有原构筑开局事实时抛出 `UnknownDeckFacts`；任意场景的当前牌库或人为写入的原始 tuple 都不能提供该事实。全知原卡组和条件帧不能进入玩家观察。

换牌、硬币、抽牌、洗入、清空当前牌库、当前卡面或费用变化不重写原构筑记录。实体保存费用、当前牌库费用、外部手牌假设报价均不能代替原印刷费用。查询不消费用途或随机数，不改动作、事件与历史。数学上的空集合全称为真，仅为通用查询内部政策，不据此证明零张牌是合法构筑或国服原生开局结果。

## 原执行入口与必要代表

原 `CheckDeckCondition` 在轮到执行时选择一次分支；公共解释器负责该分支的检查点、待选、恢复、克隆、回放和回滚。分支选中后改动当前牌库不会重新选分支，新的执行则重新查询。没有新模块、持久字段、效果、执行器、事件、动作或组合机制。

必要隔离代表仅 `GIL_692`「吉恩·格雷迈恩」，使用完整冻结原行：6费6/5、中立传说，无种族标签、无战吼。其原 `OpeningHook('before_deal', ...)` 查询起始全偶数条件，命中后对该窗口的当前初始物理英雄技能执行既有 `ModifyCost`：

```python
ModifyCost(
    initial_power_id,
    CostSpec(set_to=1, card_types=(CardType.HERO_POWER,)),
    source_id,
)
```

`HERO_POWER` 必须显式声明：`CostSpec` 默认筛选普通可打出手牌种类。该费用附件属于原物理技能，在普通使用和回合推进后保留；吉恩正常打出、沉默、回手或死亡不撤销它。随后安装的新技能即使卡牌ID相同，也有新物理身份和自身费用；没有玩家永久减费规则或未来技能升级映射。

完整原始行及 PIN 在 `data/support/starting-deck-cost-parity-basics.json`。`GIL_826` 巴库和两份 CORE 行仅原始证据，没有可执行适配。实验套牌为完整30槽，背景牌、英雄和初始技能明确为合成夹具，不扩展正式卡池或生产代表包。

## 规则依据与兼容边界

官方[奇偶套牌设计说明](https://hearthstone.blizzard.com/en-us/news/21614308)说明奇偶构筑、对战开始时生效及吉恩技能变为1费；[吉恩卡库](https://hearthstone.blizzard.com/en-gb/cards/47693-genn-greymane/)的索引文字明确初始技能条件。它们没有单独证明本实现的精确国服费用层、空集合、开局相对窗口或技能形态政策。

引入时 prototype-v238/core-effects-v232；原两字段 payload、持久布局和 schema215 保持，旧1～214仍拒绝，观察74、命令11、replay1保持。规则和处理器身份变化后，旧快照仍须使用原版本。原印刷费用、`before_deal` 和当前初始物理技能为明确内部政策，精确国服规则仍待 M6。实际验证与下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。
