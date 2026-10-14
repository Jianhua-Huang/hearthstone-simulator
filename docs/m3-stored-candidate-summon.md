# 从物理候选随机召唤

`SummonFromStoredCandidates(player_id, cards, position=None, stats=None, cause=None)` 在既有区域召唤模块中补上一次随机物理选择。`cards` 是不可变 `CardReference` 元组；每个物理实体只能出现一次，同名的不同实体分别占一个等权候选。候选属于同一原区域和控制者，目的玩家可以不同。

必要来源为本地固定的 `BAR_325` 剃刀野猪：[官方卡文](https://hearthstone.blizzard.com/en-us/cards/63163-razorboar?set=forged-in-the-barrens)要求从手牌召唤费用不超过 3 的亡语随从。两张同名卡可以因局部减费而分别为 3 和 5；原 `PoolQuery` 按印刷费用及卡牌身份过滤，不能区分这两个物理候选。前审证据在 [同名实体诊断](../outputs/stored-candidate-summon-basics-20261013/same-id-gap-probe.json)。本增量不改写原 `SummonFromZone` 的印刷过滤政策。

卡牌的纯回调在实际主体执行窗口，用 `quote_unselected_cost` 和当前有效能力查询构造完整候选。回调通过注册表闭包读取固定定义，不能获取或操作随机源。费用查询不支付法力、不消费一次减费；费用层的精确国服规则仍需 M6 校准。普通候选构造可以写为：

```python
cards = tuple(
    CardReference.capture(ctx.state.entities[i])
    for i in ctx.state.players[ctx.player_id].hand
    if ctx.state.entities[i].kind == CardType.MINION
    and active_abilities(ctx.state.entities[i], 'deathrattle')
    and quote_unselected_cost(ctx.state, registry, ctx.state.entities[i]).amount <= 3
)
return (SummonFromStoredCandidates(
    ctx.player_id, cards, cause=SummonCause.capture(ctx),
),)
```

这是一次已捕获候选的选择，不会替卡牌在后面的任意窗口重算费用或条件。需要先执行其他改费或区域效果时，应在相应效果之后通过既有 `InvokeBehavior` 重新执行纯查询。旧引用在实体离区、变形、转控或离区再返回后不再命中新生命周期；派发时仅从仍符合原引用的候选中选择，不把旧引用升级为新引用。

非空且有场位时，用引擎唯一 RNG 对当前有效物理候选均匀选择，随后返回既有 `SummonStoredCard`。单候选沿既有随机召唤规则仍执行一次 `choice`；空池、全部引用失效或满场不消耗 RNG、不产生入场。未知定义和非随从候选即使满场也明确拒绝；重复实体或跨原区域的候选在构造/恢复时拒绝，不通过删去未知内容改变概率。

入场保留原实体、owner、存储材料和适用的当前能力，controller 由既有物理入场路径处理。不抽取、不疲劳、不支付目标随从费用、不执行它的战吼。可选位置、入场身材与实际来源复用已有参数和管线；有 `cause` 时沿既有物理接受收据处理，没有新召唤历史、数量计划或生命周期实现。来源在无候选/满场时也要有效，待选帧中的请求复用既有招募帧递归校验。

验证只使用一张必要真实来源与少量诊断随从，见 [专项](../tests/test_stored_candidate_summon_basics.py)。这是内部规则表达，尚非当前国服校准；完整卡池、其他特殊召唤来源与跨机制组合未由本增量认证。运行时为 `prototype-v283` / `core-effects-v277`，状态字段、schema247、观察82、命令12和 replay1 保持；旧运行身份由原守卫拒绝。实际执行结果和下一项只维护在 [项目状态](project-status.md) 与 [机制清单](mechanism-backlog.md)。
