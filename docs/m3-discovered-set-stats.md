# 发现、实际召唤与原对象属性设值

DINO_424英雄欢迎仪式复用普通发现、带原施法原因的场上发现生产者，以及已有SetCapturedMinionStats。完整原行及两张严格双语主面保存于[data包](../data/cards/native-discovered-set-stats-v1.json)，没有发现入手、额外战吼或复制体。实际验收和下一项仅维护在原两份台账。

有限请求为`DiscoverFromPool.set_summoned_stats=SummonStats(10,10)`：需要原来源、SummonCause、一次三个选项的可收藏随从场上发现，默认None。不能与手牌交付、费用、临时牌、黑暗之赐、手牌复制召唤、冻结或发现费用治疗混用，不枚举其他组合。职业资格采用原显式current查询，包含当前英雄职业与中立；这是沿用既有发现政策，历史[官方发现说明](https://news.blizzard.com/en-us/article/19932699/join-the-league-of-explorers-on-november-12)支持职业可用范围，但不认证CN37热修或精确隐式资格。正式候选池和国服校准仍分别开放。

原完整DiscoverySummonOffer和ChoiceResult确定选中牌；原SummonByCard完成所选请求及入场反应后，SetDiscoveredMinionStats(producer_id,index)核原父子关联、SummonCause、原有序交付及关闭状态，再读取该子请求第0次实际交付。只有原MinionReference仍连续驻留且存活时，调用已有属性设值执行器。死亡、变形、转控、离场或重入不能使同名替身接收；原交付失败时接受空续接。数量额外体独立，不因同卡面成为“它”。

设值延用原属性层、光环重算和生命伤害重置，不新建属性账户，不通过额外治疗重造10点生命。原来源、支付、随机、选择、生命周期及死亡继续由公共执行器负责。当前政策是在所选请求全部交付及其反应后设值，且仅原第0次交付接收；这些细节仍待国服校准，不能以内部测试替代官方时序证据。

DiscoverySummonRecord.stat_acceptances保存已接受索引的严格前缀，私有完整事件记录原完成子请求之后的唯一接受。完成生产者必须保留所有应有续接；等待队列须保持原设值/完成控制，选择不能注入这些控制。记录接受和实际公共设值在同一个内部步骤完成，不留可被截断的额外设值队列。异常、终局、真实回溯、独立reader恢复、clone和回放复用原流程。

新增一个请求字段、一个既有记录字段和一个Effect，无新GameState字段或实体字段。core441/schema359拒绝旧1～358；观察91、命令12、replay1保持。内部账本、请求和discovery_summon_stats_started事件不进入玩家DTO或过滤日志，普通属性变化沿既有投影。未知合格内容继续明确报错，不能为让发现可运行而删掉未实现候选。
