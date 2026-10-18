# 起始套牌随从印刷费用总和

`DeckMinionCostSumCondition(total_cost, cost_basis, scope='starting')` 声明一个独立的起始套牌条件。卡牌通过现有 `CheckDeckCondition` 选择效果分支；执行、选择暂停、恢复和异常回滚均由原解释器负责。

后续完整威拉诺兹适配把本条件接到原当前物理牌库的属性均分；数值依据、余数及窗口见[接卡契约](m3-deck-stat-distribution.md)，本条件与原起始事实口径不变。

```python
from hs_sim.engine import DeckMinionCostSumCondition, CheckDeckCondition

condition = DeckMinionCostSumCondition(100, 'printed')
effect = CheckDeckCondition(player_id, condition, on_match, on_miss)
```

`on_match` 与 `on_miss` 是不可变效果元组。查询 `matches_deck_condition(state, registry, player_id, condition)` 只供宿主或规则代码使用；调用方须提供已验证的引擎状态。

## 声明与事实依据

| 字段 | 接受范围 |
| --- | --- |
| `total_cost` | 严格非负整数；布尔、浮点、字符串和负数拒绝 |
| `cost_basis` | 必须明确填写 `printed` |
| `scope` | 只接受 `starting` |

查询需要真实构筑开局的 `opening` 记录，读取指定玩家不可变的 `original_deck`。构筑与存档恢复沿用原开局身份验证。只有当前牌库或自行填写一个原套牌元组的 `Scenario` 不提供所需起始事实，会抛出 `UnknownDeckFacts`。

逐条查询全部原始主套牌定义，再以 `PoolQuery(kinds=(CardType.MINION,))` 筛选随从，将其印刷费用求和并与 `total_cost` 比较相等。每一原始槽位分别贡献费用，包括同卡面两张和零费随从。法术、武器、地标及可构筑英雄牌均排除；这些原定义仍须已知。原定义未知时明确报错，不因前面的费用已经命中或失配而跳过后项。

空随从子集的总和为零，这是明确的内部数学政策；没有借此允许空主套牌构筑。总和不受法力上限限制。抽牌、换牌、当前实体改费、外部手牌报价、生成牌、牌库移除及原物理牌变形均保持原套牌总和。

查询不推进随机数、回合、历史或事件，不保存新的计数器。原五类套牌条件和分支执行主体保持；新声明作为三个字段的 typed payload 注册，`CheckDeckCondition` 仍只有原四个字段。分支在该效果实际执行时选择一次，后续选项暂停与当前牌库变化沿用已选效果序列。

## 原始卡牌依据与实现范围

[完整本地记录](../data/support/starting-deck-minion-cost-sum-basics.json)保留 `CATA_213` 威拉诺兹的完整行、行摘要和提取源 SHA。记录中英文明确要求起始随从费用总和为 100；本文件只规定该基础查询。

- 支持包 PIN：`9fcc48a7da967a9ab6d99b8f574fc70841d651101b49c8384b06a7d81b159c95`。
- 提取源 SHA：`fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`。
- 本增量未加入完整 `CATA_213` 可执行适配。100 点属性随机分配主体仍开放，测试使用明确的条件分支夹具。
- `TLC_100` 的起始不同费用种类与自定义地标主体属于其他需求，不能以此求和声明宣称已支持。

费用依据、精确条件窗口、空子集政策及完整来源仍需国服校准。生产代表包、正式卡池与完整规则覆盖不由这份 raw 或查询证明。

## 兼容性与内部验证范围

引入时 `prototype-v242` / `core-effects-v236`；schema216、观察75、命令11、replay1保持。旧核心235和旧schema215恢复被拒绝；旧1～215拒绝范围保持。没有新增持久模型字段、效果执行器、事件、动作或组合机制。

验证覆盖真实30槽起始事实、双玩家、99/100/101及参数化总和、重复槽位、非随从/零子集、换牌、当前费用与区域/卡面变化、分支执行、开局/出牌待选、独立注册表恢复、clone与回放、回滚、严格载荷和玩家信息边界。缺失 metadata 与未知原定义的测试使用隔离的宿主诊断操作数，不宣称那些被手工改写的状态是合法原生对局。

实际执行和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护；[验证记录](../outputs/starting-deck-minion-cost-sum-basics-20261011/verification.json)绑定本轮选定测试与源码。本文件是扩展契约，不是最新国服完整支持声明。
