# M2：属性设值、交换与翻倍

真实水晶核心增加先于普通有序附件的有效基础层，原印刷/组件基数保留；既有场上组再接受一次普通设值并清除伤害，见[有限契约](m3-lost-city-rewards.md)。后文普通属性批次保留原范围。

真实卡牌应组合已有公共效果，敌方随从持续嘲讽仅增加有限声明范围；生命设值、连击复制、武器死亡、随机额外效果与牌库逆序继续共用原执行器。新增范围及待国服边界见[配方契约](m3-public-effect-consumers.md)，下文历史初始范围不覆盖此后新增形状。

对应 M2-03b。下文保留当时 `prototype-v75` / `core-effects-v75`、schema 74及 `representative-m5-v38` 的普通数值基础契约；当前运行时与实际执行以项目状态为准。本文是已实现、可回归的原型契约，尚未完成国服目标补丁的官方校准。总体进度见 [项目状态](project-status.md)。

## 数值的来源与顺序

属性真值仍是基础数值和有序的不可变 `Enchantment` 记录，不把最终攻击力写回基础属性。公共计算位于 [stats.py](../hs_sim/engine/stats.py)，由生命周期刷新调用：

1. 从实体的 `base_attack/base_health` 开始。
2. 按附魔获得顺序，分别执行攻击、生命的加法或设值。设值覆盖该属性之前的结果；之后的加法仍然生效。
3. 加上当前持续光环，攻击显示值最低为 0。
4. 当前生命为最大生命减去累计 `damage`。

例如基础 4 攻，先 +3 攻、再设为 1 攻、最后 +2 攻，结果是 3 攻。移除中间的设值后恢复为 9 攻；移除设值之前的 +3 攻则仍为 3 攻。有序列表是语义真值，附件 ID 单调增长；快照不能通过重排列表偷偷改变运算顺序。复制按原顺序分配新的附件 ID。

`attack_bonus/health_bonus` 仍为兼容现有实体接口的派生缓存，含义是“重算结果减去基础值”，不再等同于附魔增量之和。光环不进入永久附魔列表。

持续自身生命关系与[受伤时持续加攻](m2-self-damaged-attack.md)在普通数值层之后按各自关系契约计算，不写回数值附魔；以下“光环最后一层”描述仅指普通数值，不覆盖持续关系层。

## 公共效果

| 效果 | 执行契约 |
| --- | --- |
| `Buff(target_id, attack=0, health=0, ...)` | 按顺序添加有符号攻击/生命增量；负生命不作为伤害或生命设值，保留累计damage并由原死亡检查点处理 |
| `SetStats(target_id, attack=None, health=None, ...)` | 设置至少一项局部属性；另一项保持原状。整数操作数非负，也可使用 `StatReference` |
| `SwapStats(target_id, ...)` | 同时读取可见攻击、当前剩余生命，分别作为新的局部最大生命、局部攻击 |
| `DoubleStats(target_id, attack=False, health=False, ...)` | 在执行时读取选中属性，以当前攻击/剩余生命作为一次性增量，经注册分发进入 `Buff` |

这三个新效果均支持来源和绝对回合到期时间，目标为场上角色。卡牌自己的随从目标限制由 `TargetSpec` 或目标谓词控制。效果执行时目标已离场则记录跳过；来源不存在、附件已过期或参数非法会明确失败，整个外部操作回滚。

`StatReference.ATTACK / HEALTH / MAX_HEALTH` 分别表示执行时的可见攻击、剩余生命、最大生命。复合指令的所有引用先一起读取，再写入结果。例如：

```python
from hs_sim.engine import StatReference
from hs_sim.engine.effects import Damage, SetStats

def injured_attack(ctx):
    return [
        Damage(ctx.target_id, 2, ctx.source_id),
        SetStats(ctx.target_id, attack=StatReference.HEALTH, source_id=ctx.source_id),
    ]
```

第二条指令读取第一条伤害及其反应完成后的生命值。直接提前把 `ctx.state` 中的生命读成整数，含义则是回调当时的快照，不能用于需要后续实时读取的规则。

附魔只保存解析后的 `set_attack/set_health` 整数或加法量，不保存表达式。每个属性不能在同一记录里同时有非零加法和设值。普通刷新、光环变化、加载存档不会再次执行交换/翻倍，也不会让心灵之火持续跟踪后续生命变化。一般持续乘法、费用设值和任意条件持续时间不在本批范围内。

## 生命、受伤和光环

这些边界作为原型规则明确记录，不能当作最新官方规则的证明：

- 设定最大生命（包括交换）时，清除累计伤害；单独设攻击不清伤害。这是一次属性修改，不发出治疗事件，也不触发吸血。
- 翻倍剩余生命采用一次加法，保留伤害。例如最大 7、受伤 3、剩余 4，翻倍后最大 11、受伤仍为 3、剩余 8；之后普通治疗最多恢复到 11。
- 光环是最后一层。基础 4/7 受到 +1/+2 光环后为 5/9；交换读取 5/9，保存局部 9/5，重加光环后为 10/7。心灵之火读取可见生命后，攻击光环仍会继续叠加。
- 翻倍会将施加时已有光环贡献读入一次性增量。上述随从翻倍生命后为 18 血，随后光环消失为 16 血；刷新不会再翻倍。
- 零攻击随从交换后可能达到 0 最大生命，随后统一死亡检查执行亡语/复生；不会把生命悄悄钳制为 1。0 攻交换导致死亡有历史官方说明支持，但这不能证明受伤、光环或当前补丁的全部细节。[官方开发者说明](https://hearthstone.blizzard.com/en-us/news/10463005)

移除属性附魔沿用 [生命周期契约](m1-lifecycle.md)：重新执行剩余有序记录。若最大生命下降，保留原剩余生命并钳制到新上限；若上限不降，保留当前 `damage`。因此移除一个降低生命上限的设值可能增加剩余生命，不会恢复设值前的旧伤害。临时设值并不是“整份旧实体状态备份”，中间发生的伤害和之后的附魔不会被撤销。

沉默删除允许移除的设值和增量，外部光环保留。当前复制保留已解析操作数、相对顺序和伤害；基础复制、回手、洗入、变形按既有策略重置。转控保留附魔并按新场面重算光环。复生不继承额外属性附魔。死亡记录保存死亡当时的有序附魔与最终数值。

## 代表卡和验收

三条新增记录均从已验证 SHA256 的本地源文件提取，锁定原始记录和独立适配器指纹：

| 卡牌 | 公共机制 |
| --- | --- |
| 心灵之火 `CS1_129` | `SetStats(attack=StatReference.HEALTH)` |
| 神圣之灵 `CS2_236` | `DoubleStats(health=True)` |
| 疯狂的炼金师 `EX1_059` | `SwapStats`，无其他合法随从时仍能打出 |

机制测试见 [属性组合测试](../tests/test_m2_stats.py)，真实出牌测试见 [代表卡测试](../tests/test_representative_cards.py)。覆盖运算顺序、受伤、光环、零生命死亡、临时移除、沉默、复制/重置、来源错误、RNG 回滚、存档篡改和回放。官方精确交互仍列入 R-010，三张卡维持 `partial / internally_tested`。

可运行 [场景](../examples/scenarios/stat-operations.json) 和 [动作](../examples/actions/stat-operations.json)：森金持盾卫士依次受到寒冰箭、神圣之灵、疯狂的炼金师、心灵之火和沉默。攻击/剩余生命依次为 3/2 → 3/4 → 4/3 → 3/3 → 3/5。

```powershell
python -m hs_sim simulate examples/scenarios/stat-operations.json --actions examples/actions/stat-operations.json --card-set representative --replay-out outputs/stat-operations-replay.json
python -m hs_sim replay outputs/stat-operations-replay.json --card-set representative
python -m unittest discover -s tests -q
```

schema 74 严格保存新操作数字段；旧 schema 1～73 明确拒绝，需原引擎或未来显式迁移器。外层回放仍为 schema 1，当前起点为 schema 74；更换原型版本时不能将旧摘要当作可兼容结果。


## K469 原生英雄攻击与小鬼数量关系

MIS_710和REV_242只在CardDefinition.stat_relations声明一个原生普通非融合随从关系。新增CONTROLLER_HERO_ATTACK、CONTROLLER_IMP_COUNT操作数只允许target=ATTACK、CONDITIONAL_ATTACK、amount=1；不允许额外计数条件、混合声明、动态授予、可消费或有期限的非原生能力。关系共用现有conditional_attack层，不写永久Buff或基础攻击，不增加状态字段。

英雄输入读取控制方当前hero.attack。原条件武器先算出自身攻击，再经refresh_equipment发布当前装备贡献，失活的对方回合武器不算入；不得改用包含失活武器的total_hero_attack。事件规范化先保留既有关键词/受伤武器光环顺序，在光环提交后再刷新英雄依赖；新回合捕获前同样更新装备与跟随者。没有任意表达式图或第二套装备执行器。

小鬼数量使用原MinionScope(BOARD, subtypes_any=('imp',))及当前卡面的印刷分类，未知必要信息明确失败。来源只在BOARD且原生能力活跃时贡献，候选沿原活跃、正生命、非待消灭政策；沉默/转控/当前复制/回手/变形/休眠仍复用原生命周期。场外来源及休眠/待死小鬼是否应计入仍须国服37.0校准，不能从内部测试推定官方规则。当前关系版本和实际证据只在两份原台账记录；[完整真实数据](../data/cards/past-continuous-attack-v1.json)保留该政策边界。
