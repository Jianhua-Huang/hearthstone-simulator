# M5-07b-03b-01：牌库销毁与古加尔牺牲替换

本批将牌库卡的物理销毁与场上死亡分开，并实现古加尔，暮光主谋对手臂/士兵的牺牲替换。运行时 `prototype-v75` / `core-effects-v75`、snapshot schema 74、`representative-m5-v38`，玩家观察 v39、命令为 v7，外层 replay 仍 1。旧 schema 1～73 明确拒绝。

M5-07 仍未整体验收。b-03b-02 关键词光环与艾萨拉已内部验收，b-03b-03 奥拉基尔已内部验收，b-03b-04 希奈丝特拉已内部验收，奥妮克希亚生命损失替换已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)；自动施法和生命设值例外继续保留。目标正式卡池和国服集中校准仍是独立门槛。

## 物理牌库销毁

[zones.py](../hs_sim/engine/zones.py) 提供两个公共效果：

```python
DestroyDeckCard(card_reference, source_id=None, reveal=True, on_destroy=())
DestroyDeckMatching(player_id, query=PoolQuery(), count=1,
                    selection='random', source_id=None, reveal=True)
```

`DestroyDeckCard` 仅接受 `CardReference` 捕获的牌库实体；控制者、卡面、区域与区域修订必须仍匹配。已经抽走、换形、移出再移回的同 ID 实体不会被旧请求销毁。成功时将该物理实体移入墓地区域并推进修订号；它没有变成场上随从。

- 不生成 `DeathRecord`、尸体、亡语、复生、星舰贡献、抽牌/获取或弃牌事件。
- 使用独立事件 `card_destroyed_in_deck`；不能用 `DiscardCard` 或普通 `Destroy` 冒充。
- `on_destroy` 是不可变效果元组，仅在本次实际销毁成功后执行；普通事件反应与其嵌套选择先结算。整个续接经过允许列表编解码，未知回调在移牌前报错。
- `DestroyDeckMatching` 复用现有 `PoolQuery` 对本局牌库实体筛选，不从静态生成池取牌；支持固定随机或牌库顺序中的第一个匹配项。
- 每次移除及其反应结束后，重新查询下一张。无匹配项时正常结束，不把空筛选或空牌库当作抽牌疲劳；受同一结算预算限制。

`reveal=True` 时，仅移除的那张牌对双方公开；不公布候选 ID、候选数量、剩余牌面或牌库位置。`reveal=False` 时仅控制者记录被移除牌面，另一方可观察移除事件与数量变化。新事件进入玩家事件允许列表，因此观察版本提升到 v22；全知调试事件、完整快照与回放仍不能给玩家。

## 实时牺牲替换光环

`DeckSacrificeSpec(card_ids=(...))` 声明受影响的友方卡面白名单。`CardDefinition.deck_sacrifice` 安装印刷能力；`GrantDeckSacrificeAura(target_id, spec, source_id=None, expires_turn=None)` 动态授予随从。能力使用公共附件 ID、沉默、复制、重建与到期规则。

[sacrifice.py](../hs_sim/engine/sacrifice.py) 在 `SacrificeAdjacent` 实际执行时，先核对受益者身份，再查当前控制者场上的有效替换光环：

1. 光环来源必须是活动、存活、未标记消灭的场上随从；休眠、沉默移除、转控和来源离场立即改变后续适用性。
2. 受益者当前卡面必须在白名单中。多个相同光环只替换一次，不增加消灭数量。
3. 替换在寻找物理右邻之前执行，因此末位士兵或右侧为地标/休眠随从时，仍可处理敌方牌库。
4. 从对方当前牌库随机选择一张随从，使用 `DestroyDeckCard` 移除；后续由 `BuffCapturedMinion` 检查受益者同一场上身份再加属性。
5. 本原型在敌方牌库没有随从时不消灭友方，也不增加属性；该空候选策略仍待国服校准。

普通 `Destroy` 与明确指定受害者的 `DestroyForBuff` 不经过这项相邻牺牲替换。它不是全局“所有消灭都改目标”的规则；未来其他替换机制仍需明确适用事件与优先级。

`BuffCapturedMinion(beneficiary, attack, health, source_id)` 复用既有 `MinionReference`：受益者死亡、转控往返、同卡面变形、回手重入均使奖励失效；普通属性变化不失效。销毁成功后再移除光环，不会撤销已经排入队列的奖励；沉默不会取消已经开始的奖励，但停止下一次触发。终局中止剩余工作。星舰发射的死亡延迟保持原有调度，牌库销毁可即时发生并在奖励前挂起恢复。

## 真实代表与证据

本地冻结的 CATA_726 为 9 费 6/6、巨型 +2，声明左右两条独立手臂。其能力白名单只包含 CATA_725t 士兵、CATA_726t 古的手臂、CATA_726t1 加尔的手臂。数值与卡面文本来自已固定指纹的 [本地数据](../data/extracted/cards.json)，见 [官方卡牌页](https://hearthstone.blizzard.com/en-us/cards/125432/)。主体在召唤时不会使手臂立即额外触发。

[官方 35.0.2 热修公告](https://us.forums.blizzard.com/en/hearthstone/t/3502-hotfix-patch/158856)记录了手臂受伤后无法继续应用古加尔效果的修复；这支持将“受伤不关闭替换”纳入回归，不能单凭国际公告断言国服精确部署。[国服 35.6 公告](https://hs.blizzard.cn/news/24276665/)明确列出召唤古加尔时手臂额外触发的修复。两项历史修复不等于全部目标补丁时序已校准。

- **R-077：替换选择与空牌库。** 暂定按当前控制者实时查询光环、在相邻检查前替换、均匀选择敌方牌库中的物理随从，无候选时不回退。正式空候选策略、光环失效的精确窗口、并列来源和跨控制者的特殊情况仍待国服校准。
- **R-078：牌库销毁与后续奖励。** 暂定为独立物理移除事件，不产生场上死亡；公开被销毁牌但隐藏候选与位置。事件反应/选择先于奖励，终局清空奖励；一般窗口及星舰发射边界仍待集中验证。

## 验证与复现

[50 项专项测试](../tests/test_m5_deck_destruction.py)覆盖双臂入场、召唤不额外触发、受伤后替换、满/空候选、物理相邻绕过、过滤、光环沉默/复制/转控/休眠/死亡、普通消灭隔离、基础与四次兆示强化、动态授予与到期、无亡语/复生/尸体、成功续接、私有信息、跨区引用、挂起/回滚、终局、星舰延迟与严格快照验证。

```powershell
python -m unittest tests.test_m5_deck_destruction -q
python -m examples.chogall_deck_sacrifice
python -m hs_sim replay outputs/chogall-replay.json --card-set representative
```

[示例](../examples/chogall_deck_sacrifice.py)使用明确的既存局面，全程走固定座位玩家命令。古加尔召唤双臂，两次牌库销毁将其分别强化为 3/3，并公开蛛魔之卵与夺烛木乃伊；两张牌都不触发死亡机制。保存后，对手火球消灭主体，下一次回合末左臂恢复相邻牺牲，吃掉右臂并变为 5/5；右臂已失效的排队触发不会再吃掉雪人。恢复、完整回放与 CLI 核验见当前验证记录。示例不是正式构筑合法性声明，无需启动客户端。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为chogall_deck_sacrifice.py：6动作/40事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
