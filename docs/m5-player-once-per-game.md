# M5：玩家每局一次约束的既有表达

本地五条明确“每局对战限一次”的原行见[固定材料](../data/support/player-once-per-game-basics.json)：哈斯·石酒两身份、摄影师菲兹尔、大法师罗曼斯和扎里米。它们使用玩家级次数，不能用随从实例上的一次触发代替；新实体、回手重打及来源离场不会自动获得新的整局次数。

现有 `PlayerEffectSpec(kind='persistent')` 可以保存来源无关的标记，`AddPlayerEffect` 负责实际提交。必要实验的战吼主体先检查当前玩家是否已有该标记，再核对真实条件；不符合条件直接结束，符合条件才先返回标记提交，随后执行主体。标记与其他效果同处原事务、等待帧及回溯状态，不添加新账户、状态字段或次数执行器。

```python
registry.register_player_effect(
    PlayerEffectSpec('game.used.zarimi', 'TOY_385')
)

# Necessary experimental body, after its own eligibility was established:
effects = (
    AddPlayerEffect(context.player_id, 'game.used.zarimi', context.source_id),
    QueueTurns((context.player_id,), context.source_id),
)
```

实验仅接入扎里米的付费手牌战吼。条件复用 `played_cards`，依据此前真实提交身份的龙牌记录，排除当前出牌记录；达到8张后标记并安排一次额外回合。先前来源移除不会删除标记，另一物理复制也使用同一玩家标记；不同玩家的效果集合独立。当前“其他龙牌”的记录依据、精确门槛和标记继承政策仍须国服校准。

这条顺序配方使用现有规则上下文和解释器，不新增通用“整局次数”模块。必要验证覆盖未满足条件不占用、两物理实体共用次数、来源死亡、实际新回合、等待恢复、回放、支付/队列/标记回滚和玩家信息边界。没有穷举战吼重复、借用、历史/间接来源，也不据一张代表推称另外四种完整主体已适配。此实验对缺少真实手牌出牌上下文的间接调用明确报错。

标记为玩家持久规则事实，展示沿旧玩家效果 DTO，仅含规则键和卡牌身份；不会暴露全局附件 ID、来源实体或进入顺序。新实验注册表另有指纹，生产代表包及内核 `prototype-v267` / `core-effects-v261`、schema234保持。

实际执行、差异和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。正式完整池、其他来源、国服校准和批量接卡继续保留。
