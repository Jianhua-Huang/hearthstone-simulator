# M5-07b-03b-03：奥拉基尔与动态费用生成

本批接入奥拉基尔，风暴之主 CATA_153，并补入无面巨兽 OG_141 作为十费实验候选。运行时 `prototype-v75` / `core-effects-v75`、snapshot schema 74、内容包 `representative-m5-v38`；玩家观察 v39、玩家命令 v6、外层 replay 1 不变。旧 schema 1～73 明确拒绝。

实现复用已有公共机制：巨型附肢、相邻光环、冻结的 RuleContext、PoolQuery、GenerateFromPool 与生成时费用附魔。没有新增卡名专用结算分支。M5-07 整体未完成；希奈丝特拉重复施放已内部验收，奥妮克希亚生命损失替换已内部验收，M5-07c 兆示组合收尾和 M5-08 裂变公共子集已内部验收；M5-09a 印刷回响/临时手牌已内部验收；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。

## 捕获与生成顺序

1. 打出主体，按既有巨型契约尝试左右附肢，每个入场事件先处理自己的反应。
2. 附肢展开、主体召唤事件及反应结束后，ColossalBattlecry 检查原主体身份和当前战吼能力，取得此时的独立状态快照。
3. `m5.alakir` 从 `context.source.attack` 读取当前攻击力，构造费用上下界相等的普通 PoolQuery；包含附魔、设值、相邻及其他攻击光环。该数值只捕获一次。
4. GenerateFromPool 检查全部合格候选后，按已有规则放回抽样两次；逐张生成，入手事件前安装 `CostSpec(set_to=1)`。

```python
attack = context.source.attack
GenerateFromPool(context.player_id, pool_id,
    PoolQuery(kinds=(CardType.MINION,), collectible=True,
              min_cost=attack, max_cost=attack),
    count=2, source_id=context.source_id, cost=CostSpec(set_to=1))
```

可复用的动态筛选由卡牌行为读取已捕获上下文、构造普通不可变查询实现，无需在查询中保存实体指针或任意回调。候选按印刷费用匹配；一费附魔和后续费用光环只影响生成实体的支付费用，不改写候选元数据。

## 组合边界

| 情形 | 当前内部契约 |
| --- | --- |
| 未强化且双附肢正常入场 | 主体 2 基础攻击 + 两侧各 1，生成两张四费随从 |
| 两次 / 四次兆示后双附肢入场 | 两侧各 +2 / +4，通常生成六费 / 十费随从 |
| 剩余一个 / 零个附肢槽位 | 使用实际入场结果；无其他增益时生成三费 / 两费随从 |
| 手牌增益或入场反应改变属性 | 战吼读取反应后当前攻击力 |
| 主体在战吼前离场、换形或转控 | 原巨型战吼身份检查失效；不生成 |
| 主体在战吼前沉默 | 当前战吼能力被移除；不生成 |
| 第一张生成牌的反应改变主体或使其死亡 | 第二张候选已经选定，不重新查询或取消 |
| 普通召唤、复制主体 | 生成附肢但不触发战吼 |
| 攻击为零、超过十或没有对应费用候选 | 精确查询，不回退或钳制到十；空候选不耗随机数 |
| 同名生成两张 | 允许重复牌面，实体、费用附魔和入手历史相互独立 |
| 满手 | 生成牌仍安装费用，然后按既有满手处理；烧毁不计成功获取 |
| 来源离场、沉默或跨回合 | 已生成的一费附魔保留；当前复制保留，基础复制/打出后回手按已有契约重置 |

突袭/风怒使用既有攻击入口：刚入场可攻击随从两次，不能借突袭攻击英雄，也不会因获取生成牌而重置攻击次数。

## 池与数据证据

`representative.attack-cost-minions` / `representative-attack-cost-minions-v1` 明确列出十四个已适配候选，覆盖一至十费；名单见 [representative.py](../hs_sim/engine/representative.py) 的 ATTACK_COST_POOL_IDS。它绑定 `local-2026-09-23` / `experimental`，允许中立与其他职业，不宣称完整正式卡池或真实抽取概率。

未提供 GenerationContext、正式模式没有匹配池或合格候选未实现时，动作报错并事务回滚；不从注册表自动补池，也不剔除未实现候选。自定义测试池用于零费、二十费及未知候选边界；不会混入真实代表池。

奥拉基尔与无面巨兽的规则文字、属性、元数据和逐条哈希来自同一锁定本地源；无面巨兽为印刷无特殊文字的 10 费 10/10。新增它不表示它属于当前标准模式。官方卡牌库已找到奥拉基尔索引，但页面不提供可读完整规则，不能用作国服精确时序证明。[官方索引](https://hearthstone.blizzard.com/en-us/cards/125442-alakir-lord-of-storms/)

## 验证与校准

[38 项专项测试](../tests/test_m5_alakir.py)验证当前攻击力捕获、兆示/容量/光环、来源生命周期、生成牌费用/隐私、挂起恢复、候选完整性检查、回滚及突袭/风怒交互。

[真实卡牌示例](../examples/alakir_attack_generation.py)通过五条玩家操作产生 36 个事件：打出主体，使用两张一费生成牌，进行两次突袭攻击；保存恢复、动作回放与 CLI 校验一致。它是显式机制场景，不是合法构筑卡组。

```powershell
python -m unittest tests.test_m5_alakir -q
python -m examples.alakir_attack_generation
python -m hs_sim replay outputs/alakir-replay.json --card-set representative
```

**R-080：动态生成的捕获与池规则。** 当前在巨型入场反应结束后捕获攻击力，一次选定两个候选，允许放回，生成费用在事件前安装。国服中的精确捕获窗口、特殊入场干预、候选范围与去重规则仍需 M6 校准；暂定处理复用现有公共契约。全量结果与下一项见 [项目状态](project-status.md)。

v73复验：alakir_attack_generation.py 为 5 动作/38 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为alakir_attack_generation.py：5动作/44事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
