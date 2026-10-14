# 起始套牌没有法术牌

`DeckCondition('starting', 'no_spells')` 是原两字段套牌条件的有限谓词。纯查询继续使用 `matches_deck_condition`，效果分支继续使用原 `CheckDeckCondition` 和共享解释器，没有新类型、计数器或执行器。

```python
from hs_sim.engine import DeckCondition, CheckDeckCondition

condition = DeckCondition('starting', 'no_spells')
effect = CheckDeckCondition(player_id, condition, on_match, on_miss)
```

两分支是不可变效果元组，条件在效果轮到执行时查询一次，随后所选序列沿用原检查点、选择暂停、事务和恢复。

## 原始事实与范围

读取指定玩家真实构筑开局的 `opening` / `original_deck` 主套牌记录，逐条解析原 `CardDefinition`。由 `PoolQuery(kinds=(CardType.SPELL,))` 判断原牌型；不存在 SPELL 时为真，存在任何已知 SPELL 时为假。原随从、武器、地标及可构筑英雄牌均为非SPELL。费用、法术派系、职业、中立身份、重复身份或收藏状态不代替牌型。

全部原定义都必须已知，查验完成后才聚合。即使前面已遇到一个法术，也不能跳过后面的未知原定义。此条件不要求无关职业/稀有度等 metadata；宿主诊断可以检验这些依赖，但手工改写的诊断操作数不宣称为合法原生构筑。

起始事实由原构筑与存档恢复校验绑定。`Scenario` 的当前牌库或单独填写的原元组不能提供开局证据，查询会抛出 `UnknownDeckFacts`。宿主须传入已验证状态；查询自身不另建一套存档来源认证。

换牌、硬币、抽牌、生成法术、清空当前牌库、原牌非死亡移除、当前改费和存储卡面变化均不改写原记录。查询不消费RNG或资源，不推进事件、历史、时钟与动作。完整原套牌和私有条件帧不提供给玩家。

原字段仍只有 `scope` / `predicate`。本谓词只开放 `starting`，`current/no_spells` 仍明确拒绝。旧 `current/no_minions`、`current/no_neutral`、空牌库、原费用奇偶、重复身份及其他六类声明保留各自依据；“所有原法术属于暗影”也不能代替“原套牌无法术”。

## 真实卡文依据与范围

[完整本地记录](../data/support/starting-deck-no-spells-basics.json)保留 `JAIL_806` 妖术长官完整行、行摘要和提取源 SHA。英文明确读取起始套牌无法术，构成这个基础谓词的真实需求。

- 支持包 PIN：`132f56f858e3d9916cb1bab0b5eb3c823173f1aadcb9aa898cd0338153014dc3`。
- 提取源 SHA：`fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`。
- 本批仅验证公共条件，未加入完整妖术长官适配。随机获取≥5费法术、获取牌的减费主体和完整合法生成池继续开放。

精确原始牌型、求值窗口、完整来源及国服有效版本仍待校准。生产代表包和正式卡池没有因raw存在而扩充；未知卡牌、未知主体及未知池继续明确报错。

## 兼容性与内部验证

引入时 `prototype-v244` / `core-effects-v238`；schema216、旧1～215拒绝、观察75、命令11、replay1保持。旧核心237即使布局相同也被拒绝。`CheckDeckCondition` 的四字段、`check` 和 `register` 保持，没有新payload、持久模型字段、模块、效果、事件、动作或组合。

验证覆盖真实30槽原事实、原SPELL费用/派系差异、非SPELL各牌型、重复槽位、双玩家、原事实未知、完整定义遍历、纯查询、换牌/硬币/生成/移除/抽牌/当前费用与卡面变化、自然回合、公共命令、开局/出牌未执行及已选待选、独立注册表恢复/clone/回放、回滚、严格载荷与玩家信息边界。测试的MINION工具只是保持原无法术分支可达的基础验证夹具，不属于新的卡牌组合支持。

实际结果与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护；[本轮验证](../outputs/starting-deck-no-spells-basics-20261011/verification.json)绑定选定测试与源码。本文件是公共扩展契约，不宣称最新国服完整规则已实现。
