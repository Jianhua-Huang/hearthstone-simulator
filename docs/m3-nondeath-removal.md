# 独立非死亡移除

本页描述 `RemoveFromGame` 的公共基础契约。实际版本、验证与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。它是一个区域操作，不新增卡牌组合规则；精确国服时序仍待 M6。

## 场上目标范围与永久载体

原语接收的是来源明确捕获的物理随从引用，不替来源猜测“全部”或“活跃”的含义。普通指定目标的终身刑罚沿原目标资格，不能选取休眠或永久不可交互载体；显式捕获的全体物理随从批次可以移走这些载体。永久实例离开战场后复用原`Resolution.move`清除休眠和board presence，保留原实体/归属、推进区域修订号并进入SETASIDE，不经过死亡、亡语、复生或残骸。

若来源只选活跃随从，可在捕获时同时检查`CardType.MINION`和`entity.active`，从而保留定时休眠、[永久传送门](m4-permanent-board-carriers.md)以及地标。这个差异由具体来源的候选范围表达，不能另建一个默认“清空所有类型”的执行器，也不能擅自改变已有全体移除政策。

[31.0.3官方改动](https://hearthstone.blizzard.com/en-us/news/24161533/31-0-3-patch-notes)已将孤胆游侠雷诺的旧清空/场位限制改为敌方随从移除，并明确排除休眠及非随从对象。[完整本地范围证据](../data/support/board-removal-scope-basics.json)中的`WW_0700`与该改动后的文字一致。历史公告与本地卡文不能证明精确当前国服部署；这里没有适配完整雷诺、萨格拉斯能力或其来源绑定。公共原语允许某形状，不等于每个真实来源都选择该范围。

## 真实需求与证据

[官方终身刑罚](https://hearthstone.blizzard.com/en-us/cards/79596-life-sentence?class=mage&manaCost=4&set=standard)明确要求将一个随从移出对战；[神奇的雷诺](https://hearthstone.blizzard.com/en-us/cards/56076-the-amazing-reno?set=galakronds-awakening)提供批量消失的真实需求。[官方破碎之劫介绍](https://hearthstone.blizzard.com/en-us/news/23533210)说明开局拆分。[完整本地原始记录](../data/support/nondeath-removal.json)固定 MAW_013、YOD_009、DMF_254 三条，各自完整字段及原始哈希保留。

只在隔离专项注册表完整适配 MAW_013 的费用、目标和移除效果；另外两条仅作证据。没有把雷诺的战吼单独适配成完整英雄牌，也没有把破碎之劫开局单独适配成完整卡牌。生产代表和合成包保持原字节。

社区[进阶规则集](https://hearthstone.wiki.gg/wiki/Advanced_rulebook?section=66)将实体移除归入 Set Aside；另一个 Removed From Game 区域用于失效附魔。这里据此采用 `Zone.SETASIDE`。这是有来源的内部表示选择，不是国服客户端校准结论；本模块也不实现中间暂存及再取回的所有来源。

## 捕获与批量接受

```python
RemoveFromGame((MinionReference.capture(target),), source_id=source.id)
RemoveFromGame((CardReference.capture(stored_card),), source_id=source.id, reveal=False)
```

- `targets` 是不可变 tuple，使用既有 `MinionReference` 或 `CardReference`，禁止重复物理 ID。空批次无事件、无随机消耗。
- 场上引用只用于物理随从；手牌/牌库引用用于可存储的普通牌和可打出的英雄牌。当前英雄、已装备位置、地标战场位置及其他区域没有凭空获得移除接口。
- 先检查全部定义、来源与引用，再把仍匹配的目标全部移动到各自控制者的 setaside 列表。未知定义即使引用已失效也报错；离区、重入、改面或改控制者的旧引用跳过，不追踪后来的实例。
- 物理 ID、owner 和 controller 保持，区域修订号推进，战场 presence 清除。目标选择由原卡的 targeting 负责；全体来源可捕获休眠随从，不因此允许普通指定目标绕过休眠、潜行等资格。

## 时序与生命周期

全批离场后才发一个 `cards_removed_from_game` 事件并沿既有光环、触发和死亡检查点继续。已移除来源不能订阅这次事件；仍在场的监听者看到完整离场局面。不会逐个移除后插入死亡检查。

被移除实体不进入墓地，不产生死亡记录、尸体、亡语、复生、弃牌或牌库销毁事件；其他未移除实体仍按原光环和死亡规则检查。休眠状态及手牌进度沿普通区域生命周期失活，未新增卡牌重置或取回政策。之后的普通区域候选、死亡候选和回合时钟不纳入 setaside。

同一受信任效果使用原事务；错误会回滚移动、支付、事件、解释器和随机状态。使用原帧白名单编码引用和效果，真实待选前后恢复、克隆和动作回放不会重复移除。

## 玩家信息与存档

`PlayerState.setaside` 只供宿主状态使用，绝不进入玩家投影；不公开列表、数量、属性或引擎实体 ID。进入该区退役双方活跃追踪句柄。

事件向玩家提供有序 `removed_cards`，每条仅含 `player_id/from_zone/card_id`。场上牌面、本人手牌及先前确实已知的对手手牌可保留身份；默认不公开任何牌库卡面，`reveal=True` 才明确揭示。事件没有可操作的目标或牌库/移除区实体句柄，历史知情也不允许发起新动作。

存档必须显式包含 setaside 列表，实体只能占一个位置，位置必须与 controller/zone 一致。宿主移除收据验证批次数、原区域、完整物理身份和 reveal 的准确类型；玩家事件另验最小白名单。旧 schema 不静默迁移，缺字段、重复成员、错误位置和保留隐藏追踪句柄均拒绝。

## 破碎之劫边界

开局拆走原牌和固定洗入部件已有 `OpeningHook`、本操作和 `AddToDeck` 可供表达；已验证开局移除保持不可变原卡组事实、原实体起点且不进入换牌。本批没有执行完整四部件开局或组装。

组装需要成功完成的部件身份与持久进度；当前 `cast_history` 的分配顺序不能直接充当嵌套施放的完成顺序，手动及自动施放通知也不同。不能宣称简单扫描历史已正确表达整个规则。该具体卡来源保留 M7 按实际需要处理，U31 未闭环；当前独立基础阶段不为它增加组合矩阵或专用部件系统。


## 永久手牌替换来源

整批HAND移除与普通CopyCard可表达必要永久复制手牌；原组不产生取回义务，复制仍保留每个普通效果检查点。具体来源与待校准边界见[独立表达契约](m3-permanent-hand-basics.md)，未增加移除模块分支。
