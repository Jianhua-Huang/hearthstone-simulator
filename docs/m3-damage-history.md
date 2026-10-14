# 实际伤害历史与纯查询

伤害单位直接读取既有 `HealthResult.damage_dealt`。它与 `health_lost` 分开保存：例如英雄受到 5 点伤害、护甲吸收 3 点，实际承伤为 5，生命损失为 2。请求量、净生命变化、技能使用次数和死亡次数不能替代原结算量。

## 原事实与生命周期

冻结 `DamageRecord(id, action, result)` 保存每个原始流或最终流为 `DAMAGE` 的完整有序结果。`GameState` 只增加 `damage_history` 和 `next_damage_id`；零量、免疫、圣盾、规则阻止及双向转换保留结果，统计实际量时取最终 `damage_dealt`。失效目标略过没有结算结果，不另造记录。普通治疗、增加生命上限和护甲不产生伤害信用；吸血治疗不重复计入原伤害。

伤害与原治疗历史的存储、完整物理目录检查、严格解析和事件对齐由 `health_history.py` 共用。原数值、转换、吸血、生命下限、随机分段、死亡检查和事件顺序仍由既有内核处理。原整批数值和吸血完成后、首次原事件捕获前一次提交两份历史；无需预测事件位置。双方流各自使用连续记录 ID，原 `batch_id` / `packet_index` 不变。

原来源和目标的卡面、归属、物理身份、回合与动作被保留。后续变形、控制权变化、死亡、回手、技能替换不重写历史。武器原身份也校验存在及分配上界。真正的回溯沿既有有效事件政策退役旧尝试；事务失败和选择失败沿原边界回滚。没有第二套伤害执行器、玩法事件、动作或组合机制。

## 规则接口

```python
damage_records(state, *, source_player=None, target_player=None,
               target_kind=None, turn=None, before_id=None,
               target_own_turn=False)
hero_damage_taken(state, player_id, *, own_turn_only=False, turn=None)
hero_power_damage(state, registry, player_id, *, turn=None)
```

`damage_records` 返回完整冻结行的元组。玩家、角色类型、全局回合和排他记录上界严格检查；`target_own_turn=True` 要求明确目标玩家，并按原 `active_player == target_controller` 筛选。

`hero_damage_taken` 累加指定目标玩家英雄实际收到的伤害，包含护甲吸收。当前本人回合条件使用 `own_turn_only=True, turn=state.turn`；只指定 `own_turn_only=True` 则查询历次本人回合。来源可以属于另一玩家或未知来源，目标查询不依赖来源信用。

`hero_power_damage` 只统计原来源卡面类型为 `HERO_POWER`、原控制者为指定玩家的实际伤害。它检查注册表原卡面，不能仅按 `DamageKind` 或当前装备技能判定。旧技能已替换仍保留原量。这个有限直接来源政策尚不涵盖间接施法、召唤物等派生来源的技能信用，不能宣称完整英雄技能归属已校准。

正伤害若原来源未知，来源玩家累计查询明确抛出 `UnsupportedDefinitionError`；不猜归属，也不静默丢失数量。原 `FATIGUE` 包具有明确的系统来源，计入目标英雄承伤，不归属于卡牌来源，也不阻塞技能累计查询。先界定目标、回合和前缀范围，范围外未知来源不阻塞查询；未知零量不增加来源信用。查询只读宿主状态，完整历史与结果不进入玩家观察或日志。

## 必要证据与保存格式

[完整原卡记录](../data/support/actual-damage-history-basics.json)保存 `BAR_547`、`TTN_462` 与 `TRL_316`。只在隔离实验注册表接入火眼莫德雷斯：完整 8 费 8/8 法师传说亡灵，累计直接英雄技能实际伤害至少 10 时，通过既有 `DamageBatch` 对敌方角色造成 10 点伤害。其他两行只作需求证据，没有可执行白板适配或正式生成池扩充。

引入格式为 `prototype-v231` / `core-effects-v225` / schema214，旧1～213需原引擎。普通字典与既有 `FrameCodec` 保留同一完整负载，包括原生命下限计划、随机分段链接和武器身份；完整当前边界与有效原事件逐条对齐。严格解析和摘要校验不提供未签名存档的外部来源认证。

护甲、双向转换、直接技能信用、原目标英雄归属及整批可见窗采用明确本地政策，精确国服规则仍待校准。实际执行与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)登记。
