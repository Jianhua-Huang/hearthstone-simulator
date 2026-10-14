# Entity / Player 数值与战斗辅助规则反编译分析

本轮目标是传统炉石战斗机制，不是卡牌目录。客户端确实包含可离线复用的**局部数值计算、状态判断、结果预览规则**；已找到并实际编译运行若干原反编译方法体。但本次检查的类没有提供“输入出牌/攻击 → 独立执行效果、触发、伤害、死亡 → 新状态”的完整机制。

不能把“客户端接收服务器结果”概括成“客户端没有任何规则”。也不能把文本数值公式、攻击预览函数误认成权威战斗结算。

## 取证范围

- 只读安装文件：`D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll`
- SHA-256：`EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B`
- 工具：ILSpy CLI `11.1.0.9782`，按类型定向反编译。
- 类型：`Entity`、`EntityBase`、`EntityDef`、`Player`、`GameState`，以及追踪公式调用所需的 `TextUtils`、`CardTextBuilder`。
- 实际基类名为 `EntityBase`，没有名为 `BaseEntity` 的对应类型。
- 源码保存于 `reports/decompiled/entity/`，该目录已被 `.gitignore` 排除。下列行号均指本次输出的反编译 C# 文件。
- 没有启动、注入或修改游戏；没有读取用户对局日志，没有连接游戏服务器。

## 能复用什么

| 方法和源码行号 | 实际行为 | 可复用程度与限制 |
| --- | --- | --- |
| `Player.TotalSpellpower`，`Player.cs:275–320` | 通用法伤 − 负法伤 + 对应派系法伤 + 临时通用/派系法伤 + 该实体额外法伤；奥秘/符咒排除临时部分 | 可抽成纯数值函数。但输入 `CURRENT_*` 标签已是汇总值；此方法不扫描随从来生成光环、不处理光环增删、不执行伤害 |
| `Entity.GetDamageBonus`，`Entity.cs:2308–2340` | 选择控制者，取父实体或自身；法术、随从及特定附魔计算法伤，`RECEIVES_DOUBLE_SPELLDAMAGE_BONUS` 将法伤加成再乘 2；英雄技能另走专属加成 | 可复用分支。部分英雄技能分支通过 `SpellDamageOnlyCardTextBuilder` 决定，明显与文本展示相关；不能简单认定所有随从伤害都获得法伤 |
| `Entity.GetDamageBonusDouble`，`Entity.cs:2342–2358` | 法术类取 `SPELLPOWER_DOUBLE`，英雄技能取 `HERO_POWER_DOUBLE` | 返回翻倍次数对应的标签，不在这里造成伤害 |
| `Entity.GetHealingBonus` / `GetHealingDouble`，`Entity.cs:2360–2391` | 治疗加成；全局翻倍次数加上法术/英雄技能专属翻倍次数 | 可抽取聚合公式。不会修改生命，不处理过量治疗、吸血、触发等 |
| `Entity.GetAttackBonus` / `GetArmorBonus`，`Entity.cs:2393–2415` | 实体本身与控制者的额外攻击/护甲获得量相加 | 可复用简单聚合公式；不是攻击力最终计算或护甲伤害吸收过程 |
| `TextUtils.TransformCardTextImpl`，`TextUtils.cs:288–390` | `$`伤害先加法伤，再按次数翻倍，最后至少为 0；`#`治疗先加治疗量再翻倍 | 纯文本数值公式可离线运行，具体算式见下。它只输出字符串，不改变实体 |
| `TextUtils.SafeAddInt`，`TextUtils.cs:393–403` | int32 饱和加法，超过上/下限返回对应边界 | 可原样提炼成独立工具函数；仅证明此展示路径的溢出策略 |
| `Entity.GetCurrentHealth` / `GetCurrentDefense`，`Entity.cs:1627–1635` | 当前生命 = `HEALTH - DAMAGE - PREDAMAGE`；防御总量再加 `ARMOR` | 可用作状态查询/预览；不是伤害执行过程，也不做死亡处理 |
| `Entity.GetRealTimeRemainingHP`，`Entity.cs:2612–2615` | 实时缓存生命 + 护甲 − 伤害 | 是数值查询；与上述 `GetCurrentHealth` 的 `PREDAMAGE` 路径不同 |
| `Entity.WouldAnAttackZeroHealth`，`Entity.cs:2617–2626` | 以无符号门槛及溢出边界处理，比较攻击数值能否覆盖实时生命+护甲−伤害 | 是局部致死预览。未处理圣盾、免疫、剧毒、伤害减免、替代效果或死亡触发，不能当作完整攻击结算 |
| `Player.GetNumAvailableResources`，`Player.cs:473–484` | `max(0, RESOURCES + TEMP_RESOURCES - RESOURCES_USED - m_queuedSpentMana - m_usedTempMana)` | 可复用客户端可用法力预算公式；含已排队操作的本地预测支出，不负责回合恢复与过载计算 |
| `Player.GetNumAvailableCorpses`，`Player.cs:486–500` | 无英雄返回 0，否则 `max(0, CORPSES - CORPSES_SPENT_THIS_GAME)` | 可复用查询，不负责尸体生成/消耗事件 |
| `GameState.GetTauntCounts`，`GameState.cs:1559–1589` | 枚举指定玩家战场，统计有嘲讽且非潜行的随从/英雄 | 有本地选择条件，可移植；不是完整攻击目标合法性检验，例如本方法没有覆盖所有不可交互状态 |

## 多数看起来像机制的方法只是读取状态

`EntityBase.GetTag` 在 `EntityBase.cs:137–145` 直接查询 `m_tags`；`HasTag` 在 `127–130` 判断该值是否大于 0。

| 方法 | 位置 | 方法体本质 |
| --- | --- | --- |
| `GetCost`, `GetATK`, `GetHealth`, `GetArmor` | `EntityBase.cs:915–933` | 直接读取 `COST/ATK/HEALTH/ARMOR`，没有费用层、光环、攻击/生命增益计算 |
| `GetDamage` / `IsFrozen` | `EntityBase.cs:374–382` | 直接读取 `DAMAGE/FROZEN`，没有伤害执行或解冻时机 |
| `HasDivineShield` | `EntityBase.cs:444–447` | 判断 `DIVINE_SHIELD`，没有移除圣盾/吸收伤害 |
| `IsExhausted` | `EntityBase.cs:669–672` | 判断 `EXHAUSTED`，没有攻击次数资格计算 |
| `GetNumAttacksThisTurn` | `EntityBase.cs:816–819` | 直接读取 `NUM_ATTACKS_THIS_TURN`，不会累加或重置 |
| `HasWindfury` | `EntityBase.cs:1005–1008` | `WINDFURY > 0`，没有 2 次/4 次攻击或额外攻击机制 |
| `IsImmune` | `EntityBase.cs:327–334` | `IMMUNE` 或 `UNTOUCHABLE` 标签为真；没有免疫伤害执行路径 |
| `IsPoisonous` | `EntityBase.cs:336–343` | `POISONOUS` 或 `NON_KEYWORD_POISONOUS`，没有导致死亡的处理 |

`EntityDef` 继承同一个 `EntityBase`（`EntityDef.cs:5`），其标签容器和文本构建器不能提供战斗状态转移。`Entity.GetDefCost/GetDefATK/GetDefHealth`（`Entity.cs:1468–1481`）只是取定义上的基础数值。

本次检查的这几个类型没有找到完整 `CanAttack` 实现。特别要防止两个误判：

- `EntityBase.IsAsleep`（`EntityBase.cs:389–432`）虽然检查入场回合、已攻击次数、冲锋和突袭，但同时检查 `SHOW_SLEEP_ZZZ_OVERRIDE`、游戏选项 `ALLOW_SLEEP_FX`，并对地标、泰坦等展示对象作特判。它用于睡眠表现，不能充当攻击资格规则。
- `Entity.CanBeDamagedRealTime`（`Entity.cs:1614–1625`）检查实时圣盾/免疫；攻击时免疫还读取 `TargetReticleManager.ArrowSourceEntityID`。这是依赖鼠标指向/拖拽箭头的预览辅助，不是传入攻击动作即可结算的函数。

## 可执行片段证明

这里不是只根据方法名猜测。[验证脚本](../tools/client_rule_probe/verify_formula_fragments.ps1) 从已反编译的 `Player.cs:275–321` 和 `TextUtils.cs:288–404` 读取方法体，保留公式和分支，仅提供最小标签字典、枚举和字符串缓存桩，用 PowerShell `Add-Type` 实际编译 C# 并执行。枚举数值只是桩中内部标识，不冒充游戏协议编号。复现说明见 [工具 README](../tools/client_rule_probe/README.md)。

运行：

```powershell
pwsh -NoProfile -File .\tools\client_rule_probe\verify_formula_fragments.ps1
```

9 项数值验证全部通过，输出保存于 `reports/decompiled/entity/formula-verification.json`。这是**抽出的原方法体**离线运行；不是宣称整个游戏 DLL 已能独立运行，更不是端到端战斗验证。

脚本也校验以下片段 SHA-256。规范为各原行以 LF 拼接，无额外末尾 LF，使用无 BOM UTF-8 编码：

| 方法 | 原行号 | 片段 SHA-256 |
| --- | --- | --- |
| `Player.TotalSpellpower` | `Player.cs:275–321` | `5758C0AF3BBD2121694DDC873FC77CA5E42F76580DC71051EB194D46F08D4B1C` |
| `TextUtils.TransformCardTextImpl` | `TextUtils.cs:288–391` | `5D4A3CF1C8C5B871887EB6B5FE3EA653CF98DBE832306C2D7BB8ADD7055CC0C1` |
| `TextUtils.SafeAddInt` | `TextUtils.cs:393–404` | `3CA6387395FB05933DBAB3BBB7178085C879967DC6295BEF96255C4C91E4908C` |

可简化成下面的规则片段：

```text
includeTemporary = entity.SECRET == 0 and entity.SIGIL == 0
bonus = player.CURRENT_SPELLPOWER_BASE
      - player.CURRENT_NEGATIVE_SPELLPOWER
      + player.CURRENT_SPELLPOWER_<school>
      + entity.CURRENT_SPELLPOWER_BASE
if includeTemporary:
    bonus += player.CURRENT_TEMP_SPELLPOWER_BASE
           + player.CURRENT_TEMP_SPELLPOWER_<school>

shownDamage = saturatingInt32Add(baseDamage, bonus)
repeat damageDoubleCount times:
    shownDamage = saturatingInt32Add(shownDamage, shownDamage)
shownDamage = max(0, shownDamage)
```

示例测试：

| 输入/变化 | 抽取方法实测结果 |
| --- | --- |
| 通用法伤 2、负法伤 1、火焰法伤 3、临时通用 4、临时火焰 5、实体自身加成 6；普通火焰法术 | `2 - 1 + 3 + 4 + 5 + 6 = 19` |
| 相同标签，实体为奥秘 | `2 - 1 + 3 + 6 = 10`，临时部分排除 |
| 相同标签，实体为符咒 | `2 - 1 + 3 + 6 = 10`，临时部分排除 |
| 相同标签，普通无派系法术 | `2 - 1 + 4 + 6 = 11`，火焰部分排除 |
| 文本基础伤害 6、法伤 2、翻倍次数 2 | `(6 + 2) × 2 × 2 = 32` |
| 文本基础伤害 2、加成 −3 | 0 |
| 文本基础伤害 int32 最大值、加成 1、翻倍 2 次 | 饱和值 `2147483647` |
| 文本基础治疗 4、治疗加成 2、翻倍 1 次 | 12 |
| 文本基础治疗 2、治疗加成 −3 | −1；该格式化分支没有伤害分支的 0 下限 |

最后一项尤其说明：可把这些函数当作官方客户端的局部计算证据和实现参考，但不能未经验证推广成服务器治疗结算规则。

## 为什么这些公式仍不足以独立战斗

公式调用链可以精确定位：

```text
TextUtils.TransformCardText(Entity, string)  [TextUtils.cs:102–118]
  → Entity.GetDamageBonus / GetDamageBonusDouble / GetHealingBonus ...
  → Player.TotalSpellpower
  → 读取当前汇总标签
  → TextUtils.TransformCardTextImpl
  → 生成显示文本
```

其中 `SUPPRESS_SPELL_POWER_IN_TEXT` 会在 `TextUtils.cs:113–117` 直接把伤害加成和翻倍清零，进一步限定了这个调用路径的用途。

数值状态变更方向也有直接证据：`GameState.OnTagChange(Network.HistTagChange)`（`GameState.cs:4532–4558`）取网络消息中的 `Tag/Value`，写入实体或动态定义，再调用 `PreprocessTagChange` 和 `OnTagChanged`。实时缓存路径 `Entity.OnRealTimeTagChanged`（`Entity.cs:408–426`）将网络携带的费用、攻击、生命、伤害、护甲数值直接写入缓存。这与“服务器/上游已计算结果，客户端应用并展示”吻合；并不否定客户端进行一些本地预测或派生计算。

本次范围内没有发现独立的伤害包执行、圣盾消耗、护甲吸收、死亡检查点、亡语/奥秘触发队列或回合重置实现。该结论严格限于检查过的文件及路径，不是对所有安装资源作绝对不存在证明。

对传统炉石模拟器真正有用的产物是：可以提炼这些标签模型和局部公式，作为细节参考或一致性检查；完整战斗核心仍需继续找到明确的状态转移入口及效果调度代码，或另行实现。单独导出这些类不会得到可运行的战斗引擎。
