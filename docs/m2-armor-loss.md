# 直接减少与清空英雄护甲

破甲骑士要求摧毁对手全部护甲；冰冻盾牌要求失去固定护甲。这是英雄账户变化，不能用伤害或费用支付代替。执行结果与下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

## 指令与当前账户

```python
LoseArmor(player_id=2, amount=5, source_id=source)
LoseArmor(player_id=2, amount=None, source_id=source)  # 清空
LoseArmor(player_id=2, amount=5, source_id=source, on_result='consumer')
```

数量只接受非负整数，排除布尔值；`None` 显式表示全部。执行时读取指定玩家当时安装的英雄和实际护甲，固定数量扣除 `min(当前护甲, 请求量)`，全部则扣除当前余额。护甲不变成负数，不另设玩家护甲缓存。来源可空；需要回调时必须提供物理来源，未知来源或行为明确报错。

免疫、圣盾、伤害减免与重定向不介入，生命及上述防护保持。它不产生伤害、生命损失或费用支付事实。原 `GainArmor`、伤害吸收、护甲费用支付继续使用各自规则；本操作不重定义这些规则的事件。

## 不可变结果与反应

`ArmorLossResult` 保存六项：`player_id / hero_id / requested / before / after / actual`，满足 `actual=min(before, requested)`（全部为 `before`）和 `after=before-actual`。每次操作发布内部 `armor_loss_resolved`，包括零实际量；只有正实际量紧接发布 `armor_lost`。

可选回调沿原行为解释器执行，通过 `RuleContext.armor_result` 读取完整类型化结果。普通已捕获反应先执行，回调保留扣除提交时的上下文和实际量。反应后来增加护甲不会改写本次 `before/after/actual`；后续独立扣除重新读取实时余额。此事件顺序是明确的本地契约，尚未做国服精确时序校准。

## 恢复、回放与信息

没有新的持久状态字段或运行模块。结果保存在原事件与必要行为帧中，原 JSON 恢复、克隆、回放、待选续行和事务回滚共用。直接动作失败回滚整个动作；后续选择失败保留已提交等待边界。事件读取校验完整字段、数值关系、英雄身份和正量事件配对；帧解码校验结果结构。未签名快照不提供外部来源认证，也不据这份结果重建全局历史护甲余额。

玩家仅接收普通 `armor_lost` 的公开数量与既有观察引用；内部结果及其原始实体编号不向玩家输出。公开观察中的当前英雄护甲仍沿原 getter；后续反应后的余额和本次公开减少量可同时存在。新增公开事件种类，因此观察版本为 `player-view-v78`，命令12和replay1保持。

语义版本 `prototype-v276 / core-effects-v270 / schema242`，旧1～241存档须用原引擎。默认生产注册表不增加卡牌，不改变指纹。

## 来源与限度

[五条完整本地来源与固定 pin](../data/support/armor-loss-basics.json)保留 DRG_069、AV_109、MIS_902、TTN_803、YOG_500。仅 DRG_069 破甲骑士作为必要完整隔离代表；其他四条只提供真实直接扣除与实际量需求，延迟、后续减费、重复和重召等具体主体后置到接卡。本项不建立组合任务，不代表完整卡池或当前国服规则认证。
