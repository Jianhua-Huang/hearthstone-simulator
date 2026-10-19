# 跨区域随从批次、变形与费用保留

当前费用档计算以[进化封顶与退化空档契约](m5-evolve-published-rules.md)为准：原费用不超过10的正增量封顶10，超过10同费；负增量找不到合格档时继续向下探测实际池档位。下文原批次的无封顶公式及不回退政策保留为历史，已由该契约替代；原费用依据、保留费用与区域生命周期不变。

本页描述 M5-12b-02c 公共子集；当前版本和全量结果由[项目状态](project-status.md)统一登记。实现见 [cross_zone.py](../hs_sim/engine/cross_zone.py)，原有[55 项专项](../tests/test_m5_cross_zone.py)保留；v79 新增[能力条件筛选](m5-ability-filters.md)。

## 物理目标与批次

`MinionScope(zones=(HAND, DECK, BOARD), query=PoolQuery(), exclude_source=False)` 声明有序区域、卡牌条件及物理来源排除。`minion_references` 按区域声明和各区域的当前物理顺序捕获目标；只选择指定玩家的随从。战场排除地标、休眠、星舰建造中及已经濒死的实体。职业、种族、费用等仍查询 `PoolQuery` 的印刷元数据；可选 `ability` 明确按当前实体附件或印刷声明匹配。它不把费用过滤改成手牌实时报价。

`exclude_source=True` 只排除来源实体，同卡面另一张仍可成为目标；这与版本池按生成身份排除不同，因此 scope 内禁止使用 `PoolQuery.exclude_source`。跨区目标不去重，每张物理牌独立处理。

`BuffMinionsInZones(player_id, attack, health, scope, source_id)` 先冻结整批引用，再依次组合现有 `BuffStoredCard` 和 `BuffCapturedMinion`。支持永久加攻或减攻及非负生命增益；复杂设值、临时批次和其他卡牌类型不在此入口范围，已有单实体效果仍可单独组合。前一项引发反应后，后续引用必须仍匹配卡面、区域、控制者和区域修订；战场还检查原入场顺序。新生成随从不会加入旧批次，离场、换形、转控后返回的实体不会被误命中。

## 存储区与战场变形

`TransformCapturedMinion(reference, card_id, source_id=None, retained_cost=None)` 接受手牌/牌库的 `CardReference` 或战场 `MinionReference`。目的定义必须是可执行物理随从；存储区还要求其可从手牌打出。即使目标已经失效，也先检查目的定义，不能借失效目标隐藏缺失内容。

变形保留物理 ID、主人、控制者、区域位置和既有获取关联，推进区域修订并重新安装印刷定义。旧属性/费用附魔、动态能力、伤害、冻结、消耗状态、组合组件及临时手牌期限被重置；同名变形同样重置，区别于保留附件的 `UpgradeHandCard`。`retained_cost` 可在重置后附加一个新的设费记录，它在变形事件和后续反应前生效，之后继续受到正常费用光环影响。

战场变形复用已有变形入场流程，保留本回合已用攻击次数与召唤回合，重新处理光环、休眠和巨型附肢；满场时按现有规则无法加入额外附肢。手牌/牌库变形不召唤、不发动战吼、不产生死亡或复生记录，也不重新获取或抽取该牌。新形态之后实际打出时才发动对应战吼。

复制当前形态会复制新附魔并分配独立附件 ID；回手按既有重置规则恢复变形后定义的基础费用。手牌换形保留对手槽位句柄，但撤销已知旧牌面；牌库继续隐藏身份和追踪句柄。私有 `stored_card_transformed` 日志不把隐藏牌面发给对手，牌库中未知实体也不通过此日志暴露给拥有者。

## 按费用档变形

```python
TransformMinionsInZones(player_id, pool_id, cost_delta=3,
    scope=MinionScope(exclude_source=True),
    cost_basis='printed', retain_cost_basis='printed', source_id=source_id)
```

这是依赖已注册池与生成上下文的声明片段。`cost_basis='printed'|'local'` 分别读取捕获时卡面的印刷费用，或基础费用叠加本地有序附魔后的费用；两者都不是历史支付金额，也不含当前手牌光环/玩家费用修正。目标费用为 `max(0, basis + delta)`。`retain_cost_basis=None|'printed'|'local'` 独立决定是否以及按什么依据保留费用，不能混为目标费用。

整个批次先捕获目标、费用档、保留费用、来源卡面与职业依据，并检查所有相关费用档的候选能执行。随后逐个处理，目标仍有效才抽样；过期引用和空档不消耗随机数。前一项反应可以改变场面，但不会改写已经捕获的后续费用档或职业依据。`empty='skip'` 默认保持没有候选的目标原样，`'error'` 明确报错。空目标批次也要求有效生成上下文、版本池和来源。

候选使用显式版本池、权重、身份去重和 `GenerationPolicy`；普通默认生成排除仍生效，额外例外需要单独声明。未实现的合格候选会在整批抽样/变形前报错，不能删掉候选或按已实现数量重新抽样。当前不实现“找不到该费用档时自动降档”的隐式回退。

## 恢复与验证

每个待执行 `TransformPoolTarget` 保存捕获引用、固定查询、职业/来源依据、资格策略、费用保留和空档策略。已经变形的结果不再抽样，尚未处理的目标在恢复后沿同一 RNG 状态继续；加载检查池、定义、目的区域与来源引用。选择分支失败回滚至最近提交边界，包括状态、RNG 和玩家知识；终局停止剩余工作。

专项覆盖三区域增益与变形、排除自身但保留同名副本、印刷/本地费用组合、提前检查缺失候选、空池、身份失效、休眠/巨型/满场、临时手牌期限、复制与回手、来源死亡、选择恢复/回滚/回放、自动施法、法术重复、回溯、预算及玩家信息。计入既有累计结算预算，不因拆成批次而绕过限制。

## 代表、证据与 R-098

艾泽里特龙 `DEEP_999t4` 使用三区域 +3/+3 及物理来源排除。艾泽里特鱼人 `DEEP_999t5` 使用三区域费用加三变形，并暂按印刷费用选择及保留。鱼人的[官方卡库](https://hearthstone.blizzard.com/en-us/cards/104584-the-azerite-murloc/)与[冻结记录](../data/support/excavation-inventory.json)支持基础变形和费用保留文本，没有证明修正费用、顺序或每个复杂交互。

鱼人池 `representative.excavate-transform` 明列 CS2_182、BOT_563、ULD_208、CS2_222、TTN_724 五张样本，分别覆盖四至八费；`complete=False`，并非正式国服池。未覆盖费用档按声明跳过，不能据此宣称鱼人完整适配。两张代表均为 partial / internally_tested；术士蛇 WW_001t25 已在[生命转移契约](m5-health-transfer.md)中实验适配。

**R-098 暂定规则：** 三区域的手牌→牌库→战场顺序，冻结候选及费用依据，逐目标抽样和反应，原费用按印刷值保留，空档保持原样，休眠不可选，临时期限重置，以及战场变形/巨型窗口，均待国服校准。公共接口提供不同费用依据，但参数可表达不等于已判定真实卡牌使用哪种规则。

运行 `python -m examples.excavate_cross_zone`，通过玩家入口先打出龙给三个区域增益，再打出鱼人变形；存储卡恢复新形态基础属性，费用保留四费，战场新光环继续生效。共 2 动作、16 事件，保存恢复与回放一致，见[示例](../examples/excavate_cross_zone.py)。多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。发掘整类与正式池、国服集中校准尚未完成。

M5-12c-03b：`RandomBuffStoredMinion` 选取一个物理存储随从，扩展的 `BuffStoredCard(cost=...)` 同时提交属性与费用附件。`TransformMinionFromPool` 对指定引用共用批量变形的费用档准备与执行；见 [定向修改契约](m5-directed-modification.md)。

v73复验：excavate_cross_zone.py 为 2 动作/20 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为excavate_cross_zone.py：2动作/24事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 存储卡类型范围与既有事件入口

TransformStoredCard新增明确的物理HAND/DECK卡面操作，法术/武器与原随从重置共享同一助手；原MINION范围/随机池/场上分支及保费契约保持。见[普通存储卡变形](m3-stored-card-transform.md)。完整真实来源与国服仍待核实。
