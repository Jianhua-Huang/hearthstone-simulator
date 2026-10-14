# 起始套牌不同印刷费用种类

`DeckCostDiversityCondition(min_distinct_costs, cost_basis, scope='starting')` 声明原主套牌中至少存在指定数量的不同印刷费用值。卡牌通过原 `CheckDeckCondition` 选择效果分支，复用原解释器、选择帧和事务。

```python
from hs_sim.engine import DeckCostDiversityCondition, CheckDeckCondition

condition = DeckCostDiversityCondition(10, 'printed')
effect = CheckDeckCondition(player_id, condition, on_match, on_miss)
```

两分支均为不可变效果元组。`matches_deck_condition(state, registry, player_id, condition)` 是宿主/规则查询，调用方须提供已验证状态；完整原套牌和私有条件帧不提供给玩家。

## 声明与费用依据

| 字段 | 接受范围 |
| --- | --- |
| `min_distinct_costs` | 严格非负整数；拒绝布尔、浮点、字符串及负数 |
| `cost_basis` | 必须明确填写 `printed` |
| `scope` | 只接受 `starting` |

查询需要真实构筑开局 `opening` 记录，读取指定玩家不可变 `original_deck` 的全部主套牌槽位。原构筑与存档恢复共用既有开局身份校验。当前牌库或单独填写原元组的 `Scenario` 无法提供起始事实，连最小值0的查询也会抛出 `UnknownDeckFacts`。

全部原定义及其严格非负印刷费用须已知，之后将费用值去重，比较 `len(set(costs)) >= min_distinct_costs`。随从、法术、武器、地标和可构筑英雄牌均参与。两张同卡面或不同卡面但费用相同，只贡献一种费用；0也是一种费用。费用之间可以有空缺，超过法力上限的值仍参与，种类数不封顶于10。

例如原套牌含0～9费时有10种费用，含0～10费时有11种，均满足最小值10；30张零费牌只有一种。未知原定义必须报错，即使前面已达到门槛，也不能短路跳过剩余行。查询不要求无关的职业或稀有度 metadata；缺 metadata 的隔离宿主诊断操作数不作为合法原生构筑证据。

抽牌、换牌、生成、移除、当前改费、外部手牌报价和原物理牌变形不会改写原费用集合。查询不推进RNG、事件、历史或时钟，不保存新的计数器。原六类套牌条件及其聚合主体保持；新声明是三个字段的 typed payload，`CheckDeckCondition` 仍使用原四个字段。效果执行时选择分支一次，之后的暂停、恢复、当前牌库变化和异常回滚由共享帧与事务处理。

## 实际卡文与未校准边界

[完整本地记录](../data/support/starting-deck-cost-diversity-basics.json)保存 `TLC_100` 导航员伊莉斯完整行、行摘要及提取源 SHA。其英文要求起始套牌具有10张费用不同的牌，中文也明确10种费用，构成这项公共查询的需求依据。

- 支持包 PIN：`c82669854668f00c5d526cb2ad30dc481649abc409e5a94877ba7a151361f08a`。
- 提取源 SHA：`fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`。
- ≥10 是由本地卡文作出的解释：11种费用仍包含10种不同费用的子集。本轮官方网页检索没有取得直接确认“大于10”边界的规则证据，两处卡牌页面也未成功读取；[解释记录](../outputs/starting-deck-cost-diversity-basics-20261011/source-interpretation.json)明确区分推定和国服校准。
- 本增量没有加入完整 `TLC_100` 原生适配，自定义地标制造、各组件和完整生成池保持开放。`CATA_213` 的100属性分配也没有由费用种类查询实现。

公共“至少N种”的声明与计算已作内部验证；精确国服卡牌门槛、接受窗口及完整来源仍待校准。未知池、未知卡牌和未知行为继续明确报错。

## 兼容性与验证范围

引入时 `prototype-v243` / `core-effects-v237`，schema216及旧1～215拒绝、观察75、命令11、replay1保持。旧核心236即使布局相同也被拒绝。无新持久字段、模块、效果执行器、事件、动作或组合机制。

内部验证覆盖真实30槽原构筑事实、9/10/11种与参数化门槛、重复费用/零/费用空缺/大值、全部牌型、双玩家、纯查询、换牌/费用/区域/卡面变化、公共命令、开局与出牌未执行/已选待选、独立注册表恢复/clone/回放、回滚、严格载荷与玩家信息边界。

实际执行与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护；[本轮验证](../outputs/starting-deck-cost-diversity-basics-20261011/verification.json)绑定选定测试及源码。本文件是公共扩展契约，不宣称最新国服完整模拟器已实现。
