# 老巨鳍的真实消灭、吐回与原口部关系

[完整批次](../data/cards/gigafin-devoured-minions-v1.json)固定 TSC_962、TSC_962t、TSC_962e“整个吞下”和 TSC_962e2“鼓胀”的完整原行及两份官网双语主面。原本体8费7/4鱼人，巨型生成右侧4/7嘲讽口部；两附魔保留为证据，不另造可打出的卡。不增加标准合法根，不修改[完整13项过去巨型参考](../data/cards/past-colossal-local-reference-v1.json)。

## 证据与执行政策

卡面提供吞噬/吐回和口部永久消灭文本。[官方卡牌库](https://hearthstone.blizzard.com/en-us/cards/74741-gigafin)不展开这些执行步骤。官方论坛的[玩家直接报告](https://us.forums.blizzard.com/en/hearthstone/t/is-gigafin-working-as-intended/88218)及[骷髅伤害报告](https://us.forums.blizzard.com/en/hearthstone/t/gigafin-triggers-death-rattles-of-spooky-skeletons/92577)支持吞噬是普通消灭，会触发受害随从的亡语，甚至能当场杀死本体。它不是不死亡的移出游戏。

[同窗死亡实测](https://eu.forums.blizzard.com/en/hearthstone/t/gigafin-inquiry/7947)报告两部分被一次伤害消灭时随从返回；[口部回手案例](https://us.forums.blizzard.com/en/hearthstone/t/gigafin-interaction/87079)报告重新打出的口部不再消化旧本体库存。[转控案例](https://www.reddit.com/r/hearthstone/comments/107xhdj)报告吐回随从出现在本体亡语执行者的对面。这些是玩家报告，不是当前国服官方规则认证；本地采用该控制方政策，精确窗口及其它未确认差异继续待校准。

## 一次真实销毁与普通来源记录

ConsumptionProfile 新增有限 board_minions。DevourEnemyMinions 必须对应真实已开始的原战吼，查询当前敌方活跃存活战场随从，不收地点、休眠体或后来亡语新召唤的随从。先保存原完整物理材料，在同一handler里委托既有 DestroyBatch 标记整组，再将每个实际原消灭原因与来源、原材料一起记入既有 ConsumedCardRecord。

每个受害者获得一个沿原 consumed_card_id 参数的吐回亡语；整批记录/授予完成后才进入普通死亡检查点和反应。原消灭原因必须匹配卡面、控制方、epoch和入场次序，不以本次全部死亡或当前同ID对象冒充。普通死亡、亡语、复生、额外召唤和伤害继续由原内核执行；本体在随后反应中死亡时，其死亡捕获已有完整库存。来源已离场不能接收新附件时，正文仍消灭原敌方组，不制造不存在的亡语载体。

原手牌、牌库和武器吞噬政策保持；新增 destruction 字段只属于实际战场消灭，不把原静默存储操作冒充死亡。暂缓死亡可以保留准确原标记，但吐回时必须找到唯一对应的真实死亡记录，尚未完成的暂缓销毁明确报未支持，不编造死亡。

## 吐回与口部

ReturnDevouredMinion 只接受正在执行的实际亡语及其原 SummonCause，按冻结 consumed_card_id 读取唯一原死亡，交已有带归因 ResurrectMinion 在当前亡语控制方的对面召唤新的基础实体。原普通增益、伤害和临时附件不保留；Jade、完整合成材料、巨型入场和容量等继续使用原复活配方，不能用白板卡名替代。重复实际亡语沿既有政策执行。

原口部在巨型创建时，把本体的 BoardPresenceReference 放到原亡语能力的 devour_parent。它绑定物理在场区间，不扫描当前同名本体。当前复制保留这一关系，基础复制/回手重置/沉默使用原普通生命周期；单独召唤或重新打出的口部没有旧关系。连续控制/换面沿原 BoardPresenceReference 政策，少见的换面后再次授予、特殊复制及历史间接战吼仍是本地边缘，不能据普通路径声称国服一致。

DigestDevouredMinions 验证实际口部亡语及原关系，只从仍属于原在场本体的当前能力中移除匹配吐回载荷。它不改写不可变死亡捕获、旧消费记录或已吐回的随从；两部分已同时离场时，不撤销已接受的本体亡语。按受害者分别授予的内部粒度、复制继承和精确反应窗口明确作为本地表达政策保留，未获CN完整验证。

## 保存、信息与范围

ConsumedCardRecord.destruction 保存原 DeathCause；AbilityInstance.devour_parent 保存原父体区间，完整实体、死亡与冻结复制材料核关系。新增三个有限效果注册原解释器与续接，core760/schema600拒旧599及以前。观察119/命令13/replay1保持；内部材料、来源/驻留/消费ID不进入玩家DTO，宿主全知快照不能交给玩家。

适配专项沿真实CATA_EVENT_000付款，经明确单卡夹具交付后打出本体。完整13项名单不按原生覆盖裁剪；源域绑定及实际整池入口另验，注册两本体不能替代该验收。版本对齐、热修、权重与国服规则边缘按用户要求继续暂缓。
