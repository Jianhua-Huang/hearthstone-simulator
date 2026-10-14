# 本局本人邪能法术次数计费

`PlayerSpellCountCostSpec('cost.player-fel-spell-count-v1')`扩展已有[本人施法次数](m3-player-spell-count-costs.md)消费者。与总次数及[不同派系数](m3-player-spell-school-costs.md)共享原完整施法前缀、原卡面派系、固有费用层和付款管线，没有新账本、状态字段、模型类型或执行器。

这个有限政策只用于普通物理随从。原 `PlayerSpellCountCostRow.counts_for`先选择 payer 的已接受 hand 主体根，再选择原 `SpellSchool.FEL`，每个原物理根减1，最低零。同派系不同实体均计数；其他派系及明确无派系行保存但不减费。对手、反制、repeat/effect/draw/history 来源不改原 hand 根政策；卡文不能单独证明所有自动来源的施法信用，精确国服口径仍待校准。

计数跨回合、包括获取本牌之前的历史，不依赖手牌驻留、当前牌面、当前职业或已付法力。已接受但仍等待选择的手牌根沿原窗口计数；后来新增记录只能影响新报价。已提交价格保留完整有序原前缀，原身份、派系、失败结果和用途不能改写；未选中的未知原卡面也明确拒绝。

物理、生成、合法操作及实际付款共享原数量。已有本地和外部费用层继续作用；查询不分配实体、不消费随机或写缓存。JSON、typed-frame、恢复、克隆、回放、异常回滚及玩家信息边界均沿现有管线，完整前缀不提供给玩家。

[必要完整本地原行](../data/support/player-fel-spell-count-cost-basics.json)只在隔离实验注册表适配 `CATA_529`贪婪的邪能钓鱼者：6费5/5，恶魔猎手稀有纳迦，没有战吼、亡语或其他主体。生产代表包与正式池未扩张。官方[卡库表格](https://hearthstone.blizzard.com/en-us/cards?set=wild&viewMode=table)检索结果提供相同数值及类别；[独立页面](https://hearthstone.blizzard.com/en-us/cards/122775-ravenous-felfisher/)本次读取仅返回动态外壳，未据此宣称官方卡文或时序校准。

本增量仅增加已存在单字段 `profile_id`的一种有限值，并更新共享效果版本至 `core-effects-v289`。`prototype-v291`、schema255、观察84、命令12、replay1及原保存字段集合保持；旧效果版本不被新包静默认证。其他学校公式、任意筛选语言、授予、组合、全部来源与国服校准不由本契约承诺。实际验收和下一项仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。
