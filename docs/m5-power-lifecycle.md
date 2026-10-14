# M5-12d-02：定向技能操作与生命周期

当前 `prototype-v75` / `core-effects-v75`，snapshot schema 74、观察 v42、命令 v6、replay 1。旧 1～71 快照拒绝。真实代表包仍为 `representative-m5-v38`，260 条记录保持；本批用合成来源验证公共能力，未新增真实卡牌适配。[48 项专项](../tests/test_m5_power_lifecycle.py)内部通过，全量结果见[项目状态](project-status.md)。

## 两种明确的选择方式

`HeroPowerReference.capture(entity)` 捕获实体 ID、控制者、卡牌 ID、区域修订和安装顺序。只允许捕获技能区域的技能实体。列表位置不作为身份：前面的额外技能离场导致索引移动，不会使后面的引用失效；替换或重新安装则不能继承旧引用。

`hero_power_references(state, player_id, scope='all')` 返回不可变引用元组，支持 `all`、`primary`、`additional`。这是无副作用的瞬时查询，不是持续订阅；后来新增的技能不进入此前捕获的集合。

以下接口新增 `power: HeroPowerReference | None`：

- `ReplaceHeroPower(player_id, card_id, power=None, cost=None, expires_turn=None, source_id=None)`。
- `RefreshHeroPower(player_id, power=None)`。
- `SetHeroPowerUses(player_id, limit, power=None)`。
- `TriggerHeroPower(..., power=None)`；原目标/随机与玩家选择策略保持。
- 新增 `RemoveHeroPower(player_id, power=None, source_id=None)`。

`power=None` 明确表示**执行时的主技能**；有引用时，只操作其捕获的实体安装。引用和 player_id 不一致在声明时拒绝，不能用对手引用绕过控制者限制。执行时原安装已失效，则产生宿主诊断 `effect_skipped / hero_power_reference_stale` 并跳过，不修改新技能、不消耗随机数、不伪造激活记录。

缺少动态主技能时，刷新、次数、移除和间接激活报错并回滚；主技能替换允许在空主位安装。失效定向替换不会变成新增技能。未知定义、无效安装费用或来源不因为引用已失效而被静默忽略。

## 替换、移除与原子费用

定向替换保留主/额外角色和额外列表中的相对位置，创建全新实体及印刷能力；旧实体进入墓地，旧附件与已用次数不转移到新实体。玩家本回合总使用次数和此前激活历史保留。不存在同名去重的隐式规则。

移除只将指定技能移到墓地，保留其历史实体；不产生死亡、残骸或亡语。移除主技能不会提升额外技能。重复使用同一旧引用移除为明确跳过；重新安装的同名技能拥有新 ID 和新玩家句柄，旧句柄无法再次激活它。

`AddHeroPower` 和 `ReplaceHeroPower` 的 `cost` / `expires_turn` 复用已有 `CostSpec`、成本校验与费用附件。安装及替换事件发出前，费用加减、设值、替代支付和期限已原子装入，事件捕获不会看到未应用费用的中间版本。费用范围必须显式包含 `CardType.HERO_POWER`；未知来源、类型不匹配及已经过期的费用在提交前失败。

例如安装消耗残骸的技能：

```python
AddHeroPower(
    ctx.player_id, power_card_id, source_id=ctx.source_id,
    cost=CostSpec(payment=PaymentType.CORPSES,
                  card_types=(CardType.HERO_POWER,)),
)
```

费用期限到达后恢复该实体的普通报价，不移除技能。移除/替换不会转移旧实体费用。这里提供表达能力，不将未适配 JAIL_446 的具体费用、生成结果或重复获得策略自行认定为已实现。

## 刷新、次数与间接激活

刷新只清零被选中实体的已用次数；设置上限只改该实体的 use_limit，均不重写玩家累计计数或历史。可以先捕获全部技能，再逐个返回 RefreshHeroPower 等效果。每项仍有自身反应检查点；前一项反应替换了后一项技能时，后一引用失效，新安装技能不会被误刷新。这里没有偷偷把多个效果合并成一个原子批次。

间接激活复用既有 `begin`、目标策略、随机选择及独立历史：无需支付技能费用或消耗手动次数，可指定额外技能；被动技能保留无主动效果的失败尝试。选择指定给玩家时能暂停恢复，随机选择不会因为来源位于额外列表而误转为玩家选择。

失效引用在激活开始前跳过，不创建历史记录。一旦激活已经接受并捕获主体，开始事件的反应移除技能不会改为运行另一个技能；已接受主体及完成标记继续使用原实体。手动激活同样保留其已经支付的费用、使用次数和来源记录。终局和回溯的多技能组合已在 [12d-03](m5-power-combinations.md) 内部验收。

## 被动监听和英雄替换

移除后不再捕获新事件。已捕获但尚未开始的被动监听复核原安装和能力实例；原技能移除、换装或同名重建后跳过。已经开始并请求选择的监听允许继续其已捕获分支，不把旧选择来源改成新技能。

`ReplaceHero(..., additional_power_policy='preserve')` 与可打出的英雄定义 `CardDefinition(..., additional_power_policy='preserve')` 明确提供 `preserve` / `remove` 两种策略。默认保留额外实体、费用与使用次数，保持此前原型行为；remove 在英雄替换处理中移除当时全部额外技能，然后才发出各移除事件，监听不能看到只移除一半的列表。主位按原英雄替换契约处理，英雄 ID/职业/生命/护甲等仍走原路径。

非可打出英雄不得声明 remove。旧真实英雄适配保持 preserve；这不等于已经确认每张真实英雄牌的官方多技能规则。新策略先以合成来源验证，正式卡牌选择与例外仍需证据。并未擅自规定“任何英雄替换都清除额外技能”。

## 恢复、玩家信息与验证

捕获引用和效果字段进入可序列化解释器帧；恢复校验类型、控制者一致性、费用定义、引用卡牌类型等。过时的有效引用允许保留到执行时跳过，不因恢复时发现它已离场而取消整个合法选择。快照摘要不是历史真实性证明，带合法结构的宿主篡改不在玩家命令权限模型内。

观察 v42 公开 `hero_power_removed` 的既有可见源/目标身份，引用修订、内部实体 ID 和诊断原因不通过该事件泄漏。操作仍通过 v6 的玩家句柄；失效句柄即使卡名相同也不能使用。内部效果本身不是玩家可以任意提交的命令。

[合成示例](../examples/power_lifecycle.py)经玩家命令安装残骸支付的额外技能、使用后暂停选择替换，保存恢复后确认旧间接引用跳过，再使用、刷新、间接激活和移除新技能。10 动作、42 事件，完整回放一致。输出：[快照](../outputs/power-lifecycle-snapshot.json)、[回放](../outputs/power-lifecycle-replay.json)、[玩家观察](../outputs/power-lifecycle-view.json)。该注册表是合成验证，不能使用 representative CLI 卡包加载它。

## R-108 和下一项

R-108 保留：主位缺失、旧引用跳过、安装费用/期限和事件窗口、被动已捕获与已开始的区别、逐个全部技能操作、英雄替换的保留/移除策略以及间接激活的完整官方范围。R-107 的数量上限、重复获得、同名去重及正式来源策略也没有因此完成；本批没有新的官方校准证据。

多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。后续继续 M5 的条件/触发/特殊来源缺口；正式池 M0、国服校准 M6、批量卡牌 M7 保持未完成。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为power_lifecycle.py：10动作/42事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。

## 技能安装与预选继承

AddHeroPower和ReplaceHeroPower增加事件前原子choose_branch；ReplaceHeroPower默认clear，显式inherit读取实际被选旧实体的保存配方。完整分支映射支持目标技能改变效果/价格/ID，保留普通/合并角色、来源范围与strict/override。需要原接受分支时显式capture_power_choose_branch再transfer_choose_branch，不能从当前物理配方或最近一次记录猜原根。

引用、主/额外位置、原费用/用途重置和已接受旧主体继续本页生命周期；失效引用不转向新技能，声明错误不因失效静默略过。窗口及字段见[公共契约](m5-choose-branch-producers.md)。当前开发prototype-v149/core-effects-v149、schema144/观察61，不把本页历史示例或旧验证冒作本版或国服证据，实际执行位置仍在两份主台账。

当前共享费用API为prototype-v186/core-effects-v180/schema175，拒旧1～174。后续[本人本局技能次数费用](m3-player-hero-power-count-costs.md)复用原完整hero_power_history，不改变原技能生命周期/其他卡文资格；精确CN仍待校准。
