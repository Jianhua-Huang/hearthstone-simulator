# 受伤时持续增加攻击力

独立基础契约 B32/U22。扩展现有 `StatRelationSpec`、[公共属性计算](../hs_sim/engine/stats.py)和[属性关系校验](../hs_sim/engine/stat_relations.py)，不增加属性执行器、伤害监听器、永久攻击缓存或玩法事件。原有属性设值、生命和移除政策见[属性契约](m2-stats.md)与[生命周期](m1-lifecycle.md)。实际执行、验收和下一项只维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。

## 声明与计算

```python
from hs_sim.engine import StatRelationSpec, StatRelationOperand, StatRelationLayer

while_damaged = StatRelationSpec(
    operand=StatRelationOperand.SELF_DAMAGED,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,
    amount=3,
)
# 普通随从 CardDefinition(..., stat_relations=(while_damaged,))
```

这是单个印刷随从能力：累计 `damage > 0` 时具有声明的额外攻击力。`amount` 必须是严格正整数；布尔、浮点、其他目标、错误层或未知操作数明确拒绝。既有 `SELF_CURRENT_HEALTH / FINAL_ATTACK` 保持原政策，新字段 `amount` 必须为 0。没有任意表达式图、附加条件或实体之间的数值依赖。

当前攻击力查询先取原有序数值附魔与当前属性光环，再加受伤条件的数值，最后执行零下限；底层基础攻击、数值附魔、光环和伤害均不被改写。普通无关系的英雄、武器和随从保持原计算。既有最终自身生命关系继续按原最终层计算；本批不新增跨机制组合或组合测试。

因此连续受伤不会反复永久叠加，部分治疗仍保留加攻，恢复满血撤销加攻，再次受伤重新生效。零伤害或被防止的伤害不激活。条件使用已有生命结算结果：最大生命增益保留伤害；既有设定生命政策清除伤害；生命附魔或光环移除可能按原钳制政策让实体恢复满血，条件随之撤销。它不依赖某次伤害/治疗事件曾否发生。

## 生命周期、战斗与保存

仅印刷普通、非融合随从声明通过既有载体校验。新条件动态授予明确不支持，原 `GrantStatRelation` 只继续接受已有自身生命关系；不为可选授予提前扩充载体和来源。

沉默移除能力，保留原健康结算；当前复制按原策略保留伤害、沉默、印刷来源身份 并分配新附件 ID，条件只读取复制体自己，不读取来源实体。基础复制、回手和变形按既有重置政策安装本体能力；转控保留自身条件。离场后实体属性查询沿用既有纯显示政策，不使其成为可攻击对象。休眠、融合或特殊复制的完整真实来源与国服显示政策仍需按卡核查，不能由普通载体的支持推断整族完成。

攻击声明后、伤害准备前发生的健康变化由共享攻击管线按当前攻击力取值；已经准备的攻击和反击伤害保持原数值，不因本次交换受伤再改写。死亡历史保存当时的可见攻击。原 `DeathRecord` 的“攻击等于剩余生命”约束只适用于既有最终自身生命关系，不能套在受伤加攻上。

所有声明继续放在原 typed 附件中，序列化沿用原显式关系解码与严格完整字段检查。`amount` 进入附件、私有工作帧及关系声明的指纹；本受伤profile不新增 GameState、Entity 或 Player 字段。当前 `prototype-v201 / core-effects-v195 / schema189` 严格拒绝旧 schema1～188。普通空关系注册表的完整卡牌指纹保持；带关系定义的指纹相应改变。观察74、命令11、回放1接口保持。玩家可见当前攻击，不能获得关系公式、私有帧或附件来源。

## 真实需求和证据限制

仅将完整本地 `EX1_393` 阿曼尼狂战士固定到[证据包](../data/support/self-damaged-attack-basics.json)，pin为 `80ad786d0038478f6c388bc0b034f8f829b6a38a00fab9df7474445785b313a0`，以隔离实验适配验证 2费2/3、受伤时+3攻击；没有批量接卡。`VAN_EX1_393` 只作历史卡文证据，没有新执行适配。

官方索引中的[阿曼尼卡文](https://hearthstone.blizzard.com/en-gb/cards/790-amani-berserker/)支持受伤期间加攻。[官方激怒调整说明](https://hearthstone.blizzard.com/en-gb/news/21614307)确认删除激怒关键词时保留原效果，并区分持续受伤能力与每次受伤触发。这些资料不证明国服目标补丁的精确属性层序、事件窗、死亡/非活动显示或特殊来源政策。

狼人受伤时风怒已由[独立关键词契约](m2-self-damaged-keyword.md)表达，其他条件关键词、其他条件及特殊来源仍分别开放；本批不将受伤加攻宣称为整个 U22 完成。数值层序、既有生命钳制、非活动显示及准确战斗窗口为受限原型政策，待 M6 国服校准。M0 完整正式池和 M7 批量接卡继续保留。

原事件前规范化现在也处理[受伤来源的当前武器攻击贡献](m2-self-damaged-weapon-aura.md)；本页自身条件范围和原生命周期政策保持。

装备武器时自身冲锋由[独立武器条件契约](m2-weapon-presence-keyword.md)表达；其GameState依赖另用Entity.conditional_keywords派生集合。此扩展不改变本页受伤profile的本地条件与生命周期政策，未登记的条件或新条件授予仍拒绝。

装备期间自身持续加攻击由[独立武器数值契约](m2-weapon-presence-attack.md)表达，Entity.conditional_attack只保存自身状态依赖。此扩展不改变本页既有profile的数值/关键词/生命周期政策，条件授予仍按原支持范围拒绝。

原生种族受益筛选见[独立冲锋光环契约](m2-tribal-keyword-aura.md)；本页既有自身条件和数值政策保持，新选择器不扩展本页条件授予范围。

原生当前种族的持续属性筛选见[独立属性光环契约](m2-tribal-stat-aura.md)。本页既有条件和生命周期政策保持，未扩展授予或条件组合。

原生当前种族的持续费用筛选见[独立费用光环契约](m2-tribal-cost-aura.md)。本页既有数值/关键词和生命周期政策保持，未扩展授予或条件组合。
