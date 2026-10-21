# 本回合原始连击牌数量费用

实际执行、验证结果和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。本契约描述BE_721亚基巨怪的有限真实需求；卡牌已注册或内部验证不能认证完整正式标准池与国服规则。

## 有限声明与原始资格

普通物理随从沿现有报价声明：

```python
player_played_class_cost=PlayerPlayedClassCostSpec(
    card_class=None,
    profile_id='cost.player-played-combo-turn-v1',
)
```

该profile固定按实际payer和报价所处的全局turn筛选，每个符合的原手牌出牌根减2费，最低0。不能把职业、其他数量公式或任意倍率拼进此声明。实际亚基巨怪保持原8费4/5盗贼野兽，战吼沿普通Draw抽一张牌；本体不是连击牌，不给自己的本次付款减费。

纯`play_history.matches_played_combo`读取原手牌根提交付款时的`CostQuoteInput.abilities`。存在未消费的Combo关键词声明或独立combo主体即为当时的连击牌；两者同时存在、多项主体或多次触发仍只贡献一张牌。第一张打出、未满足连击条件、主体尚未结束、以及已付款后被反制的原根按本地profile计入。连击执行历史不是连击牌数量，实际对局的精确反制/未结窗口仍待M6。

这同时覆盖以Combo关键词和普通法术主体表达的连击法术，以及独立Combo主体的随从。资格来自原提交材料，不查当前战场、后来变形的卡牌ID、当前英雄职业或是否已执行Combo。后来沉默、回手、变形或区域变化不改写旧资格；同一实体回手后重新打出是另一个原根。自动施法、召唤、复制、获取、技能、交易和锻造本身不增加手牌根。

## 复用原费用与完整证明

`player_played_class_costs.py`保留原`PlayerPlayedClassCostRow`全部字段和其他profile选择。新profile仅在`PlayerPlayedClassCostFact`增加显式nullable的`combo_inputs`：必须为整个有序原历史逐项保存完整提交输入，包括非连击牌、对手和此前turn。每个输入的source_id、player_id、card_id、kind必须与原冻结卡面一致；数量为完整selected_ids的长度，after严格等于max(0, before-2*quantity)。计数即使超过零费所需数量也不能截断。

原输入只保存物理卡牌和能力材料，不递归嵌入此前整份付款报价。运行时前缀验证将这些材料逐项绑定到实际保留的原`submitted_cost.quote.quote_input`，完整检查实体分配、原卡面、获取/行动时钟与历史长度。相同总数、缺行、换原输入或用当前实体能力代替原提交均不能通过。其他profile必须保存combo_inputs=null，不能借新字段改变职业、上张费用、原套牌或拉法姆的资格。

固有减费后仍沿同一局部附件、外部修正、实际账户支付和最终费用下限。物理/生成报价、玩家费用、合法动作和付款共用同一计算，不另建玩家计数器、回合缓存、价格缓存或第二付款器；查询不消费修正用途、RNG或分配ID。付款在自身新手牌根追加前冻结，后来出牌或推进回合不重算已经支付的价格。

## 生命周期、恢复与来源边界

完整提交输入进入原报价事实、选择等待、JSON与typed帧。晚失败回滚到原待选边界；整次原动作失败则回滚原费用、手牌根和战吼抽牌。恢复、clone与replay沿原解释器；玩家只得到合法最终费用，不接收完整原输入、选择ID列表、原报价或对手隐藏卡牌。

schema508显式要求新字段，旧1～507及未来/非严格整数版本拒绝；没有隐式补旧字段迁移。引入时core-effects-v620、构筑内容v453，观察115、命令12、外层replay1保持。没有新GameState、Entity、Player或CardDefinition字段、Effect、外部动作与队列。

完整原行和双语官网主面固定在[来源包](../data/cards/combo-play-turn-cost-v1.json)。源材料支持每张连击牌减2及战吼抽牌方向；接受窗、反制/退款、授予/特殊来源与正式资格仍需M0/M6。内部前缀一致性不提供未签名存档的外部来源认证。原费用基础见[本回合出牌费用](m3-player-played-turn-costs.md)和[本局原职业费用](m3-player-played-class-costs.md)。
