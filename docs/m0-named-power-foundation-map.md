# 命名 power 标签与公共基础对照

此页是固定本地数据的静态查阅表，实际进度和下一项仅在 [项目状态](project-status.md) 与 [机制清单](mechanism-backlog.md) 维护。

仅覆盖 93 个已命名 power 标签，并非 93 种机制，也不是完整关键词、机制或正式池的分母。每行保留全部原始载体引用、卡面类型和原行哈希，绑定当前 81 个公开声明／读取符号、9 个源码文件。这里只证明现有表达路径和待核政策，不证明整族真实来源全部实现或精确国服一致。

[完整机器表](../data/support/named-power-foundation-map.json)绑定 36022 行本地卡库，SHA256 为 `fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`；固定 36.6.0.251952/zhCN 数据仍不等于当前国服正式池。其他 369 个命名符号、数值标签、加粗／非加粗真实卡文、服务端规则及可达衍生物继续核对。

## 分类边界

- 公共基础／已有表达／独立政策只指公共路径已存在；所有行明确保留完整来源、正式池和国服未认证标记。
- 其他模式按实际引用、类型、前缀和卡文识别；不可仅因不可收藏就排除构筑可达衍生物，也不从同一个标签强加同一种主体。
- 视觉／内部提示不产生一个新效果执行器；真实卡文仍必须由相应公共能力或卡牌行为处理，未知内容仍不得当白板。

## 需要保留的区别

**无关键词重复与回响。** 原 `HandRepeatSpec(echo=False)` 已明确支持本回合重复副本的最终最低费用 0；回响副本为 1，原牌没有被统一加下限。[原临时手牌契约](m5-echo.md)、[当前实现](../hs_sim/engine/temporary_cards.py)和[原专项](../tests/test_m5_echo.py)已有这一分离，本批没有修改或重跑它们。[2019 官方更新](https://hearthstone.blizzard.com/en-us/news/23239986)限定回响副本的最低费用；[女巫杂酿官方卡页](https://hearthstone.blizzard.com/en-gb/cards/52421-witchs-brew/)说明其本回合重复文字。五条 NON_KEYWORD_ECHO 来源完整保留，R-084 提交／反制／生成时序仍待国服校准，完整真实主体归 M7。

**FORGETFUL 不是统一主体。** GVG_065 等普通错误敌人已有 [公共表达](m2-wrong-enemy-attacks.md)；WW_419 是概率改为本回合英雄加攻，WW_420 是攻击时概率获得不同能力，不能都做 RedirectAttack。保留完整 11 行来源，仅按对应真实主体使用既有能力，不建立关键词组合族。

**其他载体提示。** CANT_BE_SILENCED 主要是附魔／逐载体清理提示，不能给所有随从增加免沉默。AFFECTED_BY_SPELL_POWER 当前 144 引用为 67 法术、31 附魔、46 佣兵能力，无英雄技能载体，不能仅凭这个标签给英雄技能加法强。HIDE_STATS 包括变形卷轴／殒命暗影的实际主体；COSMETIC_ACTION 是四英雄外观。SKIP_MULLIGAN 的两 Story 英雄和 SECRET_DEATHRATTLE 的冰封洛卡拉保留为相应模式资料，不能作为当前构筑缺口。

## 全部命名标签

| 标签 | 路由分类 | 现有表达或政策 | 参照 |
| --- | --- | --- | --- |
| ADJACENT_BUFF | 公共基础入口已有 | 原AuraSpec/KeywordAuraSpec及持续刷新；AURA不是任意新行为的执行指令。 | [AuraSpec](../hs_sim/engine/model.py)；[CardDefinition.auras](../hs_sim/engine/model.py) |
| AFFECTED_BY_SPELL_POWER | 数据提示 | 144行仅法术67/附魔31/佣兵能力46，无HERO_POWER载体；法强语义必须由实际伤害类型表达。 | [DamageKind.SPELL](../hs_sim/engine/model.py)；[prepare_health](../hs_sim/engine/health_rules.py) |
| AI_MUST_PLAY | 其他模式／内部策略 | 当前冒险/乱斗/AI等载体的特殊策略，不把它们自动外推为构筑机制。 | 固定原始引用，待对应模式／实际卡文审查 |
| AURA | 公共基础入口已有 | 原AuraSpec/KeywordAuraSpec及持续刷新；AURA不是任意新行为的执行指令。 | [AuraSpec](../hs_sim/engine/model.py)；[CardDefinition.auras](../hs_sim/engine/model.py) |
| AUTO_ATTACK | 其他模式／内部策略 | 当前冒险/乱斗/AI等载体的特殊策略，不把它们自动外推为构筑机制。 | 固定原始引用，待对应模式／实际卡文审查 |
| AVENGE | 其他模式关键词 | 当前引用为战棋或相应TB来源，传统构筑主线不新增战棋关键词执行。 | 固定原始引用，待对应模式／实际卡文审查 |
| BACON_RALLY | 其他模式关键词 | 当前引用为战棋或相应TB来源，传统构筑主线不新增战棋关键词执行。 | 固定原始引用，待对应模式／实际卡文审查 |
| BATTLECRY | 公共基础入口已有 | 原打印战吼及整次出牌窗口。 | [CardDefinition.battlecry](../hs_sim/engine/model.py) |
| CANT_BE_SILENCED | 按载体区分政策 | 原100候选逐载体审查已有；附魔标签不能推导全局随从免沉默。 | [m2-freeze-prevention](m2-freeze-prevention.md) |
| CASTS_WHEN_DRAWN | 公共基础入口已有 | 原CastWhenDrawnSpec与抽取链替代入口。 | [CardDefinition.cast_when_drawn](../hs_sim/engine/model.py)；[CastWhenDrawnSpec](../hs_sim/engine/model.py) |
| CHARGE | 公共基础入口已有 | 原Keyword.CHARGE与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.CHARGE](../hs_sim/engine/model.py) |
| CHOOSE_ONE | 公共基础入口已有 | 原ChooseOneSpec与普通根分支；组合政策不属于当前开发。 | [m5-choose-one](m5-choose-one.md) |
| COMBO | 公共基础入口已有 | 原CardDefinition.combo与提交时冻结连击资格。 | [CardDefinition.combo](../hs_sim/engine/model.py)；[PlayRecord.prior_turn_plays](../hs_sim/engine/model.py) |
| CORRUPT | 公共基础入口已有 | 原手牌进度与跨形态升级。 | [HandProgressSpec](../hs_sim/engine/model.py)；[CardDefinition.hand_progress](../hs_sim/engine/model.py) |
| COSMETIC_ACTION | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| COUNTER | 公共基础入口已有 | 原反制窗口；仅标签不能替代真实反制主体。 | [CounterSpell](../hs_sim/engine/interrupts.py) |
| DEATHBLOW | 其他模式关键词 | 当前引用为LETTUCE能力/佣兵相关来源，不新增佣兵规则。 | 固定原始引用，待对应模式／实际卡文审查 |
| DEATHRATTLE | 公共基础入口已有 | 原打印亡语、自然/主动接受、死亡材料与禁止门禁。 | [m2-deathrattle-prohibition](m2-deathrattle-prohibition.md) |
| DISCOVER | 公共基础入口已有 | 原RequestChoice/池候选与获取，完整合法池归M0。 | [RequestChoice](../hs_sim/engine/effects.py) |
| DISGUISED | 公共基础入口已有 | 原disguised声明/出牌/目的方控制与位置。 | [m3-disguised](m3-disguised.md) |
| DIVINE_SHIELD | 公共基础入口已有 | 原Keyword.DIVINE_SHIELD与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.DIVINE_SHIELD](../hs_sim/engine/model.py) |
| ECHO | 公共基础入口已有 | 原HandRepeatSpec(echo=True)，副本HandLifetime最终minimum_cost=1。 | [m5-echo](m5-echo.md) |
| ELUSIVE | 公共基础入口已有 | 原Keyword.ELUSIVE与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.ELUSIVE](../hs_sim/engine/model.py) |
| EMPOWER | 公共基础入口已有 | 祈求对应原Invoke共享身份/计数/职业收益派发。 | [m3-invoke](m3-invoke.md) |
| ENCHANTMENT_INVISIBLE | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| END_OF_TURN_TRIGGER | 原能力已有表达 | 原事件/健康结果/触发谓词表达；须按实际主体条件，不凭标签自动附加收益。 | [m2-health-rules](m2-health-rules.md) |
| ENRAGED | 公共基础入口已有 | 原SELF_DAMAGED条件关系与受伤时关键词/数值；不新增旧狂暴枚举。 | [m2-self-damaged-keyword](m2-self-damaged-keyword.md) |
| EVIL_GLOW | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| FINALE | 公共基础入口已有 | 原打印Keyword/出牌冻结面板、获取区间及公共主体。 | [Keyword.FINALE](../hs_sim/engine/model.py)；[Keyword.OUTCAST](../hs_sim/engine/model.py) |
| FORGE | 公共基础入口已有 | 原HandActionSpec的静态手牌动作，各行为和费用仍使用本族规则。 | [m3-hand-actions](m3-hand-actions.md) |
| FORGETFUL | 按载体区分政策 | 普通错误敌人基础已有；WW_419改为英雄加攻、WW_420随机获得能力，不能按同标签统一重定向。 | [m2-wrong-enemy-attacks](m2-wrong-enemy-attacks.md) |
| FREEZE | 公共基础入口已有 | Freeze与原冻结截止/攻击资格；FROZEN是状态而非需新增关键词。 | [Freeze](../hs_sim/engine/effects.py)；[Entity.frozen_until_owner_turn](../hs_sim/engine/model.py) |
| FRENZY | 公共基础入口已有 | 原LimitedTriggerSpec/一次用途、实际事件与载体资格。 | [m5-limited-triggers](m5-limited-triggers.md) |
| FROZEN | 公共基础入口已有 | Freeze与原冻结截止/攻击资格；FROZEN是状态而非需新增关键词。 | [Freeze](../hs_sim/engine/effects.py)；[Entity.frozen_until_owner_turn](../hs_sim/engine/model.py) |
| GHOSTLY | 原能力已有表达 | 原HandLifetime、持续附件到期和本人区间；标签只作来源线索，不统一猜测所有载体到期语义。 | [m5-echo](m5-echo.md) |
| HALL_OF_FAME | 其他模式关键词 | 当前引用为LETTUCE能力/佣兵相关来源，不新增佣兵规则。 | 固定原始引用，待对应模式／实际卡文审查 |
| HEROPOWER_DAMAGE | 公共基础入口已有 | 原HealthRule/DAMAGE/SOURCE ADD与HERO_POWER分类；本局永久消费者沿英雄无到期附件。 | [m2-hero-power-damage](m2-hero-power-damage.md) |
| HIDE_STATS | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| HONORABLE_KILL | 原能力已有表达 | 原事件/健康结果/触发谓词表达；须按实际主体条件，不凭标签自动附加收益。 | [m2-health-rules](m2-health-rules.md) |
| IMMUNE_WHILE_ATTACKING | 公共基础入口已有 | 原Keyword.IMMUNE_WHILE_ATTACKING与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.IMMUNE_WHILE_ATTACKING](../hs_sim/engine/model.py) |
| INSPIRE | 原能力已有表达 | 原事件/健康结果/触发谓词表达；须按实际主体条件，不凭标签自动附加收益。 | [m2-health-rules](m2-health-rules.md) |
| INTERACTABLE_OBJECT | 公共基础入口已有 | 原InteractableSpec与公开投牌/额外主动输入。 | [m4-interactables](m4-interactables.md) |
| KINDRED | 原能力已有表达 | 原最近关闭本人回合及冻结类型/学派匹配；完整身份消费者仍开放。 | [m3-kindred-basics](m3-kindred-basics.md) |
| LETTUCE_CHARGE | 其他模式关键词 | 当前引用为LETTUCE能力/佣兵相关来源，不新增佣兵规则。 | 固定原始引用，待对应模式／实际卡文审查 |
| LETTUCE_KEYWORD_SPELL_COMBO | 其他模式关键词 | 当前引用为LETTUCE能力/佣兵相关来源，不新增佣兵规则。 | 固定原始引用，待对应模式／实际卡文审查 |
| LIFESTEAL | 公共基础入口已有 | 原Keyword.LIFESTEAL与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.LIFESTEAL](../hs_sim/engine/model.py) |
| LOCK_VISUAL | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| MEGA_WINDFURY | 公共基础入口已有 | 原Keyword.MEGA_WINDFURY与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.MEGA_WINDFURY](../hs_sim/engine/model.py) |
| MODULAR | 公共基础入口已有 | 此标签的磁力基础对应原MAGNETIC/当前种族资格和普通宿主材料。 | [Keyword.MAGNETIC](../hs_sim/engine/model.py)；[CardDefinition.magnetic_tribes](../hs_sim/engine/model.py) |
| MORPH | 原能力已有表达 | 原Transform与区域/形态生命周期；标签不是统一变形策略。 | [Transform](../hs_sim/engine/effects.py) |
| NON_KEYWORD_ECHO | 明确独立政策已有 | 原HandRepeatSpec(echo=False)，本回合重复副本最低费用0；不等同回响，也不需另加模块。 | [m5-echo](m5-echo.md) |
| NON_KEYWORD_POISONOUS | 历史卡文与原基础 | 仅两VAN历史卡文；当前POISONOUS基础存在，不将历史文本重新造机制或加入当前正式池。 | [Keyword.POISONOUS](../hs_sim/engine/model.py) |
| OBJECTIVE | 公共基础入口已有 | 原玩家持续效果与本人区间倒计时，各真实主体沿原注册。 | [m4-player-effects](m4-player-effects.md) |
| OUTCAST | 公共基础入口已有 | 原打印Keyword/出牌冻结面板、获取区间及公共主体。 | [Keyword.FINALE](../hs_sim/engine/model.py)；[Keyword.OUTCAST](../hs_sim/engine/model.py) |
| OVERHEAL | 原能力已有表达 | 原事件/健康结果/触发谓词表达；须按实际主体条件，不凭标签自动附加收益。 | [m2-health-rules](m2-health-rules.md) |
| OVERKILL | 原能力已有表达 | 原事件/健康结果/触发谓词表达；须按实际主体条件，不凭标签自动附加收益。 | [m2-health-rules](m2-health-rules.md) |
| OVERLOAD | 公共基础入口已有 | 原过载账户与过载效果，支付和本人开始转锁共享。 | [Overload](../hs_sim/engine/effects.py)；[PlayerState.overload_owed](../hs_sim/engine/model.py) |
| POISONOUS | 公共基础入口已有 | 原Keyword.POISONOUS与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.POISONOUS](../hs_sim/engine/model.py) |
| PREPARE | 公共基础入口已有 | 原HandActionSpec的静态手牌动作，各行为和费用仍使用本族规则。 | [m3-hand-actions](m3-hand-actions.md) |
| QUEST | 公共基础入口已有 | 原QuestSpec不同kind与连续阶段，槽位/消费沿本族。 | [m4-quests](m4-quests.md) |
| QUESTLINE | 公共基础入口已有 | 原QuestSpec不同kind与连续阶段，槽位/消费沿本族。 | [m4-quests](m4-quests.md) |
| QUICKDRAW | 公共基础入口已有 | 原打印Keyword/出牌冻结面板、获取区间及公共主体。 | [Keyword.FINALE](../hs_sim/engine/model.py)；[Keyword.OUTCAST](../hs_sim/engine/model.py) |
| REBORN | 公共基础入口已有 | 原Keyword.REBORN与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.REBORN](../hs_sim/engine/model.py) |
| RECEIVES_DOUBLE_SPELLDAMAGE_BONUS | 公共基础入口已有 | Damage.spell_bonus_multiplier只乘法强加成，不乘基础伤害。 | [m2-spell-bonus-multiplier](m2-spell-bonus-multiplier.md) |
| REWIND | 公共基础入口已有 | 原RewindSpec/真实检查点与待选解释器。 | [CardDefinition.rewind](../hs_sim/engine/model.py)；[RewindSpec](../hs_sim/engine/model.py) |
| RUSH | 公共基础入口已有 | 原Keyword.RUSH与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.RUSH](../hs_sim/engine/model.py) |
| SECRET | 公共基础入口已有 | 原SecretSpec与隐藏反应/实际揭示。 | [m4-secrets](m4-secrets.md) |
| SECRET_DEATHRATTLE | 其他模式／内部策略 | 当前冒险/乱斗/AI等载体的特殊策略，不把它们自动外推为构筑机制。 | 固定原始引用，待对应模式／实际卡文审查 |
| SIDE_QUEST | 公共基础入口已有 | 原QuestSpec不同kind与连续阶段，槽位/消费沿本族。 | [m4-quests](m4-quests.md) |
| SIGIL | 公共基础入口已有 | 原玩家持续效果与本人区间倒计时，各真实主体沿原注册。 | [m4-player-effects](m4-player-effects.md) |
| SILENCE | 公共基础入口已有 | 原Silence与实例附件清理。 | [Silence](../hs_sim/engine/effects.py) |
| SKIP_MULLIGAN | 其他模式／内部策略 | 当前冒险/乱斗/AI等载体的特殊策略，不把它们自动外推为构筑机制。 | 固定原始引用，待对应模式／实际卡文审查 |
| SPELLBURST | 公共基础入口已有 | 原LimitedTriggerSpec/一次用途、实际事件与载体资格。 | [m5-limited-triggers](m5-limited-triggers.md) |
| SPELLPOWER | 公共基础入口已有 | 打印数值法强与原按来源控制者的法术伤害报价。 | [CardDefinition.spell_damage](../hs_sim/engine/model.py)；[spell_bonus](../hs_sim/engine/health_rules.py) |
| SPELLPOWER_ARCANE | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_FEL | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_FIRE | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_FROST | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_HOLY | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_NATURE | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| SPELLPOWER_SHADOW | 公共基础入口已有 | 原spell_damage_schools选择器与同一法强管线；七派系不建七份模块。 | [m2-school-spell-damage](m2-school-spell-damage.md) |
| STARSHIP_LAUNCH_TRIGGER | 公共基础入口已有 | 原星舰on_launch和普通发射路径。 | [m4-starships](m4-starships.md) |
| START_OF_COMBAT | 其他模式关键词 | 当前引用为战棋或相应TB来源，传统构筑主线不新增战棋关键词执行。 | 固定原始引用，待对应模式／实际卡文审查 |
| START_OF_GAME_KEYWORD | 原能力已有表达 | 原OpeningHook和起始套牌纯条件/实体区域入口；不是全部开局主体已适配。 | [m3-zones](m3-zones.md) |
| STEALTH | 公共基础入口已有 | 原Keyword.STEALTH与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.STEALTH](../hs_sim/engine/model.py) |
| SUMMONED | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| SUMMONED_WHEN_DRAWN | 原能力已有表达 | 原抽取事实、手牌进度、物理召唤与补抽；不把标签等同所有来源完整适配。 | [m3-draw-summon-basics](m3-draw-summon-basics.md) |
| TAG_ONE_TURN_EFFECT | 原能力已有表达 | 原HandLifetime、持续附件到期和本人区间；标签只作来源线索，不统一猜测所有载体到期语义。 | [m5-echo](m5-echo.md) |
| TAUNT | 公共基础入口已有 | 原Keyword.TAUNT与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.TAUNT](../hs_sim/engine/model.py) |
| TRADEABLE | 公共基础入口已有 | 原HandActionSpec的静态手牌动作，各行为和费用仍使用本族规则。 | [m3-hand-actions](m3-hand-actions.md) |
| TRIGGER_VISUAL | 呈现／内部提示 | 载体呈现/条件提示/来源标记不是新的公共规则指令，实际卡文仍按现有区域、触发和行为前审。 | 固定原始引用，待对应模式／实际卡文审查 |
| VENOMOUS | 其他模式关键词 | 当前引用为战棋或相应TB来源，传统构筑主线不新增战棋关键词执行。 | 固定原始引用，待对应模式／实际卡文审查 |
| WINDFURY | 公共基础入口已有 | 原Keyword.WINDFURY与攻击/伤害/死亡资格及原附件生命周期。 | [Keyword.WINDFURY](../hs_sim/engine/model.py) |

该表未运行对局或测试，没有新增机制、代表卡、账户、协议或组合；查阅路由不是官方认证。M0 正式池、M6 国服校准、M7 批量接卡与完整基础目标继续开放。
