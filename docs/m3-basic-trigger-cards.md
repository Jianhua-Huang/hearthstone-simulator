# 基础出牌、施法完成、攻击与邻接卡牌

沼地蛇颈龙继续本页与原生触发契约的整次本人法术PlayRecord资格，普通圣盾交原附件生命周期；怒袭甲龙使用正数实际护甲通知，格里什掘洞虫使用实际本体攻击完成事实。入口及准确国服窗口限制见[野兽触发契约](m3-beast-trigger-cards.md)。

本页是接入契约。实际进度/证据/下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护，完整配方在[basic-trigger数据](../data/cards/basic-trigger-effects-v1.json)。

图腾魔像把Overload(1)声明为普通on_play，battlecry为空；实际召唤不执行该出牌效果，后续锁定与历史由原法力模块负责。安瑟祭司的战吼以restored_health查询本回合本人来源实际恢复量，零治疗不满足，给敌方恢复也按来源归属计算；未知归因不能猜成零。实际+3/+3及嘲讽均沿原机制。

每个实际成功法术主体在FinishSpellCast标记completed后发布一次既有spell_cast_finished，包括hand/repeat/effect/draw/history。普通card_played仍只关闭整次物理出牌，不代替每次施放完成；反制等未开始主体没有该完成事件。没有新增事件形状、存档字段或第二份计数；语义由core323标识，schema268、观察85/命令12/replay1保持。手动与重复的逐次完成是本批明确新增的公共通知范围，旧结果不能直接继承为该语义的验证。

逐次完成不能直接作为“你施放”的资格。战地医师老兵订阅原card_played，读取整次完成的PlayRecord，匹配本人、SPELL、未反制及原卡面Holy学派。自动/抽取/历史代施法不触发，额外重复不另算本人出牌，整次主体完成后召唤一次。医生BAR_878t的2/2吸血完整卡面由DBF63321及CORE_BAR_878的COLLECTION_RELATED_CARD_DATABASE_ID直接关联，不按名称猜token。实际SummonByCard、来源、容量和等待仍沿公共层；资格筛选与历史证据见[原生触发契约](m3-reactive-growth-cards.md)。

RuleContext中的cast/power可能是监听对象，不必是当前行为发起者。SummonCause.capture仅当其source_id/player_id与行为来源一致时采用spell_cast/hero_power归因，否则采用实际来源card_effect；观察对象仍留在上下文供条件读取。医生的召唤发起者是老兵，不借用被观察法术的来源身份。没有放宽已有归因校验。

战斗邪犬和怒刺蛮兵在attack_finished绑定原CharacterAttackRecord，校验实际完成游标、攻击者和最终防守者。邪犬只匹配本方原HERO攻击，随从/对方英雄不计；蛮兵只匹配自己是防守者，对全部当前敌角色发一个MINION_ABILITY DamageBatch。已捕获的致命被攻击仍按原主体结算，不增加“必须存活”的文字条件。社区[历史实战解释](https://us.forums.blizzard.com/en/hearthstone/t/warglaives-of-azzinoth/32957)支持致命攻击后的效果仍触发，不能替代当前补丁国服实测。

脏鼠的战吼用带原SummonCause的SummonFromZone：实际对手手牌、MINION过滤、对手接收、random选择，保留原物理牌，不执行战吼；空匹配/满场不伪造交付。商贩的battlecry和deathrattle分别独立声明同一Draw主体，先当前控制者再另一方，疲劳/容量仍原样结算。恐狼只声明原AuraSpec(attack=1,adjacent_only=True)，位移、控制、沉默与消失由原光环层维护，不添加永久增益。

证据边界：完整37.0源证明卡面/标签/费用/身材及医生引用；代码和专项证明内部执行。历史[反制讨论](https://us.forums.blizzard.com/en/hearthstone/t/consistency-with-casting-spells/39311)支持部分“施放后”与未完成主体的区别，但含社区争议，不作为精确国服确认。每次完成的确切发布窗口、死亡/其他监听顺序、归因、治疗条件和正式生成/构筑资格仍待M0/M6；定义存在不等同正式标准完整支持。
