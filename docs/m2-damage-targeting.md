# M2 首批：伤害类别、法术伤害与目标域

本批实现对应 M2-01 与 M2-02 的公共基础。运行时为 `prototype-v75` / `core-effects-v75`，快照 schema 74；真实代表包为 `representative-m5-v38`。本文件记录可执行原型契约，尚未完成国服官方时序校准。总体阶段和后续工作见 [项目状态](project-status.md)。

## 1. 明确伤害来源的类别

`Damage(target_id, amount, source_id=None, kind=DamageKind.EFFECT)` 与 `RandomDamage` 使用显式 `DamageKind`：

| 类别 | 当前处理 |
| --- | --- |
| `EFFECT` | 普通效果伤害，不使用法伤；也是旧三参数调用的默认值 |
| `SPELL` | 使用来源控制者的可叠加法伤；来源必须存在且其定义为法术 |
| `COMBAT` | 普通攻击与反击的伤害，由攻击内核填写；不使用法伤 |
| `HERO_POWER` | 技能伤害类别，不使用法伤；这里只建立伤害分类，尚未实现使用技能的动作 |
| `FATIGUE` | 疲劳伤害，没有来源实体；不使用法伤 |

不要根据来源的 card_id 或卡牌类型自动猜伤害类别。同一法术产生的直接伤害、延迟触发和被指令执行的其他伤害不一定共享修正规则，应由行为作者明确选择。攻击内核和疲劳内核已填写各自类别；不存在的来源 ID 会导致事务失败，而非静默损失来源信息。

例如真实火球术的行为是：

```python
from hs_sim.engine import DamageKind
from hs_sim.engine.effects import Damage

def fireball(ctx):
    return [Damage(ctx.target_id, 6, ctx.source_id, DamageKind.SPELL)]
```

单体、随机选择后的伤害与攻击都进入统一 `DamageBatch`。当前没有任意重定向、伤害替换、倍率层或治疗转伤害；这些仍属于后续 M2。新增策略应在公共处理层设计，不能逐卡重复修改生命。

## 2. 法术伤害是当前能力实例

`CardDefinition(spell_damage=1)` 安装印刷 `AbilityInstance(kind='spell_damage', spell_damage=1)`。`GrantSpellDamage(target_id, amount, source_id=None, expires_turn=None)` 给场上角色授予独立、可沉默、可到期的实例。数值必须为正整数，重复来源加法叠加。

在每批伤害开始前，汇总来源控制者当前在场、存活且未被标记消灭的英雄/随从所持有的有效法伤。手牌、牌库、墓地和敌方法伤不计入。该能力沿用 M1 的复制、转控、回手、变形、沉默与到期语义；印刷值不绕过当前能力实例。

`combat.py` 将伤害指令准备成不可变 `PreparedDamage`，冻结来源控制者、关键词和法伤加成。一整批开始后不因其中一个法伤来源被击杀而改变后面的伤害；若行为返回多条独立 `Damage`，前一条的死亡已结算，下一批会重新计算。两种写法不是同一种时序。

当前加法约定为 `修正后伤害 = 指令基础值 + 法伤`，包括显式创建的零基础法术伤害指令。如果某张特殊牌在条件不成立时根本不应产生伤害，其行为应返回空效果；不能用 `Damage(..., 0, kind=SPELL)` 代替“没有伤害指令”。该边界及分段/随机多段法术的加成粒度要在对应卡接入时逐项校准，不能只按文本自动生成。

普通效果、战斗、疲劳和技能类别不使用法伤，治疗也不使用法伤。按法术派系提供加成、负法伤和任意倍率尚未实现。

## 3. 伤害结果和事件

处理器先产生不可变 `DamageResult`，再统一更新目标。顺序是修正基础值、零伤害、免疫、圣盾、护甲吸收、生命伤害；因此免疫不消耗圣盾，零普通效果伤害也不消耗圣盾。剧毒依旧仅在造成生命伤害时标记随从消灭。

`damage_dealt.amount` 是未被防止的总伤害，包含护甲吸收和超过剩余生命的部分。它不是“实际扣掉的正生命上限内的数值”。`damage_dealt` 与 `damage_prevented` 的 `data` 现在包含：

- `damage_kind`、`source_controller`：伤害类别与批次准备时的控制者。
- `base_amount`、`spell_bonus`、`modified_amount`：修正过程。
- `armor_absorbed`、`health_damage`：各处承受的数值；防止时均为零。

防止事件另含 `reason`。整批更新后才捕获普通事件观察者并进行死亡检查，沿用原型既定结算顺序。结果结构提供公共计算依据，当前已基于它实现固有吸血，详见 [战斗状态契约](m2-combat-status.md)。

## 4. 目标域和是否必须选择

卡牌可设置不可变 `TargetSpec`：区域 `zones`、卡牌类型 `kinds`、关系 `relation`（any/friendly/enemy）、是否排除来源实体 `exclude_source`，以及目标模式 `mode`。

| 目标模式 | 空目标何时合法 |
| --- | --- |
| `REQUIRED` | 永不合法；没有候选则不能出牌 |
| `IF_AVAILABLE` | 只有当前没有合法候选时可以省略；有目标时必须选择 |
| `OPTIONAL` | 始终允许省略，同时可选合法候选 |

`IF_AVAILABLE` 用于当前代表包的指定目标战吼。判断依据是**打出前**已经过滤后的合法候选，刚打出的随从不会自动成为自己的候选。牌仍正常入场、支付费用并执行 `on_play`，回调收到 `target_id=None`，应跳过需要目标的那部分效果，不能把整个战吼一概跳过。

```python
from hs_sim.engine import CardDefinition, CardType, TargetMode, TargetSpec, Zone
from hs_sim.engine.effects import Silence

def battlecry(ctx):
    return [] if ctx.target_id is None else [Silence(ctx.target_id)]

card = CardDefinition(
    'example.owl', '测试战吼', CardType.MINION, health=1,
    on_play='example.silence',
    targeting=TargetSpec(TargetMode.IF_AVAILABLE,
                         zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
)
```

仍需注册示例行为 ID。`target_rule` 可额外注册纯判断函数，必须返回严格 bool；默认 `any_entity` 只作最后的存在检查。明确区域和类型由 `TargetSpec` 负责，不能再将一切强制当作活体角色。因此可表达手牌法术、牌库中的随从等非角色目标；战场/英雄目标仍要求存活，敌方免疫目标不可主动选择。

原 `requires_target=True` 保留兼容 API，映射为必选活体角色目标；不能与 `targeting` 同时声明。没有这两种声明的牌不接受目标。

`Game.legal_targets(entity_id)` 返回当前行动方手中该牌的目标实体 ID，不表示费用足够或战场有空位。`legal_actions()` 与执行校验共用 `targeting.py` 的规则。谓词异常不是“没有候选”，会明确失败；谓词得到深拷贝，不能修改权威状态。

当前状态/API 是全知接口。指定牌库/手牌区域不自动建立玩家可见信息、揭示流程、发现候选或可序列化选择；这些仍归 M3。实际卡牌必须按其规则定义区域，不应把此接口当作任意查看敌方隐藏牌的产品功能。

## 5. 代表卡与验收

实验包已有 32 个真实 ID，新增血法师的法伤和亡语抽牌；火球术使用基础 6 加当前法伤；猫头鹰、中士和破碎残阳祭司使用条件必选目标。其余尚未注册的卡继续明确拒绝。完整标准/狂野合法性与官方一致性仍未声明。

```powershell
python -m hs_sim simulate examples/scenarios/spell-damage.json --actions examples/actions/spell-damage.json --card-set representative --events --replay-out outputs/spell-damage-replay.json
python -m hs_sim replay outputs/spell-damage-replay.json --card-set representative
```

这个固定场景执行：血法师在场时火球造成 7，沉默血法师，第二张火球造成 6。测试同时覆盖多个法伤来源、同批/分段伤害、能力消失、控制者变化、护甲/圣盾/免疫、非角色目标、非法操作回滚、快照及重算。对应 [伤害测试](../tests/test_m2_damage.py)、[目标测试](../tests/test_targeting.py)、[代表卡测试](../tests/test_representative_cards.py)。实际测试数量在项目状态维护。

当前能力与有序属性字段要求 snapshot schema 74。旧 schema 1～73 明确拒绝，需原引擎读取，没有自动迁移；回放外层仍为 schema 1。规则/处理器/卡包版本和指纹都参与恢复校验。吸血、冻结、潜行、生命光环与属性运算已经追加实现；武器/英雄技能已接入，资源及一般伤害/治疗规则已接入，M3-01 挂起选择/结算帧也已接入，只读信息视图已接入，受限玩家动作也已接入，静态版本池已接入，区域操作及区域内候选已接入，交易/锻造额外手牌操作已接入，星舰基础链路已内部验收，地标通用入口与星港已内部验收，英雄牌/雷诺发射历史已内部验收，一般休眠与唤醒已内部验收，泰坦能力也已内部验收，任务/任务线进度也已内部验收，持续目标与玩家长期效果也已内部验收，奥秘与打断窗口已内部验收，M5-01 初始依赖盘点、出牌历史/连击/流放已内部验收，M5-02 法术迸发/暴怒与有限次触发已内部验收，M5-03 存储升级、手牌进度/腐蚀/注能已内部验收，M5-04 额外出牌条件已内部验收，M5-05 磁力已内部验收，M5-06 巨型已内部验收，M5-07a 兆示基础已内部验收，M5-07b-01 相邻光环/生成费用及三职业代表已内部验收，M5-07b-02 术士相邻牺牲已内部验收，M5-07b-03a 死亡之翼/奥卓克希昂已内部验收，M5-07b-03b-01 古加尔牌库销毁已内部验收，M5-07b-03b-02 关键词光环/艾萨拉已内部验收，M5-07b-03b-03 奥拉基尔已内部验收，M5-07b-03b-04 希奈丝特拉已内部验收，M5-07b-03b-05 奥妮克希亚已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)，保留公共机制优先与集中校准后置的顺序。
