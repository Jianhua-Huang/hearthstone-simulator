# M3：原生回合开始变形来源

本契约只覆盖泽鲁斯、熔岩之刃和变形卷轴所需的基础表示：一个物理卡牌保有一个原生回合开始来源，当前卡面可以在原类型内反复变化。必要原卡与定义附魔的六条完整记录见[固定材料](../data/support/defining-source-binding-basics.json)。诊断使用固定目的卡面，不是这些真实卡的完整随机适配或最新正式卡池。

## 来源与卡面

`CardDefinition.defining_hand_source` 使用已有 `HandProgressSpec` 声明。当前只允许 HAND、`turn_started`、重复单事件完成主体；仅在控制者自己的回合开始激活，不接受升级链、任意事件、累计量或动态授予。原生安装为独立 `defining_hand_source` 能力，保存原始 `defining_card_id`、物理来源 ID 和既有进度见证。普通卡面进度仍使用原 `hand_progress` 能力。

```python
CardDefinition(
    "diagnostic.native_source", "Diagnostic source", CardType.MINION,
    attack=1, health=1,
    defining_hand_source=HandProgressSpec(
        "event", on_complete="diagnostic.change_face",
        repeat=True, event="turn_started",
    ),
)
```

来源声明不从 `DEFINING_ENCHANTMENT` 标签自动推导。注册表核对原始声明、来源物理实体和当前类型；原始来源与当前卡面保持同一物理卡牌类型。这一限制适用于本契约的三类回合变形来源，不泛化变色龙、幻象或殒命暗影。没有来源的普通卡牌不增加可执行监听；默认声明为空时保持旧注册表指纹。

## 自身变形与清理

原生主体使用 `TransformDefiningHandCard(CardReference, card_id, source_ability_id)`。引用捕获当前手牌实体/控制者/卡面/epoch；能力 ID 必须指向该实体的原生来源。过期物理引用沿既有规则跳过，缺少来源明确报错。目的卡面必须是同类型的普通物理卡牌；另一个原生定义来源的嵌套不在本契约内。

操作先执行原存储印刷重置，清除旧数值附魔、减费、卡面监听和普通附件，再只装回当前原生来源。保留来源能力 ID、原始卡牌 ID、进度和见证，保持接收者实体、归属、区域、槽位与获取记录；epoch 每次推进。变回原始卡面时仍保留同一来源，不另开一条进度链。安装完整后才发布原变形通知，不创建、抽取、打出、施放或召唤目的卡牌。

事件捕获、布尔条件、去重、主体调用、选择、恢复和回滚沿既有解释器。原生见证必须对应实际发生的本方 `turn_started`，保存顺序和完成次数；待选效果也核对当前绑定。存档为 schema233，拒绝旧 schema1～232；规则/解释器身份为 `prototype-v265` / `core-effects-v259`。见证与来源身份只供可信内核使用，不加入玩家 DTO；未签名存档不提供来源认证。

## 生命周期政策及范围

- 原始卡面在 HAND 或 DECK 创建/重置时安装来源；在 DECK 不触发，获取后等待自己的下一次回合开始。
- 自身变形保留该原生来源；普通外部变形按既有印刷重置清除旧来源，必要时从新卡面新装原生声明。
- 当前本地政策：离开手牌时退役原来源；当前变形卡面再入手不自动恢复已经退役的来源。明确重置/新建仍沿印刷声明安装。
- 带此来源的当前附件复制和手牌间转移明确报错，等待各真实来源需要时确定政策。印刷新建副本仍沿普通创建管线；不能把当前复制报错解释为官方不可复制规则。

暴雪[12.0机制说明](https://hearthstone.blizzard.com/en-gb/news/21965466)支持构筑三类变形清除旧增益/减费的方向。[27.6公告](https://hearthstone.blizzard.com/en-gb/news/23989479/27-6)的泽鲁斯保留增益改动标为战棋，不能用来覆盖构筑政策。离手、精确来源退役及触发先后仍是待国服校准的本地契约；完整随机候选池、其他定义来源和真实卡主体未因这项表示而完成。

实际执行、已知差异和下一项仅在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。原普通变形和当前物理复制见[存储变形](m3-stored-card-transform.md)与[复制变形](m3-stored-copy-transform.md)。

随机选面复用入口与私有抽样记录见[随机选面契约](m3-native-hand-transform-pools.md)。实际执行与下一项仅在两台账。
