# 古神独立基础机制：前审与实施边界

独立基础入口已接入，内部验证结果以台账为准；这不表示四位古神的专属卡牌主体已实现。本页保存基础契约；实际执行、验证结果和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 已确认的规则

[官方机制页](https://hearthstone.blizzard.com/en-us/expansions-adventures/reign-of-the-black-empire)明确古神有四个技能，耗尽技能前不能普通攻击，构筑时每副套牌最多一位古神。

[设计师 John McIntyre](https://www.reddit.com/r/hearthstone/comments/1whw4cv/comment/paeyvcj/)明确：每回合第一次技能使用是免费动作，后续技能使用占普通攻击机会。通常前两回合各用两个技能，第三回合攻击；如果某回合只剩最后一个技能，首次使用后还可普通攻击。不能把两次技能使用当成自带风怒。

[工程师 Clay Howell](https://www.reddit.com/r/hearthstone/comments/1whw4cv/comment/pco65e4/)明确：现有普通攻击次数为1/2/4时，古神额外拥有首次技能机会；总量受四个尚未使用技能限制。超级风怒下四个技能用完还能普通攻击一次。这是已有攻击次数规则在本机制内的预算，不建立组合待办或任意授予功能。

[冻住和最后技能说明](https://www.reddit.com/r/hearthstone/comments/1whw4cv/comment/pbldtk8/)与[耗尽后的当前复制说明](https://www.reddit.com/r/hearthstone/comments/1whw4cv/comment/pb92ioj/)提供必要生命周期依据：最后一个免费技能后保留普通攻击机会；复制已耗尽技能的当前随从可以立即攻击，且不自带风怒。当前复制应保留已消费能力材料，这是从复制说明与现有材料模型得出的实现依据，不将“每局一次”解释为全体同名新实体共享禁用账户。

[官方团队问答](https://www.reddit.com/r/hearthstone/comments/1whw4cv/reign_of_the_black_empire_how_does_this_work/?sort=qa)确认随机生成排除政策沿泰坦。命名特许来源继续通过现有生成资格声明处理，不从普通池删掉未实现内容来假装支持。

## 实施路径

复用 ActivatedAbilitySpec、物理 AbilityInstance.consumed、UseMinionAbility 和原目标/使用规则/场位条件。泰坦仍是三个能力；古神必须四个不同能力，两种入口政策互斥，不补任意授予或刷新。

Entity.old_god_free_used 严格布尔记录当回合首次技能机会是否已用，第二次起沿原 attacks_this_turn 计费。原实际回合开始和物理重置负责清理；当前复制保留消费材料，但新实体不复制当回合计费状态，基础复制取得原始四能力。原控制转移保留当前计费与消费材料，直到真实回合清理；没有全局同名禁用账户。普通攻击仍由公共攻击资格、次数及目标规则判断；四个技能没有全部耗尽前禁止普通攻击，耗尽后的新复制沿泰坦相同的立即攻击资格。冻住沿原丢失机会与本人结束期限判断，休眠禁止技能，沉默移除能力和关键词。

注册要求普通随从、四个不同能力 ID 和独立 OLD_GOD 关键词；泰坦保持三个能力，两种政策互斥。GrantKeyword(OLD_GOD) 沿原禁止未声明入场机制的守卫报错。生成库存中的 OLD_GOD 沿现有特殊生成排除政策，只能由明确 GenerationPolicy 特许来源进入；未知执行定义依旧报错。构筑主卡组累计同类关键词最多一张，分别于单卡副本上限；侧板、专属包及其他具体来源的限制政策仍属M0/M7核对，不能据此宣布整个构筑来源完整。

等待选择、失败回滚、JSON快照、独立注册表恢复、回放和玩家命令边界复用已有解释器。公开能力列表和原命令入口继续使用现有DTO，不显示内部 old_god_free_used 或全知证明；可用动作由公共枚举给出。首次引入为prototype-v287/core-effects-v281/schema251，旧schema1～250需要原引擎；观察82/命令12/replay1保持。没有新增运行时模块、顶层状态账本或能力授予功能。

只用一个基础诊断载体验证四技能及预算；固定原卡见[完整raw与规则依据](../data/support/old-god-foundation-audit.json)。克苏恩的全局三倍奖励、追随者额外触发、其他古神的专属主体、拼装和批量接卡后置，不把它们纳入本项门槛。

## 版本与当前范围

[国服36.6公告](https://hs.blizzard.cn/news/24294373/index.html)公布国服扩展上线日为2026-10-21；三张活动赠卡在10月7日至21日可提前加入套牌。这项已公布的新关键词可先完善基础机制，但不能宣称整个扩展已经在当期国服普通构筑开放。正式池、准确客户端规则和国服运行校准仍须分别验证。


## 尤格四个原生技能与尚未接入的代打来源

BE_009t1～t4仅作为四个真实技能标签及ActivatedAbilitySpec主体接入，不是可入手使用的法术。完整原行保留隐藏费用None，官网两语言的显示零费经显式归一化记录；原根BE_009仅保存证据，没有注册战吼或宣称整卡可执行。固定原行、主面及推断边界见[技能资料](../data/cards/yogg-skills-v1.json)和[来源政策](../outputs/card-integration-20261014/k501-yogg-native-skills/source-policy-01.json)。

头脑沿AddSpellRepeatModifier接受一个本回合、一次用途、两次施放的全学派自动CAST预算；没有新增账户或重复支付。原单学派政策与手动限制保持。新增有限声明只允许原创建回合到期；未消费的预算自然到期须有同一实际owner区间的turn_ended和end_event证明，不能从事件序号猜回合，已退役用途不能再次到期。疯狂沿原Damage执行10点随从技能伤害，不产生法术CAST，也不受法术伤害加成。

崛起在首个变形前捕获本人全部原手牌法术、当前报价加三的目标档和本地保留费用，逐一交TransformStoredFromPool，保持物理位置和原通知/恢复流程；不改随从或敌方手牌。当前报价/本地保留值、整批捕获窗口和空档跳过是明确内部政策，未国服校准。领域沿DrawMatching随机检索五个原物理法术，满手仍逐张抽取并烧牌；随机顺序及无匹配跳过沿现有政策，仍待M6。未知合格候选报错，不能通过删池规避。

[HearthstoneTeam开发者说明](https://www.reddit.com/r/hearthstone/comments/1wuibfx/developer_insight_reign_of_black_empire_old_gods/)明确代打采用类似普通难度练习AI的决策，开局先用技能；同时选择领域和崛起时领域先结算，崛起的选取机会与其他技能相同。此说明不提供完整决策排序或国服轨迹。下一项须实现真实整局一次战吼、来源绑定的结束/代打回合以及可恢复的原生动作入口；递归调用Game.apply或把普通手动额外回合当代打都不符合现有边界。实际验证、版本和下一项只记原两份台账。
