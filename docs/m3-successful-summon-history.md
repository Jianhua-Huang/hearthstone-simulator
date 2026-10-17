# 成功随从召唤事实与纯查询

实际复生发生在原记录追加可空`reborn_death_id`并提供`successful_reborns`，同时核原入场和复生事件对；没有平行计数器，见[有限复生分类](m3-successful-reborn-history.md)。下文原引入版本与字段表保留为历史。

`successful_summons.py` 在原 `Resolution.emit` 发布 `minion_summoned` 时记录不可变事实，先于原监听者捕获。普通随从出牌和原效果召唤共用这个入口。它不创建或移动实体，不执行召唤主体，不增加事件、检查点、随机消费或逐玩家可变计数器；既有来源 producer、数量计划与召唤执行器继续各自负责原行为。

本能力引入于 prototype-v220/core-effects-v214、schema205。`GameState` 新增 `successful_summon_history` 和 `next_successful_summon_id` 两个私有字段，旧 schema1～204、未来版本和非严格整数版本明确拒绝，不能通过补空历史重标为新保存。玩家观察74、命令11和replay1保持。实际执行结果及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

## 记录与归属

每次原成功发布保存一个冻结 `SuccessfulSummonRecord`：

| 字段 | 含义 |
| --- | --- |
| `id`、`event_sequence` | 完整单调分配的发生身份及原成功事件位置；事件之间允许存在其他事件 |
| `player_id` | 原事件的召唤方，即发布时该随从的场上 controller |
| `active_player`、`turn`、`action` | 原发生时的行动玩家、全局回合和实际动作；行动玩家不能替代召唤方或冒充原因方 |
| `minion` | 完整原 `SourceAllocationFact`：实体、原牌面、类型、owner/controller、区域、epoch、入场顺序及原分配上界 |
| `printed_tribes` | 原牌面的固定印刷种族，允许明确未知 `None` |
| `tribe_changes`、`tribes` | 发布时原有序种族声明及完整当前种族结果，包括 all 的排除集合；结果必须可由原声明与印刷集合推得 |

owner 与 controller 可以不同；后续变形、回手、死亡或转移控制权不会重写原记录。当前活动玩家只是时间背景，这里没有从它或事件 source 推测造成召唤的卡牌/玩家；原 `minion_summoned` 的 source 与 target 均为成功入场的随从。

这里只记录原事件确认的成功：初始场景中的既有场面、手牌/牌库、失败或取消的尝试、变形和纯控制转移不能凭空增加次数。磁力合体按原执行器不发布召唤事件。复生、复活、复制、巨型附属物、号角士兵和星舰启动沿用各自原发布点，不另造一套入场规则；休眠或之后死亡不能抹去已经发布的成功。同一物理实体回手后再次入场可以有不同 epoch/入场顺序；同一次物理入场不能重复发布。具体特殊路径是否与现行国服完全一致仍由 M6 校准，不因该台账覆盖原发布点而宣称官方规则已完整。

## 纯查询

扩展可从 `hs_sim.engine` 导入：

```python
summoned_minions(state, player_id, *, tribes=(), basis='current', turn=None)
summon_count(state, player_id, *, tribes=(), basis='current', turn=None)
```

第一个返回按原顺序排列的冻结事实 tuple，第二个返回其长度。默认是本人本局全部成功随从召唤；`turn` 指全局回合，`basis` 只允许 `current` 或 `printed`，均读取原发布时的牌面/种族而不是现在的场面。`tribes` 是不可变、无重复字符串 tuple，多种族按任一个匹配，每次发生仍只有一个计数；`all` 使用原 `TribeState` 的集合语义，不从少量已适配卡牌推测完整种族全集。

无种族过滤时，未知种族的成功仍计数。有种族过滤时，匹配范围内任何未知原种族明确抛出 `UnsupportedDefinitionError`，不会静默当作非匹配；其他玩家或其他指定回合的记录保留在历史中，但不属于本次匹配范围。该接口不读取宿主事件日志，不依赖消费卡何时进入手牌，不返回宿主快照，也不内置减费或任意条件表达式。OG_028 所需的有限图腾费用消费者须另行接入原费用与付款层。

## 保存、时序与边界

原事件完整写入记录后再捕获监听者，因此监听者得到的原 `RuleContext.state` 可查询刚发生的成功。私有 JSON 与所有原捕获状态复用严格 `GameState` 编解码；记录字段、原分配、种族声明、类型、顺序和 cursor 必须完整。稳定边界逐项对齐有效的原成功事件库存，拒绝缺行、重排、重复物理入场及原事件身份变化，即使调用者重新计算 JSON 哈希也不会跳过这些检查。

原 clone、独立注册表恢复和 replay 复用同一事实；工作事务或选择失败恢复原历史及 cursor。原 Rewind 恢复发生前的 State 历史，宿主诊断日志仍可保留已撤销事件；边界检查复用原 `effective_events` 的真实 rewind marker 退役后缀，查询只读取恢复后的 State，不重复计数撤销尝试。

这些是内部结构与一致性证明，不是未签名保存的外部来源认证。历史中的完整原种族声明不能证明外部声称的过去确实发生过；国服对象归属、种族依据、特殊入场窗口及正式卡池继续待 M0/M6。私有历史不进入玩家观察、命令或公共事件载荷；玩家仅接收原有可见随从与事件。
