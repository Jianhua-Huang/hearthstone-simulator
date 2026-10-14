# 其他命名标签与独立基础对照

此页是静态来源查阅表，实际执行、验收与下一项仅在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。

从上一份 [命名 power 对照](m0-named-power-foundation-map.md) 之外的369个命名符号中核对52项，包括原定12个优先项。52是标签路由数，不是完成的机制数；其余317项及数值标签、全部卡文、服务端规则和正式可达池仍开放。

[完整机器表](../data/support/nonpower-named-foundation-map.json)保留每项全引用、载体类型和原行哈希，并绑定54个当前声明／读取节点、17个源码文件。仅核对表达入口，未新增卡牌适配、运行机制或行为测试；历史契约页中的版本与测试数量保留当时含义。

| 标签 | 引用数 | 当前基础或判断 | 范围限制 |
| --- | ---: | --- | --- |
| `ADAPT` | 23 | 现有能力可表达：原十结果配方及RequestChoice三选一、普通附魔；不新增进化执行器。 [`adapt`](../hs_sim/engine/adapt.py), [`register_adapt_options`](../hs_sim/engine/adapt.py)；[原契约](m3-adapt.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `CANNOT_ATTACK_HEROES` | 41 | 现有公共基础：原AttackPolicySpec不同限制模式；条件按来源明确声明，不统一推测。 [`AttackPolicySpec`](../hs_sim/engine/model.py), [`CardDefinition.attack_policies`](../hs_sim/engine/model.py) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `CANT_ATTACK` | 15 | 现有公共基础：原AttackPolicySpec不同限制模式；条件按来源明确声明，不统一推测。 [`AttackPolicySpec`](../hs_sim/engine/model.py), [`CardDefinition.attack_policies`](../hs_sim/engine/model.py) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `CANT_BE_DESTROYED` | 4 | 其他模式载体政策：已逐行核对当前有限来源为BG/Story/冒险/棋子；不自动推出传统构筑新公共限制。 | 全部原行保留。不可收藏不是模式证明；后续真实构筑需求重新核对。 |
| `CANT_BE_FATIGUED` | 2 | 其他模式载体政策：已逐行核对当前有限来源为BG/Story/冒险/棋子；不自动推出传统构筑新公共限制。 | 全部原行保留。不可收藏不是模式证明；后续真实构筑需求重新核对。 |
| `CANT_BE_FROZEN` | 4 | 现有公共基础：已补持续冻结防护，阻止新增冻结并清除旧截止。 [`Keyword.CANT_BE_FROZEN`](../hs_sim/engine/model.py)；[原契约](m2-freeze-prevention.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `CANT_DISCARD` | 1 | 其他模式载体政策：已逐行核对当前有限来源为BG/Story/冒险/棋子；不自动推出传统构筑新公共限制。 | 全部原行保留。不可收藏不是模式证明；后续真实构筑需求重新核对。 |
| `CAN_TARGET_CARDS_IN_HAND` | 40 | 现有公共基础：原TargetSpec区域/类型与玩家目标输入；自方手牌可见，对手隐藏信息隔离。 [`TargetSpec`](../hs_sim/engine/model.py), [`accepts_target`](../hs_sim/engine/targeting.py), [`factory`](../hs_sim/engine/player_target_inputs.py)；[原契约](m5-player-target-inputs.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `CARD_ALTERNATE_COST` | 3 | 现有公共基础与印刷声明：原Health/Corpses账户、CostSpec.payment和不可变CardDefinition.cost_payment共用物理/生成/冻结报价，创建与重置依据原卡面。见[印刷账户契约](m2-native-cost-payment.md)。 | 保留两可收藏来源和不可收藏JAIL_446hp完整原行；后者未适配，模式未确认。不得靠扣资源回调替代正常支付，也不宣称三个来源/正式池/CN已完成。 |
| `CARES_ABOUT_IMBUE_CARDS` | 21 | 族提示：关注灌注的来源提示；具体条件和奖励按实际卡文，不再造灌注计数器。 [`imbue_count`](../hs_sim/engine/imbue.py)；[原契约](m5-imbue.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `COLOSSAL` | 30 | 现有公共基础：原有序AppendageSpec与公共入场展开；标签数值不是附肢数量。 [`CardDefinition.colossal`](../hs_sim/engine/model.py), [`AppendageSpec`](../hs_sim/engine/model.py)；[原契约](m5-colossal.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `COLOSSAL_LIMB` | 61 | 现有结构声明：附肢仍是独立普通随从；原AppendageSpec明确卡ID和左右落点。 [`AppendageSpec`](../hs_sim/engine/model.py)；[原契约](m5-colossal.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `COLOSSAL_LIMB_ON_LEFT` | 5 | 现有结构声明：附肢仍是独立普通随从；原AppendageSpec明确卡ID和左右落点。 [`AppendageSpec`](../hs_sim/engine/model.py)；[原契约](m5-colossal.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `DARK_GIFT` | 29 | 真实族尚未完整实现：普通ChoiceOption/预览/获取/附件部分已有；成对不同赐福交付和特殊满血保附魔复生尚未完整支持。 [`ChoiceItem`](../hs_sim/engine/model.py), [`CardPreview`](../hs_sim/engine/model.py), [`ChoiceOption`](../hs_sim/engine/effects.py), [`GrantStoredKeyword`](../hs_sim/engine/hand_keywords.py), [`reborn_minion`](../hs_sim/engine/resolver.py) | 历史国服说明有10种；当前本地EDR_100另有两种结果，完整生效池须另核，不能删去或自动纳入。 |
| `DORMANT` | 209 | 现有公共基础：原独立休眠实例、定时/无限期休眠、显式唤醒与休眠触发。 [`CardDefinition.dormant_turns`](../hs_sim/engine/model.py), [`CardDefinition.dormant_triggers`](../hs_sim/engine/model.py), [`MakeDormant`](../hs_sim/engine/dormancy.py), [`AwakenMinion`](../hs_sim/engine/dormancy.py)；[原契约](m4-dormancy.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `DORMANT_AWAKEN_CONDITION_ENCHANT` | 41 | 逐载体政策待核：回合或具体条件唤醒线索；原休眠触发可表达条件，但各死亡/复活/变形主体需逐卡核对。 [`CardDefinition.dormant_triggers`](../hs_sim/engine/model.py), [`AwakenMinion`](../hs_sim/engine/dormancy.py)；[原契约](m4-dormancy.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `EXTRA_TURNS_SPELL_OVERRIDE` | 1 | 现有能力可表达：原QueueTurns表达额外回合；TOY_385的条件/每局一次主体仍按真实来源。 [`QueueTurns`](../hs_sim/engine/turn_scheduling.py)；[原契约](m3-turn-scheduling.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `FABLED` | 11 | 现有结构声明：原有限主卡/伴生包、完整原始物理卡组及既有容量政策；实际战斗主体仍逐卡。 [`FabledSpec`](../hs_sim/engine/fabled_decks.py), [`expand_fabled_cards`](../hs_sim/engine/fabled_decks.py)；[原契约](m3-fabled-basics.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `FABLED_PLUS` | 1 | 现有结构声明：原有限主卡/伴生包、完整原始物理卡组及既有容量政策；实际战斗主体仍逐卡。 [`FabledSpec`](../hs_sim/engine/fabled_decks.py), [`expand_fabled_cards`](../hs_sim/engine/fabled_decks.py)；[原契约](m3-fabled-basics.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `GIGANTIC` | 5 | 衍生卡面标记：已有微型/大型衍生卡面标记；不再创建独立缩放执行器。 [`Keyword.MINI`](../hs_sim/engine/model.py), [`Keyword.GIGANTIC`](../hs_sim/engine/model.py)；[原契约](m5-hand-derivatives.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `GIGANTIFY` | 5 | 现有公共基础：原HandDerivativeSpec与各自真实生成时机/卡面。 [`Keyword.GIGANTIFY`](../hs_sim/engine/model.py), [`HandDerivativeSpec`](../hs_sim/engine/model.py), [`create`](../hs_sim/engine/hand_derivatives.py)；[原契约](m5-hand-derivatives.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `HAS_DARK_GIFT` | 10 | 其他模式标记：当前十行均为BG36衍生卡；不是完整构筑赐福身份协议。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `HEALING_DOES_DAMAGE` | 1 | 其他模式数据提示：当前仅BG30_101且文本为战斗开始圣盾；不能从该提示推断普通构筑治疗转伤的新规则。 [`HealthRule`](../hs_sim/engine/model.py)；[原契约](m2-health-rules.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `HEROPOWER_UNLIMITED_USES` | 1 | 其他模式载体政策：已逐行核对当前有限来源为BG/Story/冒险/棋子；不自动推出传统构筑新公共限制。 | 全部原行保留。不可收藏不是模式证明；后续真实构筑需求重新核对。 |
| `IMBUE` | 26 | 现有公共基础：原版本化十一职业映射、玩家成长历史与英雄技能替换/成长入口。 [`Imbue`](../hs_sim/engine/imbue.py), [`ImbueProfile`](../hs_sim/engine/imbue.py), [`imbue_count`](../hs_sim/engine/imbue.py)；[原契约](m5-imbue.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `IMMUNE` | 222 | 现有公共基础：原免疫属性与伤害/敌方主动目标保护。 [`Keyword.IMMUNE`](../hs_sim/engine/model.py), [`is_immune`](../hs_sim/engine/combat.py)；[原契约](m2-health-rules.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `INFUSE` | 56 | 现有公共基础：原手牌进度、友方实际死亡见证和原实体升级；同批死亡逐条计数。 [`HandProgressSpec`](../hs_sim/engine/model.py), [`CardDefinition.hand_progress`](../hs_sim/engine/model.py)；[原契约](m5-hand-progress.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `IS_NIGHTMARE_BONUS` | 116 | 真实族尚未完整实现：普通ChoiceOption/预览/获取/附件部分已有；成对不同赐福交付和特殊满血保附魔复生尚未完整支持。 [`ChoiceItem`](../hs_sim/engine/model.py), [`CardPreview`](../hs_sim/engine/model.py), [`ChoiceOption`](../hs_sim/engine/effects.py), [`GrantStoredKeyword`](../hs_sim/engine/hand_keywords.py), [`reborn_minion`](../hs_sim/engine/resolver.py) | 历史国服说明有10种；当前本地EDR_100另有两种结果，完整生效池须另核，不能删去或自动纳入。 |
| `KEEP_HERO_CLASS` | 5 | 现有公共基础：原英雄牌keep_hero_class显式政策，不能用外观猜职业。 [`CardDefinition.keep_hero_class`](../hs_sim/engine/model.py)；[原契约](m5-imbue.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `LOCATION_ACTION_COST` | 1 | 数据提示／政策已有：当前唯一来源FIR_907值为0，与原免费地标激活一致；不从标签名发明付费地标。 [`location_error`](../hs_sim/engine/locations.py)；[原契约](m4-locations.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `MANATHIRST` | 22 | 现有公共基础：原印刷阈值与出牌提交时冻结的法力水晶条件，不新增支付账户。 [`CardDefinition.manathirst`](../hs_sim/engine/model.py), [`PlayRecord.manathirst_threshold`](../hs_sim/engine/model.py), [`PlayRecord.mana_crystals`](../hs_sim/engine/model.py)；[原契约](m5-play-conditions.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `MINI` | 20 | 衍生卡面标记：已有微型/大型衍生卡面标记；不再创建独立缩放执行器。 [`Keyword.MINI`](../hs_sim/engine/model.py), [`Keyword.GIGANTIC`](../hs_sim/engine/model.py)；[原契约](m5-hand-derivatives.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `MINIATURIZE` | 19 | 现有公共基础：原HandDerivativeSpec与各自真实生成时机/卡面。 [`Keyword.MINIATURIZE`](../hs_sim/engine/model.py), [`HandDerivativeSpec`](../hs_sim/engine/model.py), [`create`](../hs_sim/engine/hand_derivatives.py)；[原契约](m5-hand-derivatives.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `REPEATABLE` | 1 | 现有能力可表达：真实可重复任务的普通进度/奖励/ResetQuestProgress可以复用；原生TLC_426未接入。 [`QuestSpec`](../hs_sim/engine/model.py), [`ResetQuestProgress`](../hs_sim/engine/quests.py)；[原契约](m4-quests.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `RITUALIST_MINION` | 28 | 族提示：原克苏恩族成长/玩家事实与条件；提示标签不自动执行所有主体。 [`GrowCthun`](../hs_sim/engine/cthun.py), [`cthun_attack_at_least`](../hs_sim/engine/cthun.py)；[原契约](m3-cthun.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_ARCANE` | 5 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_FEL` | 5 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_FIRE` | 13 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_FROST` | 11 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_HOLY` | 2 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_NATURE` | 5 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_RESISTANCE_SHADOW` | 8 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_ARCANE` | 17 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_FEL` | 6 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_FIRE` | 19 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_FROST` | 19 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_HOLY` | 1 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_NATURE` | 7 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `SPELL_WEAKNESS_SHADOW` | 15 | 佣兵族来源政策：当前全引用为LETL/LT23/LT24/LT25等佣兵族来源，学派抗性/虚弱不自动外推到构筑伤害系统。 | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `TITAN` | 47 | 现有公共基础：原三个独立ActivatedAbilitySpec、用途与行动次数；普通攻击资格共用。 [`Keyword.TITAN`](../hs_sim/engine/model.py), [`CardDefinition.activated_abilities`](../hs_sim/engine/model.py), [`ability_error`](../hs_sim/engine/minion_abilities.py)；[原契约](m4-minion-abilities.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `TWINSPELL` | 45 | 现有公共基础：原HandDerivativeSpec与各自真实生成时机/卡面。 [`Keyword.TWINSPELL`](../hs_sim/engine/model.py), [`HandDerivativeSpec`](../hs_sim/engine/model.py), [`create`](../hs_sim/engine/hand_derivatives.py)；[原契约](m5-hand-derivatives.md) | 静态入口核对；未证明全部真实主体、完整正式池或精确国服时序。 |
| `UNTOUCHABLE` | 120 | 显式永久载体复用原无限期休眠及永久声明/唤醒守卫，见[永久载体契约](m4-permanent-board-carriers.md)；条件休眠及其他不可交互来源分别声明，不从标签统一映射。 [`CardDefinition.permanent_dormancy`](../hs_sim/engine/model.py), [`CardDefinition.dormant_turns`](../hs_sim/engine/model.py), [`CardDefinition.interactable`](../hs_sim/engine/model.py) | 只表达明确声明的公共基础，混合120原行保留；其他主体、特殊移除、正式池及精确国服规则未确认。 |

## 黑暗之赐的真实差异

国服2025年公布的构筑规则将发现结果与不同赐福逐一配对，列出十种结果，并明确一个复生结果会保留附魔与完整生命。该规则是历史依据，不能替代当前生效池或精确窗口校准。[国服官方说明](https://hs.blizzard.cn/news/24179067/)

普通 [`reborn_minion`](../hs_sim/engine/resolver.py) 从印刷定义创建新实体，消费复生并把生命设为1；它没有复制死亡记录中的附魔。因此仅授予普通复生，无法兑现本地 `EDR_100t9`／`EDR_100t9e` 的真实文本。原冻结死亡材料、附件复制和解释器可作为复用基础，不能用额外亡语召唤冒充正常复生。

[完整来源前审](../outputs/nonpower-named-foundation-audit-20261012/dark-gift-source-audit.json)保留27条 `EDR_100` 原行和所有 `DARK_GIFT` 来源。当前本地有12种描述卡面，其中两种不在该历史十项清单中；这些原行不能被静默删除，也不能仅凭存在直接加入正式赐福池。酒馆的同名系统与 `HAS_DARK_GIFT` 标记不作为构筑规则依据。

印刷固有替代支付、永久不可交互物体、各休眠条件主体继续保留逐源核查状态；已有支付账户或休眠实例不能证明这些原生政策完整。M0正式池、M6国服校准和M7批量接卡保持未完成。
