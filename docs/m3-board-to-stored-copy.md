# 战场随从直接复制到手牌或牌库

CopyCard可接原历史中的DeathRecord，但仅限BOARD随从印刷base复制，必须逐字段匹配对应原死亡行；不提供死亡current附魔继承。该新增操作数与劫持的两费洗入、core344/schema275边界见[原材料契约](m3-original-material-spells.md)。

复用 `CopyCard`、`MinionReference`、原物理创建与复制附件、`SummonStats`、创建费用及手牌容量。实际进度、验收、下一项和差异仅维护在 [项目状态](project-status.md) 与 [机制清单](mechanism-backlog.md)。

```python
CopyCard(
    MinionReference.capture(source), player_id, Zone.HAND,
    stats=SummonStats(1, 1),
    cost=CostSpec(set_to=1, minimum=0, card_types=(CardType.MINION,)),
)
```

原 `CardReference` 仍仅代表 HAND/DECK，不扩大到战场。`CopyCard.card` 追加已存在的 `MinionReference`；其卡面、控制者、区域修订、入场身份与存活资格在实际执行时复核。源死亡、换形、转控、回手、离场后重入或休眠使引用失效，沿原 `zone_target_skipped` 处理；未知卡面仍报错。复制分配独立实体，原源不移动、消失或死亡。

新复制 owner/controller 为接收者，`origin_entity_id` 保留原物理源。`current` 沿原本地基值、附件、沉默、已消费能力与费用材料规则；`base` 重建印刷材料。战场到存储的当前复制清零战场伤害，不继承攻击次数和冻结状态；接收者光环及条件重新计算，外部光环不是永久材料。伤害清除等精确国服复制政策仍待校准。

在旧位置/来源参数后追加可空 `stats`、`cost`、`expires_turn`。`stats` 复用严格 `SummonStats`，只用于随从；指定生命按原规则清除伤害。`cost` 复用 `CostSpec`、资格及期限验证和 `attach_cost`；未知类型、属性错误、过期期限和不匹配目标在创建前拒绝。复制本地材料后，固定属性和费用在首次 `card_created` 事件前原子安装，不追加事后增益/改费事件。

HAND 复制追加至手牌；容量读取目标玩家的既有 `hand_capacity`。满手时仍创建正确复制及全部数值/费用材料，再沿原创建溢出销毁流程，原战场随从保持。DECK 的 top/bottom/random/整数位置沿原插入和 RNG；它不是物理移区或真实抽牌。实际抽到该新实体后按原抽取/获取流程处理。

原 CardReference 当前/基础复制默认行为保持。原 `discard_copy` 材料仍只允许原玩家的 current HAND 追加，拒绝新属性/费用覆盖；不把被弃牌的原接受契约改成任意区域复制。所有安装、知识、等待、事务回滚、clone/快照/回放复用原模块；没有新增状态、复制执行器、动态主体或组合矩阵。

本轮仅完整隔离适配 OG_291 暗影施法者：5费4/4潜行者史诗，战吼选择友方随从，创建1/1且费用1的手牌复制。MIS_919 和 SW_064 仅完整原始需求依据，未宣称其地标或多次洗牌主体已适配。当前目标补丁正式池与准确国服窗口保持开放。

活动帧 CopyCard 多了三个字段，使用 prototype-v300/core-effects-v302/schema264，旧1～263明确拒绝。没有新 Entity/Player/GameState 字段；观察84、命令12和replay1以及生产代表指纹保持。普通生命/沉默/费用层和来源例外继续按各自已有契约处理。
