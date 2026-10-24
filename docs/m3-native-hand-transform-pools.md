# M3：原生手牌来源的随机选面

`TransformDefiningHandCardFromPool` 将原候选查询、整数抽样和[原生自身变形](m3-native-defining-hand-source.md)接在一起。它保持同一个物理手牌实体和原生来源，不经过生成新实体或出牌流程。没有第二套随机、费用、触发或选择执行器。

## 请求与候选

请求携带当前手牌 `CardReference`、原始 `defining_card_id`、来源能力 ID、版本池、`PoolQuery`、既有 `GenerationPolicy` 和空池政策。绑定必须属于接收者，原始声明与当前卡面同类型；执行时检查物理引用是否仍匹配。候选统一由 `resolve_candidates` 按完整池、明确过滤和生成身份去重后给出；空 `kinds` 沿原始来源类型补齐，显式其他类型拒绝。

```python
TransformDefiningHandCardFromPool(
    CardReference.capture(context.state.entities[context.source_id]),
    context.trigger.defining_card_id,
    context.trigger.id,
    "experimental.native_faces",
    query=PoolQuery(kinds=(CardType.SPELL,), collectible=True,
        class_mode="specified", classes=(CardClass.MAGE,), include_neutral=False),
)
```

变形卷轴按印刷来源选择法师法术，不能从当前控制者的职业推导。泽鲁斯和熔岩之刃分别选择随从、武器。原始来源 ID 也作为原有 `exclude_source` 查询的来源依据，不改成上次随机得到的卡面。

所有符合查询的候选先检查可执行定义、物理类型及来源生命周期，再接触 RNG。未知候选或尚不支持的另一个原生来源明确报错，不能从池里删去，也不能只等抽中时才报错。过期引用仍核对内容后跳过，不抽样。空池默认保存空结果且不消耗 RNG；`empty='error'` 明确失败并沿事务回滚。

## 抽样、恢复与私有记录

每个实际请求用原 `sample_candidates` 做一次整数权重抽样，随后执行原 `TransformDefiningHandCard`。后续回合依据新的实际局面再接受请求。选择新卡面不创建、抽取、施放或召唤卡牌，不对随机结果额外收费。

私有 `defining_hand_card_randomized` 事件保存完整请求、生成上下文、必要当前职业、实际本方回合开始见证、完整有序候选及权重、结果和 MT19937 前后状态。`DefiningHandTransformDraw` 在本地重演一次抽样；边界校验对注册表重算完整候选，拒绝能够自行重演但已经被裁剪的池。等待帧沿原 codec 保存请求，恢复后才实际抽样。选择失败和后续主体异常一起回滚来源、卡面、记录与 RNG。

记录不进入任一玩家的观察或事件接口。校验只证明注册表/窗口内抽样的一致性，不提供未签名历史的来源认证，也不假设这次抽样之后 RNG 没有被其他合法操作推动。

生成上下文的 `target_id` 是规则库存名称；帧 codec 对这个已知类型按字符串验证，其他实体/记录 ID 仍要求正整数。规则与解释器身份为 `prototype-v266` / `core-effects-v260`；既有状态结构和 schema233保持，玩家接口保持。

## 必要代表与限度

[固定材料](../data/support/native-hand-transform-pool-basics.json)保留三张原生来源、三个来源附魔和六张必要目的牌的12条完整原行。实验只在两张随从、两把武器、两张法师法术之间选面；目的牌使用已有效果，额外补充淡水鳄和刺客之刃的普通印刷定义。实验注册表具有独立来源与池指纹，不改生产代表包。

原始变形卷轴禁止手动出牌是当前明确本地政策，仍待国服校准；无COST原行原样保留，诊断印刷数值使用零默认值。三类持续来源的离手/外部变形政策继承前一契约。完整随机池、其他定义来源、复制/转手政策及国服精确时序未由受限实验覆盖。

实际执行、差异和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。长期目标及 M0正式池、M6国服校准、M7批量接卡保持开放。


## K487 真实泽鲁斯的当前格式入口

[OG_123完整原行及双语主面](../data/cards/past-physical-source-passives-v1.json)接通原defining_hand_source，每个本人开始只返回原TransformDefiningHandCardFromPool。池使用constructed.cards，查询固定collectible=True和MINION，实际GenerationContext继续由宿主格式绑定；不能把“过去的一费随从”调查名单当作泽鲁斯完整随机池。原类型、来源、所有候选预核、整数权重抽样、私有draw证明、自己原始卡面及反复换面生命周期保持。

国服37上线候选宿主仍保留全部源候选；只要符合条件的执行定义缺失，真实回合开始会在抽样前明确失败，原动作和RNG回滚。不会以已接入子集替换全池。完整标准正式池、可达材料和国服规则未据此认证；原实验定义与固定源缓存继续作为独立历史证据保留，实际结果与下一项仅见两份台账。
