# 起始套牌印刷费用上限

公共声明 `DeckCostCeilingCondition(cost_limit, cost_basis, scope='starting')` 表达：指定玩家原始构筑中的每张牌，其印刷费用均不高于明确上限。实际执行、验证结果与下一项统一见[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。

```python
condition = DeckCostCeilingCondition(3, 'printed')
CheckDeckCondition(player_id, condition, matched_effects, unmatched_effects)
```

`cost_limit` 必须是非负整数；布尔、浮点、字符串和负数均拒绝。`cost_basis` 必须显式为 `printed`，`scope` 只允许 `starting`。不接受当前牌库、保存费用或外部报价作为隐含替代。

读取 MatchSetup 开局所绑定的 `original_deck` 和注册表中的固定 `CardDefinition.cost`。所有原始牌型及重复条目都参与判断；等于上限符合，0费和高于通常法力上限的合法整数也按相同规则比较。换牌、抽牌、洗入、变形、离场、当前实体改费及手牌外部减费均不重写原始构筑事实。

每条原定义及其费用完整查验后才聚合。前面的高费用不遮蔽后面的未知定义；只比较印刷费用，不要求无关职业、种族或稀有度元信息。Scenario 没有可信的起始构筑事实时抛出 `UnknownDeckFacts`，不能从当前剩余牌推断。空原始条目的全称真只属于通用内部查询政策，不证明原生构筑允许空套牌。

查询复用原 `PoolQuery(max_cost=...)` / `matches_metadata`。新冻结三字段声明显式注册到公共帧编码器；`CheckDeckCondition` 仍是原来的四字段效果，其分支执行器和已选择分支的恢复政策保持。没有新增持久状态、计时器、动作、事件或另一套结算器。查询本身不付款、不推进随机、不发表私有牌库内容。

原本的 `DeckCondition`、`DeckCostCondition`、`DeckSpellSchoolCondition` 和 `DeckMinionCostCondition` 继续使用各自依据与范围；费用上限声明不扩大这些声明的合法值。未知类型、字段和旧处理器身份明确拒绝。

真实需求依据是[完整本地 JAIL_860 证据](../data/support/starting-deck-cost-ceiling-basics.json)。原文的费用条件为“不超过3费”；原始 `CHEF_NETHREK_REQUIREMENT=4` 保留，不用内部标签覆盖正文。该包包含完整原行和来源指纹，不能代替正式目标卡池或规则校准。

费用条件可以单独验证。JAIL_860 的完整“五回合后法力设为10”还包含计数边界、法力含义和来源政策，在明确这些规则前不注册部分牌、不将该牌当作白板。必要开局、分支和等待夹具均明确为合成定义，不宣称完整原生卡适配。

普通持续玩家效果可监听真实本人回合历史并移除自己的精确实例，因此仅凭 objective/sigil 占槽不能推断必须新增计时模块。具体原生“五回合”采用哪个边界、是否调整最大/可用法力及精确国服行为，仍按既有 M5/M6/M7 阶段处理，不由费用上限接口暗中决定。
