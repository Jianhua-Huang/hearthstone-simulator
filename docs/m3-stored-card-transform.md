# M3：普通存储卡牌变形

`TransformStoredCard(target, card_id, source_id=None, retained_cost=None)` 将明确捕获的手牌或牌库物理卡牌变为另一张已注册的物理卡牌。它使用 `CardReference`，不接受场上随从引用。目的地必须能成为物理手牌/牌库卡；未知卡、英雄技能和仅选择用模板明确报错。

```python
from hs_sim.engine import TransformStoredCard
from hs_sim.engine.zones import CardReference

effect = TransformStoredCard(
    CardReference.capture(held_card), 'registered.new_face', source_id,
)
```

这是普通变形，与 `UpgradeHandCard` 的保留附魔升级分别表达。普通变形复用原存储随从的重置过程：清除原附魔、授予能力、费用修改和旧进度实例，按新印刷定义安装属性与能力。同卡面变形也重置。实体 ID、owner/controller、所在区域与槽位、手牌获取记录保持，区域修订推进以使旧捕获失效；不打出、施放、抽取或召唤目的卡，也不自行消耗随机数。

`retained_cost` 复用已有随从变形的显式数值保费能力，只在清除原附件后安装一个新数值费用覆盖。它不是对所有真实变形卡的自动裁定：印刷费用、当前费用、支付账户和数值保留策略仍须由真实卡牌规则确定。它也不保留原属性或其他附魔。

已离开捕获区域或卡面/控制者/修订改变的引用沿原规则跳过；跳过之前仍检查目的定义。玩家信息沿原 `stored_card_transformed` 私有事件和身份隐藏流程处理。选择帧使用解释器登记的新效果类型，恢复、克隆、回放和异常回滚继续由公共层负责。本项引入时GameState/Entity 结构未变，schema 232保持；规则及解释器身份分别为 `prototype-v263`、`core-effects-v257`，旧身份不能混用。

手牌回合事件已有 `HandProgressSpec('event', goal=1, repeat=True, event='turn_started', condition_id=..., on_complete=...)` 表达。它捕获当时的物理手牌和能力实例，来源条件用严格布尔值声明；自然起始抽取发生后取得的牌不追认已捕获窗口，离开并再次进入手牌不恢复旧候选。无需另建手牌触发系统。

普通变形会清掉旧手牌监听；新卡面声明自己的原生监听时重新安装。**这不等于已经实现泽鲁斯等牌的连续变形来源**。连续变形来源如何保留、何时终止，以及随机候选、复制和其他特殊生命周期，仍须按真实证据确定。完整泽鲁斯、熔岩之刃、变形卷轴、幻象、殒命暗影、恶魔计划、美味变异鱼、愚人套牌和普瑞斯托女士均未因此宣称接入。

基础方向来自[完整本地证据](../data/support/stored-card-transform-basics.json)和暴雪[12.0机制说明](https://hearthstone.blizzard.com/en-gb/news/21965466)：历史修正规定三张手牌变形牌清除附魔与减费。该说明不能替代最新国服对每个例外的校准。既有随从能力见[跨区修改](m5-cross-zone.md)，保留附件的升级见[手牌升级](m5-hand-upgrades.md)，原监听见[手牌进度](m5-hand-progress.md)。实际执行及下一项只在两台账维护。


## 当前材料复制到现有实体

TransformStoredIntoCopy使用原当前复制材料安装到已有接收者，与CopyCard的新实体分配及TransformStoredCard的印刷重置分别表达。完整材料安装后才通知，特殊来源与复合政策未由此完成。见[公共契约](m3-stored-copy-transform.md)。
