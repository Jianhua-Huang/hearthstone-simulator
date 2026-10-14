# 成功残骸消耗历史与纯查询

本接口记录已有资源执行器实际完成的残骸扣款，为查询和后续费用规则提供共同事实。账户余额、获得量、请求上限和操作次数都不能替代实际消耗单位。规则以国服构筑校准为最终依据；本接口的执行与验收记录由[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 三个原发布入口

| 原入口 | `origin` | 记录内容 |
| --- | --- | --- |
| `SpendResource` 成功扣款 | `fixed` | 固定实际量；原效果没有物理来源参数，来源显式为空 |
| `SpendUpToResource` 完成扣款 | `capped` | 原 `ResourceConsumptionResult.actual_amount` 及原 `operation_id`；显式来源和原卡面保持 |
| 原共享 `CORPSES` 付款 | `payment` | 已付实际量、原付款实体及卡面；手牌和英雄技能共用原支付管线 |

成功零量操作保留完整零量行，累计单位增加零。余额不足的可选略过、必需付款失败、增益及其他账户支付不产生残骸扣款行。上限消耗的原结果、回调窗口和 pending 生命周期继续由 `resource_operations.py` 管理；完成后 pending 移除，公共消耗记录保留。退款只改变账户，已经实际消耗的单位仍保留。

## 不可变事实与纯查询

`GameState.corpse_spend_history` 是完整有序的私有列表，每项为冻结的 `CorpseSpendRecord`。记录保存连续 `id`、实际玩家、全局 `turn`、外部 `action`、入口、实际量、原账户前后余额，以及入口实际具备的来源和上限操作身份。余额差必须等于实际量；未知入口、非法整数、布尔量、不一致来源或操作身份明确拒绝。来源卡面是扣款时的事实，后续合法变形不会改写旧行。

```python
from hs_sim.engine import corpse_spends, spent_corpses

rows = corpse_spends(state, player_id)
units = spent_corpses(state, player_id)
this_turn = spent_corpses(state, player_id, turn=state.turn)
original_prefix = corpse_spends(state, player_id, before_id=boundary_id)
```

查询只读取原状态中的记录，返回不可变元组或单位和。`turn` 和排他性的 `before_id` 为可选的严格整数筛选。总量跨本局回合累加，两位玩家独立；不扫描事件日志，不修改余额或缓存，不触发行为。规则消费者需要保留完整原前缀和接受窗口，不能只保存一个可变总数。

## 付款、事件与事务边界

固定和上限路径在原扣款后登记一次，然后由原事件发布反应；反应查询能看到已经提交的行。付款使用既有 `PaymentPlan.resource_writes`，一次写入账户与记录；纯付款投影使用同一个准备函数，保持原接受证明和真实执行一致，没有第二套资源执行器。

原 `resource_spent` 或 `corpses_spent` 事件附带完整私有 `corpse_spend` 包。上限事件继续保留完整原 `result`，两份事实的单位、账户、时钟、来源及操作身份必须一致。没有实际扣款记录的伪消耗事件会被拒绝。边界验证把完整状态前缀与有效事件逐行比较；只有该完整性检查读取事件，纯查询仍只读取状态。

原事务回滚同时恢复余额、记录、队列和随机状态。真实待选保存已经提交的扣款，再次选择不会重付或重复登记。原回溯恢复记录前缀，并沿用有效事件退役规则；被撤销尝试不累计，原上限操作分配计数继续保持自身政策。终局中已经实际接受的扣款保留。

## 保存与玩家接口

引入时使用 `prototype-v226` / `core-effects-v220`、快照 schema209，旧1～208需要原引擎。严格字典保存和公共 typed 帧保留完整记录；重算摘要不能绕过缺项、重排、截短、额外字段、未来身份或事件包不一致检查。此验证不认证未签名存档的外部来源。

玩家 DTO、日志和合法操作继续使用原白名单投影，不导出此私有列表、扣款证明、物理来源或上限操作身份。观察74、命令11及 replay1保持。本接口不提供真实费用卡适配，也不定义新的跨机制组合。

相关契约：[账户与资源](m2-resources.md)、[英雄实际生命变化](m3-hero-health-changes.md)、[固有费用与付款](m5-intrinsic-costs.md)。
