# 特殊生成资格与连续发现后的交付

M5-12b-02b 公共子集；`prototype-v75` / `core-effects-v75`、snapshot schema 74、representative-m5-v38、player-view-v44。旧 1～71 快照明确拒绝；玩家命令 v6、外层 replay 1 保持。实现见 [pools.py](../hs_sim/engine/pools.py) 与 [discovery.py](../hs_sim/engine/discovery.py)，[48 项专项](../tests/test_m5_discovery_delivery.py)已通过；全量结果由[项目状态](project-status.md)统一登记。

## 按效果声明生成例外

`GenerationPolicy(allowed_special=(Keyword.TITAN,))` 只允许当前效果绕过指定关键词的默认生成排除。默认仍排除泰坦、任务与任务线；允许泰坦不会同时允许任务。可用于 `GenerateFromPool`、`DiscoverFromPool` 和 `CastFromPool`；不可传任意关键词或全局关闭限制。

资格策略与查询分开：`keywords_all=(Keyword.TITAN,)` 只要求印刷关键词，本身不会解除默认排除。允许例外后仍应用目标/模式、显式池成员、费用/职业/类型、来源和其他排除、生成身份去重及权重。全部合格候选必须有可执行定义，缺失实现先报错，不能在抽样时悄悄删牌。显式发掘奖励配置继续使用自身清单。

## 多轮发现与获得时机

`DiscoverFromPool.count` 仍表示每轮展示选项数，默认三；新增 `discoveries` 表示选择轮数，默认一。每轮独立抽样，单轮不重复身份；`replacement=True` 允许不同轮选到同一身份，`False` 则从后续候选中排除已经选中的生成身份及别名。仅被展示而未选中的牌不因此排除。

`destination` 支持 hand、board、deck；`delivery='after_each'` 在每次选择后获得一张，`'after_all'` 在所有选择结束后按选择顺序获得。hand/deck 支持生成费用和期限，deck 支持插入位置；board 复用召唤、巨型、容量与反应规则，不触发战吼，也不消耗被选牌的法力费用。

```python
DiscoverFromPool(player_id, pool_id,
    PoolQuery(kinds=(CardType.MINION,), min_cost=8, max_cost=8,
              collectible=True, class_mode='current'),
    source_id=source_id, discoveries=2,
    destination='board', delivery='after_all', replacement=True)
```

示例中的类型需从 `hs_sim.engine` 导入，池及行为需要注册。全部选完前只记录选择，不提前创建实体或占据战场。满场仍可进行发现；每个实际召唤时重新检查容量，前一随从及其巨型附肢可能占满空间，使后续召唤无效。没有可选候选则停止后续发现，已经选择且尚未获得的结果仍按顺序交付。来源离场不撤销已经排定的发现，终局停止剩余工作。

下一轮重新读取当前职业和来源身份，因此逐轮交付产生的反应可以影响后续候选。已完成选择保存当时的职业、来源卡面及选中身份，不用后来的职业重新解释历史选择。

## 恢复、事务和信息

`DiscoveryPick`、`ContinuePoolDiscovery`、`ResolvePoolDiscovery` 为不可变、可序列化的选择记录和续接效果。每个选项保存本轮完整展示名单及已选结果；暂停时不重新抽样，加载时验证候选资格、数量、身份去重、此前选择、目的区域和选项结构。未知候选、伪造身份和不一致批次明确拒绝。

每次提交仍沿用既有事务边界：选择失败时恢复该次提交之前的状态、随机数、事件与知识，保留此前已提交选择。多轮选择计入累计结算预算，不能通过反复挂起绕过限制。支持自动施法的随机或玩家选择、法术效果重复、回溯撤销、嵌套选择以及保存/克隆/动作回放。

玩家视图增加 `purpose='pool_discovery'`。选择者看到候选句柄和卡面，对手只知道哪一方正在选择；此前延迟交付的选择不通过公共日志泄露。入手、烧牌、入场与牌库可见性沿用相应区域原语。全知快照和内部选择记录不能作为玩家观察数据。

## 必要代表和 R-097

只增加两张验证所需代表，均为 partial / internally_tested：

| 代表 | 公共组合 | 实验候选范围 |
| --- | --- | --- |
| 艾泽里特鹰 WW_001t24 | 明确允许泰坦生成，随机加入手牌并设为一费 | `representative.excavate-titans`：仅艾欧娜尔 TTN_903 |
| 艾泽里特牛 WW_001t27 | 两轮发现八费可收藏随从，完成后依次召唤 | `representative.excavate-eight-cost`：TTN_724、TID_711、CATA_150；再应用当前职业加中立过滤 |

两池均是显式、不完整的 experimental 清单，不通过扫描已实现卡牌推导，也不代表正式国服候选分布。原始卡文与指纹保留在[宝藏快照](../data/support/excavation-inventory.json)与[代表台账](../data/support/m1-representatives.json)。新增生成的泰坦保有独立的三项能力；重复选择同一卡面会在交付时创建不同实体。

**R-097 暂定契约：** 鹰使用不限职业的泰坦候选；牛使用当前职业加中立的八费候选，每轮重新发现、可重复选择同一卡面、两轮结束后依次召唤。满场继续发现、巨型展开及各交付间的反应窗口、职业变化与来源变化的读取时机仍待国服证据校准。本地卡文只证明基础效果，不足以证明这些精确边界。

运行 `python -m examples.excavate_generation`，通过玩家接口打出鹰、使用一费泰坦，再打出牛连续选择两次同名八费随从；第一次选择后保存并恢复，最终得到两个不同实体。共 5 动作、20 事件，保存恢复与回放一致，见[示例源码](../examples/excavate_generation.py)。

多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。发掘整类、正式池与国服集中校准尚未完成。

v73复验：excavate_generation.py 为 5 动作/24 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为excavate_generation.py：5动作/30事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
