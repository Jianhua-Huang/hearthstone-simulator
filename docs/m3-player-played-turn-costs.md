# 本回合本人使用牌数的独立费用输入

实际执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约定义一个有限基础输入，不代表U53整族、正式卡池或国服规则已经验收。

## 有限声明

普通物理随从复用原声明：

```python
player_played_class_cost=PlayerPlayedClassCostSpec(
    card_class=None,
    profile_id='cost.player-played-card-count-turn-v1',
)
```

旧默认`cost.player-played-class-v1`继续要求一个严格的可玩`CardClass`，按整局原印刷职业筛选。新profile必须显式`card_class=None`，固定按实际payer与原报价的全局turn筛选全部牌型、全部职业。不能把单一职业、种族或另一时间条件拼进新profile；未知profile、错误参数/类型、非普通物理随从和同时声明另一数量公式均拒绝。

必要隔离代表是[完整本地AV_134霜狼将领](../data/support/player-played-turn-cost-basics.json)，canonical pin为`9abbe8fcf3ccb0410bd7a2920a90699737bf7e9c003c9b52afbb05d1b5d67c35`。原印刷卡面为4费3/3中立稀有，按本回合本人使用牌数减费；无额外战吼或亡语。生产代表包及正式卡池不扩张。[官方卡页](https://hearthstone.blizzard.com/en-us/cards/70238-frostwolf-warmaster/)本次直接返回导航壳，不能作为当前国服接受窗口的证明。

## 原根、回合与数量

`player_played_class_costs.py`继续读取全部原`play_history`、验证原付款收据、物理获取和完整冻结卡面。新profile调用原`played_cards(..., turn=state.turn)`，不创建第二历史、玩家计数器或回合缓存。每个符合实际payer和原全局turn的原物理手牌出牌根贡献1，最低费用零，数量不因费用到零而截断。

各类手牌出牌、中立/其他职业/双职业、零费和替代资源付款都按根计一次。同一实体回手再打出是另一个根。普通召唤、自动施法、技能、获取、交易及锻造本身不新增此根；这些操作如果由本人使用的一张手牌执行，那张手牌根仍计一次。

原`PlayRecord`在付款完成后、`card_committed`前已经存在。已付款反制根、等待主体完成的根，以及后来被终局打断的已提交根沿原本地政策计入；失败或不足付款动作由事务回滚。卡文不能代替精确国服时点证明，反制/退款、未结窗口和特殊来源仍需M6校准。

新付款的费用在自身根追加前冻结，本牌不能给自己这次付款减费；追加后可影响后续报价。获取该随从之前、仍在当前turn的历史同样计入。真实回合切换后新查询使用新turn，两方重新按该turn筛选；整局职业profile不重置。不同于“最近一次本人回合”，也不改owner区间或原手牌进度。

当前变形、英雄职业变更、转控或区域迁移不能改写原根。完整原定义是已知的，即使可选职业元数据为None，新全牌型profile也无需猜测职业；仍须逐行核对原卡面。原职业profile继续要求必要职业数据，不据新profile放宽其条件。

## 原证明与付款

原`PlayerPlayedClassCostRow`和`PlayerPlayedClassCostFact`所有字段保持。完整有序原卡面、原turn/action与获取身份、实际payer、分配上界、历史游标、selected_ids、quantity、before/after进入原固有阶段；包含对手、此前turn和其他未计入行。事实按自身已冻结turn重算完整选择，不用当前turn重算原已付金额。

金额仍为`max(0, base_cost - quantity)`，后续本地、外部层和资源账户沿原费用管线。物理、生成、玩家显示、合法操作与付款共享同一数量。查询不分配ID、不消耗RNG、不写实体印刷费用。原接受窗口从真实状态重取完整输入，后来追加根、完成原主体或推进回合不改变旧付款；紧凑前缀允许合法后续进展，拒绝替换原卡面、删尾、换时间或用相同总数冒充完整选择。

严格字典恢复允许此spec的`card_class`显式为null，再由profile检验资格，不把null默认成圣骑士。typed帧复用既有模型及`CardClass | None`声明。选择恢复、clone、replay和异常回滚沿原解释器；待选之后的异常回滚到原待选边界，已经提交的付款保持。

保存证明不提供未签名归档的外部来源认证。玩家只看到自己合法的最终价格，对手手牌、完整原前缀、分配身份、selected_ids和付款证明不输出到玩家接口。

## 协议与剩余范围

引入时规则`prototype-v225`、效果`core-effects-v219`。字段和schema208布局保持，旧1～207及未来/非整数schema拒绝；同schema的旧规则或效果签名也拒绝。观察74、命令11、replay1及生产代表64/合成3保持。没有新模型类型、字段、模块、Effect、事件或动作，也没有新的出牌、回合、支付或保存执行器。

原职业费用契约见[本局职业出牌数量](m3-player-played-class-costs.md)。已有TID_077隔离声明的race18种族标识对齐生产解析器的小写elemental，原raw/pin及全局匹配保持，不扩大到其他元数据。

精确接受窗、反制/退款、开局前根的真实来源归属、费用层顺序、特殊复制/来源和当前国服规则仍开放。有限profile不证明全部基础机制、正式池、M0/M6/M7或完整模拟器已完成。
