# 原手牌邻居、下一种族费用与条件生命支付

真实DINO_137灵敏的厨师需要对原相邻手牌减费，CORE_BT_416暴怒邪吼者需要下一恶魔减费，CORE_ETC_523死亡金属骑士需要本人英雄本回合被治疗后改付生命值。TLC_823恐惧畏缩与CORE_EX1_145伺机待发复用对应下一次费用主体。完整卡面见[固定配方](../data/cards/next-cost-effects-v1.json)，实际验收和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 原物理邻居

prepare_play在原付款前，按实际手牌顺序捕获左/右HandNeighborFact(entity_id,player_id,card_id,zone_epoch)，保存在PlayRecord.hand_neighbors。空邻居是明确空元组；已提交历史不能缺失该事实。端点不绕回，原邻居不是按卡名或战吼时的新位置重新选择。

submitted_hand_neighbors(context)将原提交邻居转成原HAND CardReference，卡牌使用ModifyStoredCost组合原ModifyCost。该指令在执行时检查区域、控制者、卡面和epoch，失效引用跳过；第一份减费后的反应不会把第二份改加给新的替代实体。它支持既有可出牌类型，不把法术/武器/地标的减费伪装成随从增益。

没有真实手牌提交的回调没有手牌位置，返回空邻居；历史重放和特殊来源的精确位置口径仍须CN校准，不声称已穷尽所有来源。原完整付款/接受状态重做prepare_play并校验原事实，紧凑历史保存物理分配与生命周期引用；选择恢复不重新捕获邻居。公开观察不提供原邻居清单。

## 有限玩家种族修正

AddCostModifier与CostModifier增加tribes_any不可变元组。非空声明限于CARD域、普通MINION负delta且无账户切换/固定赋值；实例的有限用途、到期、原来源和全局附件顺序继续沿原玩家修正机制。

匹配复用当前tribe_state_for，包括原种族附魔、ALL及明确排除；物理报价读原实体材料，虚拟报价读印刷材料且不创建实体。未知必要种族明确拒绝。未匹配卡牌、报价/枚举、普通召唤不消费下一次用途；实际匹配手牌付款消费原已接受的修正一次，多个独立实例依次作用并各自消费。暂时野兽减费在原当前回合到期，恶魔减费没有额外伪造到期。

## 原治疗条件决定账户

CardDefinition.pay_health_if_hero_healed默认false。true仅允许原MANA基准与唯一hero_healed_this_turn固有条件，delta=0、无金额赋值；该事实用于账户选择，金额保持原值。intrinsic_payment(definition,stage)读取原完整HeroHealedTurnMatch：真则HEALTH，假则原MANA。

物理、虚拟、冻结报价及重复接受成本重演共同使用这个函数；随后本地附魔及外部修正仍可以沿原规则改变金额或账户。零实际治疗、其他英雄治疗不满足，回合推进后新报价重新判断。付款后触发或等待不改变已接受账户、不再扣第二次；实际生命扣除复用原付款/实际健康历史，未新增资源余额或治疗缓存。

## 保存、恢复与边界

两项原保存结构扩展，因此schema268拒绝旧1～267，core-effects-v312保护新指令、筛选与账户语义。原测试字节和旧证据保留，旧记录不被静默补成当前原邻居。无GameState/Player顶层新字段，观察85、命令12、replay1及规则302保持；旧代表定义的默认false字段在指纹中省略。

原引用、下一次修正、付款事实、种族材料、治疗前缀与接受帧均由公共codec/事务/回放处理。玩家只看到当前公开费用与实际账户结果，不能读原付款状态、内部条件、邻居或候选。精确原邻居窗口、特殊重放、下一次来源信用与国服账户规则继续待校准。
