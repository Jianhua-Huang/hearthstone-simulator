# M2：武器、英雄攻击与英雄技能

已装备武器的物理转控复用本页安装/替换/装备贡献及原死亡，新增明确安装引用而不重新创建材料。英雄已用次数保持、源转出不死亡，见[独立转控契约](m2-weapon-transfer.md)；临时取走返还、精准国服事件/计数按真实来源后置。

以下M2-04版本为历史基础：`prototype-v75` / `core-effects-v75`、快照schema74、代表包`representative-m5-v38`；当前运行时见项目状态。本页记录已实现的原型契约；国服目标补丁的精确规则仍待 M6 校准。进度与下一项见 [项目状态](project-status.md)。

受伤来源的当前武器攻击光环复用原装备层，声明、派生层及事件前规范化见[独立基础契约](m2-self-damaged-weapon-aura.md)。没有另一套装备、死亡、攻击次数或磨损处理器。

## 独立对象和位置

新增 `CardType.WEAPON / HERO_POWER` 与 `Zone.WEAPON / HERO_POWER`。玩家有可空的 `weapon_id / hero_power_id`，分别指向独立实体；它们不占随从位置。武器可以在手牌、牌库、装备位和墓地；英雄技能只在技能位或墓地，不能当普通手牌打出。

`PlayerSetup(weapon_card_id=..., hero_power_card_id=...)` 可明确设置初始装备和技能，旧场景不填时保持为空。初始化不会触发装备战吼或技能效果。实体、附件、来源、替换和使用状态进入快照及回放；类型/位置不匹配、重复位置、失效装备和派生缓存不一致均会拒绝。

武器定义使用 `attack` 和正数 `durability`，没有角色生命。当前本地原始记录用 `HEALTH` 标签承载武器耐久，代表适配器显式映射到 `durability`；卡牌数据快照仍保留原文。不能把武器塞进战场列表或用受到伤害的角色来模拟耐久。

实现位置：[装备模块](../hs_sim/engine/equipment.py)、[英雄技能模块](../hs_sim/engine/hero_powers.py)，结算器继续负责统一事件、死亡与事务边界。

## 武器与攻击

| 操作/状态 | 当前契约 |
| --- | --- |
| 从手牌打出武器 | 正常 `PlayCard`，支付费用，同一个实体移入装备位；允许满随从场面时装备，拒绝指定随从位置；执行 `on_play` |
| `EquipWeapon(player_id, card_id)` | 新建并装备武器，不支付卡牌费用，不触发武器战吼 |
| 替换装备 | 旧武器先保存死亡记录并离场，新武器安装后记录旧武器被摧毁；旧亡语通过普通死亡反应队列执行 |
| 攻击贡献 | 当前回合玩家的英雄获得武器攻击；对手回合不贡献。英雄自身的攻击增益独立相加，负武器攻击不会抵消自身增益 |
| 次数与冻结 | 英雄复用统一攻击规则、嘲讽/冻结检查和当回合次数；换武器不重置攻击次数。风怒武器可以提高当前上限 |
| 攻击耐久 | 成功进入伤害交换的主动英雄攻击消耗当时装备的一点耐久；打圣盾、零伤害也消耗，取消的攻击不消耗；被动受击不消耗 |
| `ModifyWeapon(target_id, attack=0, durability=0, source_id=None)` | 攻击增量记为附魔，耐久直接增减。可修复耐久，也可降至非正并由死亡检查摧毁 |
| `Destroy(weapon_id)` | 标记当前武器被摧毁，进入统一死亡检查；不是对武器造成普通角色伤害 |

武器的风怒、超级风怒、吸血、剧毒和攻击时免疫通过独立派生字段提供给当前回合英雄。吸血/剧毒在伤害准备时冻结，最后一点耐久也正常产生效果；这些武器属性不会泄漏给只是以英雄为来源的非战斗伤害。非当前回合武器不提供英雄攻击或这些关键词。当前武器贡献允许集为上述五项；攻击时免疫仍受原攻击窗口约束。集合外声明及未支持的授予明确拒绝，不能由武器载体推导更多战斗属性。

武器支持印刷/动态关键词、亡语和触发；授予的能力沿用附件到期与来源记录。武器触发在装备期间监听，离场后停止。武器亡语可从 `ctx.death` 读取死亡时攻击、耐久、控制者与附件；死亡记录的 `zone` 区分武器和随从。武器死亡不增加随从死亡事件，也不复生。

## 战斗边界与暂定规则

`DamageBatch` 可携带一个不可变 `CombatExchange(attacker_id, defender_id, weapon_id)`。只有匹配的双向战斗包才能使用该上下文；普通单体/法术伤害不携带它。它保存实际伤害阶段使用的武器，避免宣告攻击后替换装备仍扣错旧武器。

当前原型在同一伤害批次中完成双向伤害、固有吸血、耐久消耗和 `attack_finished` 事件，再统一检查随从/武器死亡与英雄终局。这保证致命攻击也会消耗耐久、武器也会离场。新阶段沿用可替换的 `DamageBatch` 分发；自定义替换处理器须承担整个批次契约，不能只保留伤害而遗失战斗上下文。

此顺序并未证明官方“攻击后触发—武器死亡—英雄终局”的全部窗口。武器替换时，普通触发先于旧武器亡语，亡语先于这次武器出牌的后续战吼；攻击宣告反应中换武器使用新武器结算；中途冻结取消攻击但保留已用攻击次数。这些具体选择登记为 R-011，M6 必须独立核对。当前终局仍会停止后续普通触发和亡语，不能把内部确定性误当作官方一致性。

## 英雄技能公开操作

`UseHeroPower(player_id, entity_id, target_id=None)` 是独立玩家动作。必须使用当前技能实体 ID，替换后的旧 ID 不会被悄悄解释成新技能。JSON 操作名为 `use_hero_power`，支持严格编解码、合法枚举、事务回滚和逐步回放。

```python
from hs_sim.engine import UseHeroPower

player = game.state.players[game.state.active_player]
game.apply(UseHeroPower(player.id, player.hero_power_id, target_id))
```

技能定义用 `on_use` 行为，初始化为对应能力实例，不能用 `on_play` 代替。使用时支付当前费用、增加当前技能与玩家的回合使用计数、发出 `hero_power_started`，执行行为后发出 `hero_power_used`；不产生 `card_played`。费用支付与出牌共用 v7 的统一报价/支付入口，已支持法力、生命、护甲和尸体账户；特殊例外仍待后续覆盖。

目标域、空目标策略、潜行/免疫保护与正常出牌共用 `targeting.py`。`Game.legal_targets` 支持查询当前技能；`legal_actions` 和执行校验调用同一使用条件。技能不需要目标时拒绝多余目标。技能伤害显式使用 `DamageKind.HERO_POWER`，不自动获得法术伤害加成。

定义的 `uses_per_turn` 默认为 1。可用 `requires_board_space=True` 表达召唤型技能的空间要求，使用实际规则里的场地上限；`register_use_rule` 可添加其他纯布尔条件。条件回调读取状态副本，异常或返回非布尔值明确失败。未知条件不能被当作永远可用。

| 原语 | 状态变化 |
| --- | --- |
| `ReplaceHeroPower(player_id, card_id)` | 旧实体移入墓地，新建技能实体，次数和上限取新定义；不触发死亡。玩家整回合累计使用数保留 |
| `RefreshHeroPower(player_id)` | 当前技能已用次数归零；不改变玩家累计数或使用上限 |
| `SetHeroPowerUses(player_id, limit)` | 修改当前技能上限，保留已用次数；当前是显式赋值，不是条件光环 |
| 切换回合 | 清理当前技能已用次数及玩家回合累计数；各自技能上限保留 |

替换是否刷新、技能结束事件在致命伤害或自身替换时的窗口、特殊一次性技能和持续条件修正仍需逐卡校准。本批没有实现被动/多按钮技能、挂起选择或整局技能升级系统；新卡不能假装由上述次数字段自动覆盖。

## 英雄替换基础

`ReplaceHero(player_id, card_id, armor=0, hero_power_card_id=None, health=None)` 是内部公共原语。创建新英雄 ID，旧英雄进入墓地但不产生死亡；保留普通附魔、非印刷能力、攻击次数与冻结，安装新英雄的印刷能力，继续使用原武器。默认保留剩余生命并限制到新上限，额外护甲加到原护甲上；显式 `health` 可指定新的剩余生命。技能参数为空时保留当前技能实体及其使用状态，否则通过 `ReplaceHeroPower` 替换。

这为 M4 英雄卡提供可测试基础。[从手牌打出英雄牌](m4-heroes-history.md) 已另实现并通过内部验收，但尚不覆盖加拉克苏斯等所有特殊替换语义。原语的新实体身份、继承附魔、冻结与英雄死亡边界由 R-012/R-038 跟踪，后续需根据目标卡版本校准。使用 `health` 设值不产生治疗事件；旧英雄的失效武器派生缓存会重新计算。

## 代表内容与验证

新增九个锁定本地记录：炽炎战斧 `CS2_106`、邪恶短刀 `CS2_082`、死亡之咬 `FP1_021`；火焰冲击 `HERO_08bp`、匕首精通 `HERO_03bp`、全副武装 `HERO_01bp`、援军 `HERO_04bp`、变形 `HERO_06bp`；白银之手新兵 `CS2_101t`。技能的生成内容也明确登记依赖，未注册候选仍报错。总计 32 条实验记录，均保持 `partial / internally_tested`，不宣称完整职业技能、构筑合法性或全卡池支持。

回归入口：[武器与技能组合](../tests/test_m2_equipment_powers.py)、[真实代表卡](../tests/test_representative_cards.py)。固定 [场景](../examples/scenarios/equipment-powers.json) 与 [动作](../examples/actions/equipment-powers.json) 演示武器替换、死亡之咬亡语、双方技能和英雄攻击；空牌库的抽牌按正常疲劳执行。

```powershell
python -m hs_sim simulate examples/scenarios/equipment-powers.json --actions examples/actions/equipment-powers.json --card-set representative --replay-out outputs/equipment-powers-replay.json
python -m hs_sim replay outputs/equipment-powers-replay.json --card-set representative
python -m unittest discover -s tests -q
```

schema 74 保存新位置、耐久、英雄武器派生状态、技能用量和武器死亡记录；旧 schema 1～73 明确拒绝。回放外层仍为 schema 1，起点为 schema 74；历史回放需相应原引擎，不能隐式套用新时序。M2-05 费用资源与 M2-06 伤害治疗规则已接入，实际测试结果与下一阶段 M3 统一维护在项目状态中。

M5-12c-02a：`TriggerHeroPower` 按执行时的当前位置触发技能；与 `UseHeroPower` 共用独立 `HeroPowerRecord` 和完成过程，付费/次数、目标/选择策略分开声明。`RuleContext.power` 提供捕获记录，技能回溯已接入，详见 [回溯契约](m5-power-rewind.md)，见 [激活契约](m5-power-activations.md)。

M5-12c-02b：英雄技能用 `on_use` + `Keyword.REWIND` + `RewindSpec` 声明每次激活的回溯预算；不支持手牌卡面链。内核统一处理检查点、费用/次数和结果关联 `power_id`，回调仅组合普通效果，见 [技能回溯契约](m5-power-rewind.md)。

M5-12c-03a：`passive_hero_power=True` + 普通 `TriggerSpec` 声明被动技能，不提供手动入口；技能区域监听按安装顺序捕获、开始前复核位置与能力身份。`is_first_play` / `played_cards(tribes_any=..., registry=...)` 查询固定卡牌身份，见 [被动技能契约](m5-passive-powers.md)。

M5-12d-01：主技能 `hero_power_id` 与有序 `additional_hero_power_ids` 分别保存；派生 `hero_power_ids` 供统一枚举，`AddHeroPower` 安装额外实体。手动动作、费用/次数、在位监听和观察/恢复处理所有已安装技能；刷新/替换/间接触发的空引用默认指主位；12d-02 已支持捕获引用的定向操作，见 [技能生命周期](m5-power-lifecycle.md)。见 [多技能契约与 R-107](m5-multiple-powers.md)。

M5-12d-02：`HeroPowerReference` 冻结安装身份；定向技能操作复核引用，过时引用跳过。安装成本在事件前提交；英雄替换显式声明保留/移除额外技能。观察 v42 新增移除事件。具体接口与 R-108 见 [技能生命周期契约](m5-power-lifecycle.md)。
