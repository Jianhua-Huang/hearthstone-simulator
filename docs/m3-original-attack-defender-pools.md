# 原防守随从的随机变形与召唤交付

[完整固定数据](../data/cards/attack-defender-secrets-v1.json)保存偷天换日BT_042、游荡怪物LOOT_079两张原行及四张中英官网主面。来源复用上一批已核验的完整响应缓存和[准备引用](../outputs/card-integration-20261014/k641-original-attack-defenders/source-review-reference-01.json)。过去奥秘72成员及其顺序保留；这两张效果接入不自动开放整池来源。

`TransformAttackedMinion(window, source, target)`仅连接原攻击中的友方受击随从与已揭示奥秘。完整分配和原窗口保存接受身份；实际执行按原BoardPresenceReference找同一连续在场对象，再委托`TransformMinionFromPool`读取当前local费用、按已有+3费用层级和完整绑定标准池变形。揭示反应中的同驻留变形/转控不冒充离场；回手离场不重绑手牌或同ID新驻留。攻击者可以是英雄或强制友方随从；奥秘的对手回合门禁仍由普通SecretSpec执行。普通变形负责清伤、材料、原生能力及生命周期，不执行战吼。

`SummonFromPool.attack_window`和`PoolSummonBasis.attack_window`是默认None的有限可选连接。它要求原英雄受击窗口、完整已揭示来源和普通归属召唤，不叠加回调或另造选择器。原攻击/揭示事件核对接受窗口，来源和cause保持同一物理身份；等待产生新的实体/顺序水位可合法前进。完整候选、权重、池版本、RNG、实际数量计划、位置与普通交付仍由已有pool/quantity执行器负责；无上下文、未知内容和满场/空池保持原明确政策，不按实现率或目标资格裁池。

第一份实际主交付在其入场反应之前通过原RedirectAttack成为原攻击目标，保存真实新驻留，不扫描同名随从或猜实体编号。主交付之后的数量副本继续普通入场，本地政策不重新选择防守者。如果主目标被入场反应消灭或离场，原攻击取消，不回头击中英雄；英雄攻击次数与原武器磨损仍沿既有攻击历史。已经接受的随机材料不因待选恢复重抽。数量翻倍、旧位置/回调/固定替换接口保持各自原契约。

两个新字段进入现有pool basis/帧解析，没有新GameState历史列表或新战斗结算器。完整原窗口和pool basis不进入玩家信息。引入core799/schema622、735效果/283payload，旧1～621需相应旧引擎；默认None请求维持旧路径。

休眠行为是已记录的本地差异：候选保留原生休眠牌，召唤也执行真实休眠材料；目前沿既有活动性门禁，游荡怪物生成非活动主体时不重定向，偷天换日将防守者变为非活动主体后普通战斗取消。[2020年本人报告](https://us.forums.blizzard.com/en/hearthstone/t/bug-wandering-monster-and-dormant-minions/32446)和[2023年本人报告](https://us.forums.blizzard.com/en/hearthstone/t/wandering-monster-and-bait-and-switch-sometimes-bugged/115156)记载过休眠对象反击或触发后续奥秘，与当前本地政策不同；不能把这些历史报告或当前实现冒称正式国服规则。按用户安排，精确休眠资格、数量副本目标、揭示/入场优先级和版本对齐留待校准，不等待实测，也不移除候选。

保存及私有完整事件证明用于内部一致性，不认证未签名存档的外部来源。实际验证、剩余内容和下一项仅维护在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)。
