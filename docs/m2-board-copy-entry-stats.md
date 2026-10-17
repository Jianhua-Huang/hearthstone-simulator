# 战场复制的入场前固定身材

扩展既有 `CopyMinion`，复用 `SummonStats`、普通复制材料和 `apply_summon_stats`。实际进度、验收、差异和下一项仅维护在 [项目状态](project-status.md) 与 [机制清单](mechanism-backlog.md)。

```python
CopyMinion(target_id, player_id, stats=SummonStats(attack=1, health=1))
```

`stats` 追加在原位置、模式、归因参数之后，默认为 `None`，旧位置调用保持。只接受严格 `SummonStats`：至少设一个属性，攻击和生命均非负，布尔和字典不是数值/声明。零生命材料按[原入场光环与死亡管线](m3-zero-health-summon-entry.md)执行。没有新增 Entity/Player/GameState 字段、复制执行器或泛化授予。

复制仍按原 `current` / `base` 材料规则创建独立物理实体和附件；普通本地状态复制完成后，再安装原可沉默的 `summon_stats` 设值附件，随后刷新接收者光环、冻结期限并发布入场。指定生命值按原召唤规则清除复制的伤害；只指定攻击不清伤害。`None` 保持旧行为。外部光环与持续关系继续沿原层序，不作为永久材料复制。

带 `SummonCause` 的普通战场复制使用原 `CopyEntryMaterial.stats`，取消其对 board_copy 的旧禁止；接受时捕获数值，原归因/材料、数量计划、逐次交付和等待继续使用原协调器。未知/失效源、满场、位置、原能力身份、基础重置、异常回滚和信息隔离沿原入口；没有新增特殊赐福授予或跨机制组合矩阵。

当前固定身材可被沉默、回手等原重置清除，主卡印刷属性和其余本地复制材料保持。所有入场监听从第一个事件开始看到固定后的数值；复制后另执行 `SetStats` 不等价。精确国服层序、受伤材料和重置政策仍待校准。

仅新增完整 UNG_022 幻象制造者的隔离实验适配。其本地原行是3费2/3牧师稀有，战吼选择随从并召唤1/1复制；[官方27.6说明](https://hearthstone.blizzard.com/en-us/news/23989479/27-6-patch-notes)确认可选择任意随从。EDR_100t5只保留原始需求依据，本轮没有适配黑暗之赐来源、动态主体或配方；当前/基础复制行为的精确CN规则不能由历史目标范围公告证明。

活动帧里的 CopyMinion 多了一个字段，使用 prototype-v299/core-effects-v301/schema263，旧1～262由原引擎读取。原 CopyEntryMaterial 已有 stats 字段，未扩展材料布局；注册表代表定义指纹保持，玩家观察84/命令12/replay1保持。完整正式池、全来源与阶段总体完成仍单独登记。
