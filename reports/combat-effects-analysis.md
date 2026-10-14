# 传统炉石：伤害、攻击、死亡和触发的反编译证据

检查日期：2026-09-23。只读检查本地 `D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll`，未启动、注入或连接游戏，未读取账号和对战日志。

被检文件 SHA-256：`EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B`。

使用 ILSpy CLI 11.1.0.9782 按类型反编译。源码保存在 `reports/decompiled/effects/`，被 `.gitignore` 排除。下文行号指本次生成的源码，而不是游戏开发时的原始源文件行号。所有源码路径的共同前缀为 `C:/Users/Administrator/Documents/ChatGPT/炉石模拟器/reports/decompiled/`。

## 结论及范围

**客户端确实包含部分传统战斗规则计算，尤其是攻击致死预览、圣盾/免疫判断、剧毒判断、法术强度和伤害倍增数字计算。** 所以“客户端完全没有规则”不准确。

但是，本次沿攻击、死亡、亡语和 Spell/FSM 的实际调用链追踪，伤害及死亡状态的写入端点拿到的是已给定的 `Network.HistTagChange.Value`，触发块也是已给定的 `Network.HistBlockStart`。没有在这些链中找到从“玩家打出某张牌/指定攻击目标”自行算出全部状态变化、再继续跑亡语/触发/光环直至稳定的独立规则入口。

这足以判断下面这些看似引擎的类不能直接拿来作为无服务器战斗引擎；不等于已经证明安装目录每一个原生模块、每一份资产都没有其他规则代码。

## 1. 随从互殴：明确分成预览计算和实际状态应用

### 1.1 拖动攻击箭头时，客户端真正在算哪些规则

调用者证据来自并行检查保存的 `network/InputManager.cs`：

- `ShowSkullIfNeeded`（4327 附近）取当前服务器选项的来源，检查目标有效性，然后分别 `ShowSkull(攻击者, 防御者)` 与 `ShowSkull(防御者, 攻击者)`。
- `ShowSkull`（4350）取 `entity1.GetRealTimeAttack()`；目标有 `HEAVILY_ARMORED` 时将该数值限制至 1。
- 4357 行组合 `CanBeDamagedRealTime()`、`WouldAnAttackZeroHealth(num)` 和 `EntityIsPoisonousForSkullPreview()`，决定是否显示死亡骷髅/剧毒图标。
- `EntityIsPoisonousForSkullPreview`（4305）要求攻击力大于 0，识别剧毒/烈毒以及英雄武器上的对应状态。

被调用的本地数值方法：

| 位置 | 输入和判断 | 输出/副作用 |
| --- | --- | --- |
| `effects/Entity.decompiled.cs:1614`，`CanBeDamagedRealTime` | 即时圣盾、免疫；攻击时免疫且实体是当前箭头来源 | 返回布尔值，不扣血、不破圣盾 |
| `effects/Entity.decompiled.cs:2617`，`WouldAnAttackZeroHealth` | 给定攻击值与即时 `health + armor - damage` 比较，包含无符号溢出处理 | 返回致死预测，不标记死亡 |
| `effects/Entity.decompiled.cs:1627`，`GetCurrentHealth` | `HEALTH - DAMAGE - PREDAMAGE` | 返回当前展示血量 |

这组代码是可读、可迁移的规则片段，但它的消费端是 `ActivateActorSpell(SKULL/DAMAGE)` 和缩放动画，不能把它当成完整伤害结算。它不修改伤害/护甲，不建立亡语队列，也不把预览结论发回充当服务器结果。

### 1.2 攻击落地后，伤害值从哪里来

实际链：

1. `effects/PowerProcessor.decompiled.cs:329`，`OnPowerHistory(List<Network.PowerHistory>)` 读取既有结果列表。
2. `:696`，`BuildTaskList` 将 `BLOCK_START/BLOCK_END`、标签变化和元数据组装成任务树；`:719` 附近直接把网络块传给 `SetBlockStart`。任务不是从攻击力重新生成的。
3. `:1666` 的 `ATTACK` 分支创建 `AttackSpellController`；`:1997` 挂任务和完成回调。
4. `effects/AttackSpellController.decompiled.cs:342`，`OnMoveToTargetFinished` 到达动画碰撞时点；`:397` 的 `DoTasks` 调用 `GameUtils.DoDamageTasks`。
5. `effects/GameUtils.decompiled.cs:1866`，`DoDamageTasks` 遍历**已有** PowerTask。只提前执行攻击双方的 `META_DATA(DAMAGE/HEALING)`、`TAG_CHANGE(DAMAGE/EXHAUSTED)`。它没有 `targetDamage += attackerAttack` 之类伤害计算。
6. `effects/PowerTask.decompiled.cs:162`，`DoTask` 中的 `TAG_CHANGE` 分支（195）调用 `GameState.OnTagChange`。
7. `effects/GameState.decompiled.cs:4532`，`OnTagChange` 构造 `TagDelta`，将 `newValue = netChange.Value`（4547）写入实体（4554）。这里才发生标签变化；数值来自传入的网络结果，而非本地攻击计算。

此外，`effects/PowerTaskList.decompiled.cs:1071` 的 `GetDamageInfo` 也是 `HistTagChange.Value - 当前DAMAGE` 得到本次伤害差值，而不是用攻击力算伤害。

即时状态同样来自结果：`PowerTask.DoRealTimeTask:105` → `GameState.OnRealTimeTagChange:4495` → `Entity.OnRealTimeTagChanged:408`；`Entity:421` 对 `DAMAGE` 调 `SetRealTimeDamage(change.Value)`，`:2602` 直接保存该值。这里的 “RealTime” 表示提前消费收到的状态以支持响应/预览，不是本地独立模拟时间线。

## 2. 法术伤害：有加成公式，但效果处理器没有造成伤害的规则入口

以下可用于理解火球术这类数值法术的客户端路径。**本检查没有找到名为 `Fireball` 或 `CS2_029` 的托管执行类，也未把具体火球资源 prefab 与所有 FSM 节点一一对照，故不把通用路径声称为已完整还原火球术脚本。**

真实本地公式证据：

- `effects/Entity.decompiled.cs:2308`，`GetDamageBonus` 汇总法强，处理双倍法强收益以及英雄技能伤害加成。
- `effects/Player.decompiled.cs:275`，`TotalSpellpower` 汇总基础/负法强、对应法术派系、临时法强、实体自身法强；奥秘/符咒排除临时部分。
- `effects/Entity.decompiled.cs:2342`，`GetDamageBonusDouble` 读取法术或英雄技能倍增次数标签。
- `effects/TextUtils.decompiled.cs:101` 附近把以上结果放入 `TransformCardTextParams`。
- `effects/TextUtils.decompiled.cs:288`，`TransformCardTextImpl` 的 `$` 分支（341）先把基础数加 damage bonus，再循环倍增，最后对负数归零；`SafeAddInt:393` 对有符号整数溢出做饱和处理。

忽略整数饱和时，伤害文案数字相当于 `max(0, (基础值 + 加成) × 2^倍增次数)`。这是一段真实本地运算，但产物是 `StringBuilder` 中的文字。

用途证据：`effects/CardTextBuilder.decompiled.cs:140` 的 `GetTargetingArrowText` 对数据库箭头文案调用 `TextUtils.TransformCardText`；`effects/TargetReticleManager.decompiled.cs:272` 调用实体的该方法来显示数字。这条链没有扣目标血量。

实际法术效果调度：

- `effects/PowerSpellController.decompiled.cs:226`，`GetOrCreateEffect` 从传入的 `HistBlockStart` 读取 `SubOption`、`EffectIndex` 和效果卡 ID，挑选客户端 `CardEffect`。
- `:347`，`InitPowerSpell` 将既有任务列表附到 `Spell`；`:388` 进入 `SpellStateType.ACTION`。
- `effects/Spell.decompiled.cs:896`，`AttachPowerTaskList` 保存任务并从任务中找视觉目标；`:953` 的 `OnSpellFinished` 移除阻塞并触发完成回调。
- `effects/PowerProcessor.decompiled.cs:2014` 收到完成回调后调用 `DoCurrentTaskList:1597`，后者执行剩余任务；最终仍到 `GameState.OnTagChange:4532` 的网络数值写入。

因此不应把 `PowerSpellController`、`Spell`、`CardEffect` 名字中的“效果”直接理解成完整牌效规则实现。

## 3. 死亡、亡语和触发：消费既定事件，不是发现死亡再递归结算

### 3.1 死亡选择依据是 ZONE 变化

`effects/PowerProcessor.decompiled.cs:1797` 遇到 `HistoryBlock.Type.DEATHS` 才创建 `DeathSpellController`。后者 `AddDeadCardsToTargetList:31` 遍历收到的标签变化，以 `GameUtils.IsCharacterDeathTagChange` 找死人。

`effects/GameUtils.decompiled.cs:1579` 的检测是 `tag == 49`（ZONE）、`value == 4`（GRAVEYARD）、实体为角色。它不是扫描 `health <= 0` 决定将哪个随从送墓地。

`effects/DeathSpellController.decompiled.cs:16` 的 `OnProcessTaskList` 给已选目标播放死亡效果并选择哪张牌播放死亡音效。名称 `Destroy` 也需要查上下文：`effects/Entity.decompiled.cs:1399` 的 `Destroy` 只是销毁关联客户端 Card；不是“摧毁一个随从并执行其所有亡语”的规则方法。

### 3.2 通用亡语召唤的对象已经存在于收到的 FULL_ENTITY 中

`effects/DeathrattleSummonSpell.decompiled.cs:5` 的 `GetTargetCardFromPowerTask` 只接受 `FULL_ENTITY`，拿 `HistFullEntity.Entity.ID` 去当前 GameState 找到对象。它没有选择召唤什么卡，也没有分配实体 ID。

`:22` 的 `OnAction` 将这些目标移到死亡来源的位置，缩小为 0.2 倍，设置慢速区域过渡，最后 `OnSpellFinished`。这是亡语召唤的表现，不能作为亡语召唤规则函数抽走运行。

### 3.3 具体传统亡语类 AnomalusDeathrattleSpell 也没有范围伤害结算

`effects/AnomalusDeathrattleSpell.decompiled.cs:35` 的 `OnAction` 收集既定视觉目标，给其中将被杀死的实体设置自定义死亡动画，然后运行 `AnimateMinions:60`。

容易误判的 helper 是 `effects/GameUtils.decompiled.cs:1676`，`GetEntitiesKilledBySourceAmongstTargets`：它克隆目标状态，查看当前及排队的 **PowerTask**，应用 `LAST_AFFECTED_BY` 并查找 `ZONE=GRAVEYARD`。因此是向前看已收到的结果以安排动画，不是根据伤害值推演谁会死。

在这个具体亡语类中没有发现亡语伤害常数、扣血循环或依规则产生下一轮死亡事件。该结论针对这个类，不依据本地化卡牌描述猜测实现。

### 3.4 TriggerSpellController 是触发表现调度器

`effects/TriggerSpellController.decompiled.cs:31` 从任务给出的 source entities 构建表现。`:498` 的 `InitEffect` 用网络块 `EffectIndex` 和效果卡 ID 选 `GetTriggerEffect`，`:584` 把已有任务附到 Spell，`:602` 激活视觉状态。

没有在这条链找到从“一个随从受到伤害”扫描全场触发条件、按进入战场顺序登记新触发、处理递归亡语的逻辑。`PowerProcessor.BuildTaskList:696` 保留/调整的是输入块及呈现调度；不能仅从它的队列、parent、previous 名称推断出规则层触发顺序。

## 4. FSM 为什么不是已找到的规则引擎

`effects/Spell.decompiled.cs:97` 持有 PlayMakerFSM；`:120` 从 Unity GameObject 取该组件；其 `OnBirth/OnAction/OnDeath`（989、1000、1011）更新位置或派发状态回调。

`effects/HutongGames.PlayMaker.Actions.SpellFinishAction.decompiled.cs:23` 的 `OnEnter` 调用 `Spell.OnSpellFinished`，有延迟时启动 `WaitForSeconds` 协程。`Spell.OnSpellFinished:953` 解除服务器处理阻塞，并回到上面的 PowerTask 应用链。

这些说明已检查的 FSM 集成负责动画状态与服务器结果消费时点。不能据此否认所有 FSM 节点可能有特殊客户端逻辑；但要证明资源里的 FSM 含战斗规则，必须找到它从行动/局面产生新伤害、召唤、死亡和触发结果的写入链。目前本链未找到这样的证据。

## 5. 对模拟器工作的实际价值

能直接用于规则研究的是：完整标签枚举/状态模型、网络结果块结构、局部致死预览、法强和文案数值加成公式、客户端对结果的时序解释。这些内容远超静态卡牌信息。

目前不能据此交付的是：一个仅传入牌组和玩家行动即可在离线环境算出任意传统对局结果的原版引擎。关键缺口仍是产生结果的牌效执行、伤害替换/防止、光环刷新、死亡处理及触发注册/顺序，以及隐藏状态与随机数规则。

搜索辅助证据：`effects/types.txt` 保存本程序集全部类名，`effects/methods.txt` 保存全部 MethodDef 元数据。对 `DealDamage/ApplyDamage/CalculateDamage/ResolveDeath/ProcessDeath` 等名字未发现相应常规规则入口；名称搜索只是辅助，以上结论主要来自已经追到状态写入端点的调用链。

## 6. 完整程序集交叉核验：具体卡 ID 和直接 DAMAGE 写入

主任务随后提供完整反编译文件 `full/Assembly-CSharp.decompiled.cs`。对火球术 `CS2_029` 的 9 处精确 ID 引用逐处核验：329175、341114、342112、344124、351295、358922、361148、363968、370652，全部在冒险关卡的 `PlayEasterEggLine` / `PlayLineOnlyOnce` 语音响应链。344124 和 351295 属于多张火焰法术共用的语音分支，也没有伤害写入。教学版 `TUTR_CS2_029s2:495367` 是开启指向对手的教程动画。麦田傀儡 `EX1_556:332643` 仅触发特定首领语音。这不是说卡牌效果不存在，而是这些具体 ID 命中不能充当客户端牌效实现证据。

另一个需要解释的直接写入是 `full/Assembly-CSharp.decompiled.cs:681997` 的 `SetTag(GAME_TAG.DAMAGE, tagValue)`。所属方法为 `Cheats.OnProcessCheat_PlayFinisher:681889`，设定终结特效 ID 和固定攻击/伤害值 1 或 999，再手工组装 ATTACK 标签任务供特效预览；没有按传统攻击规则计算双方结果。此处仅静态审阅，未执行任何开发命令。另一处命名 `DAMAGE` 写入 `:702968` 对应 `Entity.OnHideEntity:338`，隐藏实体时重置为 0。

因此，确实存在客户端人为构造状态/任务的代码，但本次找到的这些写入并没有补齐传统战斗规则引擎。

可复现命令示例（仅写报告目录）：

```powershell
& "$env:TEMP\hs-inspect-tools\ilspycmd.exe" --disable-updatecheck `
  -t AttackSpellController -o reports/decompiled/effects `
  'D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll'
```
