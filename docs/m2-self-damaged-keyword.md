# 受伤时持续拥有风怒

独立基础契约 B33/U22。扩展[现有关键词声明与校验](../hs_sim/engine/keyword_auras.py)、[本体刷新](../hs_sim/engine/lifecycle.py)与[原事件前规范化](../hs_sim/engine/event_normalization.py)，复用[攻击次数规则](../hs_sim/engine/attack_policies.py)。没有新的属性解释器、攻击计数器、永久关键词授予、玩法事件或玩家操作。实际执行与下一项只维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。

## 声明与当前范围

```python
from hs_sim.engine import Keyword, KeywordAuraSpec

while_damaged = KeywordAuraSpec(
    Keyword.WINDFURY,
    target='self',
    condition='self_damaged',
)
# 普通随从 CardDefinition(..., keyword_auras=(while_damaged,))
```

`condition` 默认严格字符串 `always`，旧外部与手牌光环保持原声明、作用范围及重算。新增声明仅接受已知自身受伤风怒：`target='self' / condition='self_damaged' / Keyword.WINDFURY`。自身声明不能附加物理相邻或包含自身选项；本受伤profile仅允许风怒；另一已知武器条件见末节链接，未登记条件、其他条件关键词和消耗型关键词明确拒绝，不自动退化为无条件能力。

该声明仅安装为可沉默的印刷普通非融合随从附件。注册表核对本体，恢复时绑定原卡面声明，拒绝重复原生附件、授予标记、已消费、到期、无来源或不可沉默形状。复制沿用原来源身份并重新分配附件 ID；条件只读复制体自身，不读取来源实体。新条件不允许 `GrantKeywordAura`，旧 `always` 授予保持原语义。

当前能力不是外部贡献：原 `refresh_entity` 在实体活跃且 `damage > 0` 时，将它并入本体、已有永久、武器和外部关键词的集合。它不写 `aura_keywords`，不创建新的 `keyword` 附件，不重复增加攻击次数。自身条件消失不会清除另一来源的同名关键词。普通外部光环刷新跳过自身声明；原手牌贡献流程保持。

## 健康、事件与攻击次数

部分治疗保留，满血撤销，再次受伤恢复；零量或被防止的伤害不激活。健康设值、最大生命增益、光环撤销钳制和沉默继续使用既有健康政策。

只在效果尾部刷新会使伤害/治疗结果回调保存旧关键词。原 `normalize_event_state` 在复制事件上下文前，仅重算携带新自身条件的实体；没有新事件、随机、分配或效果执行。批次的主要健康包仍按原准备/结算策略执行，结果回调读取完成主要包之后的共享状态。已有无条件光环不因此提前重新选择外部来源。

当前 `attack_limit` 与 `has_action_remaining` 保持原最大次数和已消费次数的比较。狼人受伤后最大次数从 1 变为 2；已经攻击过一次仍可进行一次额外攻击。满血使最大次数回到 1，不退还已使用次数；恢复受伤最多重新开放原剩余机会。已经使用两次后，治疗再受伤不能获得第三次攻击。实际新本人回合才按原规则重置次数。风怒不提供冲锋，新打出或召唤的狼人仍受原召唤限制。

攻击声明期间与准备后的健康变化保持原攻击管线和冻结的伤害包政策。本批不修改攻击接受、重验证或强制攻击规则。休眠抑制自身能力，唤醒按当前伤害重算；基础复制、回手、变形重置，当前复制和转控按原保留策略执行。死亡记录冻结当时的有效关键词，离场后的纯显示沿用既有活跃/休眠与印刷能力政策，不能据此认证国服显示规则或所有特殊来源。

## 保存、玩家接口与必要代表

新 `condition` 字段进入原 `KeywordAuraSpec` 显式完整解码、工作帧及非空关键词声明指纹；缺失或未知字段、错误条件、非本体形状和陈旧有效关键词缓存明确拒绝。本受伤profile不新增 GameState、Entity 或 Player 字段。当前 `prototype-v201 / core-effects-v195 / schema189` 拒绝旧 schema1～188；观察74、命令11、回放1保持。玩家看到当前关键词与合法攻击，不能获得条件声明、内部附件或私有帧。

只新增完整本地 `EX1_412` 暴怒的狼人[证据包](../data/support/self-damaged-keyword-basics.json)，pin为 `cd302e20447dfcf40570b6880980e650c77664351a4bba332f8ae4b2954694a8`。3费3/3的隔离适配用本体受伤风怒声明，受伤+1攻击直接复用[已有数值能力](m2-self-damaged-attack.md)；没有另一套狼人处理器。`VAN_EX1_412` 只作历史证据，没有新执行适配或批量接卡。

[官方狼人卡文索引](https://hearthstone.blizzard.com/en-us/cards/1155-raging-worgen/)支持受伤期间+1攻击及风怒。[官方激怒调整说明](https://hearthstone.blizzard.com/en-gb/news/21614307)支持保留持续条件效果。它们不证明国服目标补丁的精确关键词窗、攻击接受/重验证窗口、既有健康钳制或非活动显示。其他条件关键词、特殊授予、融合来源、完整 U22、M0 正式有效池、M6 国服校准和 M7 批量接卡仍开放。

原事件前规范化现在也处理[受伤来源的当前武器攻击贡献](m2-self-damaged-weapon-aura.md)；本页自身条件范围和原生命周期政策保持。

装备武器时自身冲锋由[独立武器条件契约](m2-weapon-presence-keyword.md)表达；其GameState依赖另用Entity.conditional_keywords派生集合。此扩展不改变本页受伤profile的本地条件与生命周期政策，未登记的条件或新条件授予仍拒绝。

装备期间自身持续加攻击由[独立武器数值契约](m2-weapon-presence-attack.md)表达，Entity.conditional_attack只保存自身状态依赖。此扩展不改变本页既有profile的数值/关键词/生命周期政策，条件授予仍按原支持范围拒绝。

原生种族受益筛选见[独立冲锋光环契约](m2-tribal-keyword-aura.md)；本页既有自身条件和数值政策保持，新选择器不扩展本页条件授予范围。

原生当前种族的持续属性筛选见[独立属性光环契约](m2-tribal-stat-aura.md)。本页既有条件和生命周期政策保持，未扩展授予或条件组合。

原生当前种族的持续费用筛选见[独立费用光环契约](m2-tribal-cost-aura.md)。本页既有数值/关键词和生命周期政策保持，未扩展授予或条件组合。
