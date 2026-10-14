# 不同本人施法派系的费用输入

实际执行、验收和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本页扩展[原本人施法数量费用](m3-player-spell-count-costs.md)的有限 profile，沿原完整施法历史和固有费用管线，不新增计数模块或执行器。

```python
CardDefinition(
    "TTN_085", "诺甘农的智慧", CardType.SPELL,
    cost=5, spell_school=SpellSchool.ARCANE,
    on_play="wisdom.draw_two",
    player_spell_count_cost=PlayerSpellCountCostSpec(
        "cost.player-distinct-spell-school-count-v1"),
)
# wisdom.draw_two 使用已有 Draw(player_id, 2, source_id=source_id)。
```

必要隔离代表来自[完整本地原行](../data/support/player-spell-school-cost-basics.json)，pin 为 `3e5b8c62504eade691be76949af7e1585c56fe0504b0de6e7cce28b4d7cae64c`。印刷卡面是5费法师史诗奥术法术，主体抽两张牌，按不同已施放派系减费。[官方卡库的检索结果](https://hearthstone.blizzard.com/en-gb/cards/97132-wisdom-of-norgannon/)支持卡文、职业、稀有度及奥术派系；具体接受窗口和国服现行来源口径仍待校准。生产代表包和正式卡池未扩张。

## 有限声明和数量

原默认 `cost.player-spell-count-v1`继续用于普通物理随从，每个本人的原 hand 已接受主体根贡献1。新 `cost.player-distinct-spell-school-count-v1`仅用于普通物理法术，仍选择相同 hand 根，再按原卡面派系去重。未知 profile、错误卡牌类型、非普通出牌形态及另一数量公式同时出现均拒绝，不提供任意谓词或来源组合。

两政策共用原 `PlayerSpellCountCostRow.counts_for`：实际施法方是 payer、origin 为 hand、payload_started 为 true 且没有 failure。新政策把所选根的非空 `SpellSchool`组成集合，集合大小为 quantity；同派系多个物理实体或不同卡名只计一次。`None`沿已有卡面契约表示明确无派系，保存完整行但不新增派系。新政策不是“法术次数”，不依据职业、当前实体卡面或支付费用推断派系。

反制及 repeat/effect/draw/history 行不增加这个本人的派系集合，但完整原前缀保留它们。接受后正在等待选择、或后来被终局中断的手牌根沿原窗口保留；完全执行的 successful 查询不能替代 payload 接受窗。获取此卡前的记录同样计入。本牌费用在自身提交前冻结，其后来接受的奥术主体只影响后续报价。

“你施放”不能仅凭卡文外推到全部卡牌自动施法；旧原手牌根政策保持。其国服来源及接受窗口仍需 M6 校准。

## 原卡面、保存和付款

原 `PlayerSpellCountCostRow`增加一个 `spell_school: SpellSchool | None`，由不可变注册表的原施法 `card_id`获取。`validate_history`先校验全部原记录；`validate_fact`逐行核对原法术类型及原声明派系，包括未计入行。零金额或前面的已匹配行不能隐藏未知原卡。当前实体的变形、转控、死亡不会改写原记录的印刷派系。

旧完整有序行、游标、物理分配、时间线、payer、quantity 和 before/after 保持。数量在原固有层减费，最低零，后续本地/外部层及资源支付共享原管线。物理报价、生成报价、合法操作和实际付款使用同一输入；纯查询不分配实体、不消费 RNG，也不写实体费用缓存。

原付款接受窗重新捕获整份事实；紧凑历史重算被冻结的同一原前缀，不按后来的新增派系重新定价。原自动 payload 可以继续推进，但身份、原派系、来源和失败结果不可改写。此证明不认证未签名归档的外部来源。

普通字典保存把派系保存为显式枚举值或 None，读取时还原 `SpellSchool`；缺失、额外、未知或错误类型字段拒绝。等待帧沿原模型自动类型集合编码为有类型的枚举，不能用裸字符串代替。恢复、克隆、回放和异常回滚共享原管线，已支付金额不再扣取。

引入时 `prototype-v224` / `core-effects-v218`、schema208；旧1～207和错误类型明确拒绝。schema 变化来自原费用行新增字段，不是新 State/Player/Entity/CardDefinition 字段。没有新模型类型、模块、Effect、事件、动作或施法/付款执行器。观察74、命令11、回放1保持；玩家只得到允许观察的费用，不得到完整施法前缀、派系集合或对手隐藏卡面。

正式池、精确费用顺序、来源/等待/终局窗口和国服规则校准继续分别维护；本页不代表 U53 整族或完整基础目标已完成。
