# 机制扩展指南

固定具名填场使用FillBoardWithCard，完整初始容量与配方进入原召唤组；弃牌、数量和恢复仍沿原执行器，见[契约](m3-named-fill-story.md)。

真实时光流汇需要从原场上发现结果取得手牌复制，可用有限copy_selected_to_hand声明；原选择、接受前缀与普通创建的边界见[契约](m3-conflux-locations.md)。

阿沙隆使用`remember_adaptations(context, spec_id)`捕获两轮原驻留选择，注册的`adaptations`玩家效果只接受完整两项程序；实际后续出牌、磁力和孢子交公共入口，见[契约](m3-ashalon-adaptations.md)。不要在`card_played`完成回调给本次战吼刚安装的程序重新找受益者。

首张当前种族的费用应沿[原提交附件筛选](m2-first-tribe-turn-cost-aura.md)表达，不读取后来场上实体，也不安装新的逐卡计数。间接起源仍须按真实来源接受政策处理。

奖励只能兑现一次时，使用完整原实例的`ConsumePlayerEffect`，不要排列“移除＋独立奖励”来模拟条件成功；接受窗、来源和恢复边界见[契约](m3-once-player-effect-reward.md)。

需要0/0初始召唤时直接使用非负 `SummonStats`，不要先创建正生命再设值，也不要强制消灭可能被光环保住的实体；原具名交付可继续原驻留攻击，见[契约](m3-zero-health-summon-entry.md)。

需要实际可用性筛选时复用[可用法术契约](m3-playable-spell-generation.md)中的共享手动资格和纯材料副本，不以试打动作或剩余法力代替；真实交付和生命周期继续交给普通执行器。

原存储卡牌的完整随机池选面复用普通跨类型重置；原引用、完整候选和私有抽样/变形收据见[契约](m3-stored-pool-transforms.md)。

原随机法术结果的费用治疗使用来源绑定的有限请求、普通生成交付和共享健康批次；等待、回溯及私有收据边界见[契约](m3-generated-spell-healing.md)。
RandomSplitDamage可显式声明spell_bonus_multiplier=0，仅忽略外层法强预算；法术归因与单位管线保持，见[契约](m3-immune-spell-split.md)。
有限触发授予可通过GrantLimitedTrigger.recipient保存原随从引用；成功后仍沿普通附件生命周期，原施法玩家的结束条件可独立于当前控制者，见[契约](m3-original-finite-grants.md)。
原驻留强制攻击可直接使用既有BoardPresenceReference；窗口与合法改向共同保护原防守方，见[契约](m3-original-attack-defender.md)。
真实已使用任务条件复用原提交记录和本人quests_played_total输入；原目标、间接执行和恢复边界见[契约](m3-played-quest-targets.md)。
原生圣骑士光环可用明确的aura种类、对手时钟和独立费用贡献；来源、恢复与待国服边界见[契约](m3-native-paladin-aura.md)。
真实法术需按执行时容量支付残骸召唤，可用原SpendResource的有限requires_board_space声明；原来源、形状与待国服边界见[契约](m3-corpse-spell-capacity.md)。
真实召唤后的流放奖励按原完整召唤收据交给既有关键词和本回合清理；有限原组续接见[契约](m3-outcast-original-summon.md)。
真实英雄“免疫到下个本人开始”复用原期限和英雄附件继承，有限载体许可见[契约](m3-hero-timed-immunity.md)。
真实普通随机法术洗入复用原抽选与语义洗牌组，有限请求及流放重复见[契约](m3-plain-spell-shuffle.md)。
真实流放发现复用印刷关键词，下一张减费复用原费用贡献及一次消费；有限条件与恢复边界见[契约](m3-printed-outcast-study.md)。
真实随机随从的计时休眠作为原入场材料在首次通知前安装，倒数与恢复沿原生命周期；见[契约](m3-pool-entry-dormancy.md)。
真实发现后的赠礼复制绑定同一所选创建材料，独立交付和生命周期沿原执行器；有限入口及待国服窗口见[契约](m3-selected-gift-copy.md)。
真实延系赠礼的减费随一次原发现交付，复用原准备角色、费用和回溯；见[迅猛龙先锋契约](m3-kindred-dark-gift.md)。
原生黑暗之赐生成来源通过有限请求绑定实际宿主上下文，再委托已有完整配对发现；见[契约](m3-native-dark-gift-generation.md)。
真实随机生成的固定属性与翻倍使用独立创建声明，在原获取通知前绑定实际新实体；五张洗入复用原语义洗牌组，见[创建属性契约](m3-generated-minion-stats.md)。

随机池适配器转交原死亡位置，批次保留起点及前根实际交付偏移；原位和父子收据边界见[池召唤位置契约](m3-pool-summon-positions.md)。

随机沉默后消灭保留原战场驻留，能跨沉默撤销控制而不追踪重入实体；有限请求及恢复边界见[随机沉默消灭契约](m3-random-silence-destruction.md)。

随机池召唤的有限嘲讽声明沿原完整basis转交已有入场材料；候选、权重与材料一致性见[池入场关键词契约](m3-pool-entry-keywords.md)。

普通池发现/随机获取的临时随从交付复用原CreateTemporaryCard，独立于费用到期；原期限、批次与等待恢复见[临时池随从契约](m3-temporary-pool-minions.md)。

普通发现的固定属性增益转交已有实际创建层，包装器不支持时明确拒绝；有限形状与创建/烧牌窗口见[发现随从增益契约](m3-discovered-minion-grant.md)。

已审印刷元数据在构筑组装时显式投影，生成目录从完整可执行定义登记，历史代表包保持原默认值；见[构筑元数据契约](m3-constructed-metadata-catalog.md)。

固定1188候选的独立PoolQuery字段不依赖可执行覆盖，未知效果仍在完整资格查询后明确失败；有限地标兆示标记及原生连击入口修正见[候选目录契约](m3-candidate-generation-catalog.md)，不据此声明正式标准池完成。

真实发现后的按费用治疗使用原选择收据和有限声明，不扫描后来手牌或私自重建发现；来源、交付反应和恢复边界见[发现费用治疗契约](m3-discovery-cost-healing.md)。

通用构筑生成使用宿主GenerationContext绑定的constructed.cards完整资格池；原生已重组状态在首个入手通知前消费印刷裂变，见[生成与创建契约](m3-combined-shatter-generation.md)。

原致死随从变形从DeathCause取得原身份，再在实际执行时核对完整驻留，交由公共变形生命周期执行；见[原凶手变形契约](m3-native-killer-transform.md)。

本回合死亡随从的亡语继承读取原完整物理声明，保留原生记忆和声明证明，分配新的可移除身份；不能只复制behavior ID，见[亡语继承契约](m3-deathrattle-inheritance.md)。

混合普通效果与延系奖励应按原prepare/active接续，原属性与实际消灭奖励可直接复用已接受材料和原引用执行器，见[魔暴龙契约](m3-native-kindred-destruction.md)。

纯延系随从的原生条件目标通过KindredTargetProfile连接既有主体与原目标流程，公开端只给本人手牌必要布尔值；约束见[契约](m3-native-kindred-target.md)。

真实完整有限名单可通过GenerateFromCandidates复用原抽样与入手，无通用格式上下文时也不裁池；具体约束见[完整梦境来源](m3-fixed-dream-source.md)。

真实数值与一次性开始回调须共同安装，原有限触发器负责条件、消费和来源；梦魇及伊瑟拉苏醒的限定表达见[契约](m3-complex-dream-cards.md)。

梦境CLASS11使用独立CardClass.DREAM；可用英雄职业须按PLAYABLE_CARD_CLASSES查询，不能把所有非中立类别当作可玩职业。来源、类别筛选与格式边界见[契约](m3-dream-class.md)。

真实施法完成消费者从原cast_id的target_origin读取已接受目标，原分配材料与开始事实共同保持；不在目标换面后查询当前类型。完整范围、回溯及信息边界见[契约](m3-native-cast-target.md)。

真实原攻击致死可在原不可变上下文冻结BOARD随从的基础复制材料，后续沿普通CopyCard执行；仅MINION/base，不开放场上当前冻结复制。来源/归因/格式与国服政策边界见[契约](m3-native-combat-copy.md)。

真实免疫法强SPELL使用既有Damage系数0，原召唤组可声明限定双方随从关系；继续使用原健康和强制战斗执行器。类型、原引用、默认关系及旧格式边界见[契约](m3-native-shreds-treants.md)。

真实延迟返还弃牌使用原生discard_link，在实际成功通知前绑定原记录；基础重新获取使用CopyCard(DiscardRecord,mode="base")，不扫描source_id历史，也不扩展旧物理返还范围。见[原生弃牌记忆](m3-native-discard-memory.md)。

真实“本回合使用过某学派”目标只读本人DTO的有序学派集合，原事实由既有提交账本投影，不能在玩家条件闭包读取全状态或从墓地推断。普通根与独立主体窗口、私密范围及原观察校验见[契约](m3-played-school-targets.md)。

原随从攻击规则授予可用GrantAttackPolicy.recipient保护原接收对象，来源归属和source_binding仍各自保留；见[契约](m3-captured-attack-grants.md)。

非施法随从/地标的具名分摊可显式使用NON_SPELL_PROFILE，cast_id=None及匹配kind，复用原完整单位管线和原致死结果；见[契约](m3-non-spell-split.md)。

真实具名生成法术可使用AddToHand.spell_damage正数材料，要求实际SPELL及来源，复用物理局部法伤安装；仅该入口，默认0保持。见[契约](m3-created-spell-bonuses.md)。

真实龙牌的当前种族/赐福条件、分阶段移除和回溯伤害继续复用原管线；只为实际地标需求增加有限随机入口。候选、原死亡、恢复及待国服窗口见[契约](m3-dragon-native-effects.md)，生成资格仍独立核对。

从本人牌库发现并授予黑暗之赐须保留原实体和当前材料，不能套用生成副本。有限原牌发现、共享配对、原授予/区域交付及恢复边界见[契约](m3-stored-dark-gift-discovery.md)；这不认证外部随从生成池。

真实具名亡语循环召唤新的基础实体，伤害后的固定入手复用普通批次和交付；已有静电震击定义保持，未知虚空灵魂来源继续显式未支持。完整依赖、保存与目录/生效补丁边界见[契约](m3-fixed-named-followups.md)。

真实原生伤害与攻击提供者仅扩展有限来源、嘲讽绕过和本体免疫条件，数值/目标/生命周期仍交原执行器。当前种族、占位和未实现克洛玛图斯来源边界见[契约](m3-native-health-attack-providers.md)，不能从登记数量认证正式标准支持。

真实条件消费者继续使用既有属性、攻击、施法和物理库存事实；跨冻结反应的原邻位组仅增加有限法术续接，冻结/死亡仍由公共执行器负责。保存、末次武器奖励及初始资格的边界见[契约](m3-conditional-consumers.md)，当前执行版本以原两份台账为准。

真实卡牌应组合已有公共效果，敌方随从持续嘲讽仅增加有限声明范围；生命设值、连击复制、武器死亡、随机额外效果与牌库逆序继续共用原执行器。新增范围及待国服边界见[配方契约](m3-public-effect-consumers.md)，下文历史初始范围不覆盖此后新增形状。

原延系检索按第一次实际抽牌的完整类型连接第二次物理检索；原生手牌额外效果只替换两个印刷关键词槽，独立授予继续保留。有限表达及未实现来源边界见[契约](m3-kindred-hand-bonus.md)。

真实抽牌条件只读原两次物理抽牌，来源奖励绑定原连续驻留；按实际消灭奖励保存原目标与死亡原因，继续委托普通死亡、抽牌和法力执行器。有限请求及待国服边界见[五费随从契约](m3-five-cost-native.md)。

真实原生法术参数绑定原亡语执行与物理材料，当前费用/亡语抽取连接原手牌奖励；首回合和后续正常抽牌共用可移除来源门禁。有限字段、公共执行及未覆盖继承边界见[亡灵资源契约](m3-undead-resource-native.md)。

真实英雄本回合生命变化目标读取原提交账本，随机随从增益仅抽选后交给原属性层；受伤召唤、不能攻击和实际过量治疗继续组合公共执行器，表达与待校准边界见[亡灵原生效果契约](m3-undead-native.md)。

上一张使用的印刷符文用原冻结历史查询；固定召唤组从完整原交付连接原目标强制攻击，保存、容量与时序边界见[符文与召唤组战斗契约](m3-blood-rune-native.md)。

真实英雄救援复用原英雄致死屏障、实际残骸支出与原身份恢复，公开一次性标记按原接受时钟退役；具体表达、替换及校准边界见[哈斯克契约](m3-hero-corpse-rescue.md)。

原生残骸获得倍率保留可移除来源和固有死亡基数；物理消费者检索、原目标支付及真实任务/地标/第二技能依赖见[残骸消费者契约](m3-corpse-consumer-native.md)。已有第二技能槽安装仍明确未支持，不能以首次安装认证整卡。

原随从残骸门禁在执行时重核实际来源、空位/复生/召唤对象，再沿原完整支付分支；原目标伤害与三个真实选项保持引用和信息边界，见[残骸触发与选择契约](m3-corpse-trigger-choices.md)。

真实固定召唤后的残骸奖励连接原完整交付和原支出，残骸raise按原实际容量/扣除单位生成固定新体；与原法力奖励共用交付连接器。入口、无残骸衍生物及待国服窗口见[残骸召唤契约](m3-corpse-summon-effects.md)。

真实回手禁止须绑定成功到达的原物理对象；控制归还和“下个本人回合结束”按实际原玩家区间计时，普通/对方/结束反应安装分别接受。有限入口和仍未支持的控制层叠边界见[时间效果契约](m3-temporal-spell-effects.md)。

真实首次复制的目标要求通过有限原生声明共用选择管线；召唤后的全法力奖励绑定原请求、实际交付和原支出，见[数值资源法术契约](m3-numeric-resource-spells.md)。

下一次延系必须只重复真实成立部分，原准备/替代分支、原付款及原接收对象分别表达；原生入口、紧凑计划与恢复边界见[延系部分契约](m3-kindred-components.md)。

真实固定家族随机置顶并增益用PutMatchingDeckMinionOnTop，不能两次随机分别挑受益牌。按原成功召唤奖励时，用BuffSummonedMinion绑定实际记录，避免按当前名字或复用实体ID重绑；限定用法与国服边界见[契约](m3-original-imp-recipients.md)。

真实固定洗入先核官网child身份，用recruit_cards.shuffle复用一次语义批次；抽到时召唤用原成功物理抽牌条件和drawer/opponent回调，不从牌名猜衍生物、不制造副本。与下一回合税费的复用见[契约](m3-fixed-shuffle-followups.md)。

真实下一次种族减费附圣盾，用AddCostModifier的有限minion_keyword声明共享原付款接受，不分开监听两个“下一张”。下一实际回合加费沿既有玩家实例/真实开始/当回合到期，见[费用卡契约](m3-paid-minion-price-keywords.md)。

真实“尽量以自身为目标”使用PreferredMinionTarget保存原BoardPresenceReference，并交给原CastSpell/CastStoredSpell或历史重施；不要在卡牌层提前指定目标后取消合法回退。牌库筛选用CastRandomDeckSpell的存储费用，不用手牌报价，见[契约](m3-original-minion-spell-targets.md)。

延系正文没有战吼时，用随从on_play读取原query_previous_owner_turn，不把延系声明为战吼。真实固定生成依赖按官网child与完整源身份核对，原生出牌、结束、亡语继续委托已有执行器；用法见[延系与鱼人依赖契约](m3-kindred-murloc-effects.md)。

真实亡语状态用有限NativeDeathrattleSpec/DeathrattleMemory声明，抽牌关联用DrawForDeathrattle在原通知前保存，按原hand_entry驻留而非卡名绑定；卡牌代码不直接改全局历史。三个有限请求、私有引用和未接通授予边界见[契约](m3-native-deathrattle-memory.md)。

真实满面板唤醒用dormant_turns=None和dormant_board_full=True，沿已有物理休眠实例/唤醒解释器；不要写死七随从、只订阅召唤事件或在查询中修改状态。声明、队列去重与旧存档边界见[契约](m3-full-board-dormancy.md)。

按原使用随从奖励时，别把效果召唤当出牌，也别按后来卡面重算原亡语资格。用原实际入场绑定连续驻留，InvokeBehavior带原play_id在真正窗口委托原关键词模块；归因与未核实磁力接收者见[契约](m3-played-minion-keywords.md)。

补基础角色先核对完整源HERO_POWER和职业，再通过有限initial_hero_power_bindings装配；defer_validation只用于完成外层真实依赖后统一校验。默认技能组合原效果，完整图腾池及食尸鬼用法见[契约](m3-basic-hero-roles.md)，不要用其他头像的Scenario代替默认构筑验证。

原生受伤法强或小手牌技能设0用CardDefinition.native_condition=NativeSourceCondition(...)限定原提供者，不写回永久修正；本人回合英雄攻击用AuraSpec的friendly_hero/controller_turn配对。不要重算已接受付款或动态授予这些资格，完整有限形状见[契约](m3-native-conditional-sources.md)。

真实“用完最后法力”按原正数扣款事实判断，不按报价或零费推导；当前回合技能条件的目标谓词只读玩家DTO。伪装文本的原落位接收者与使用者分开，固有过载不造战吼；具体配方及负属性边界见[契约](m3-one-cost-basic-cards.md)。

真实连续手牌镜像使用CardDefinition.hand_mirror=HandMirrorSpec(3,4)，不要用回合开始来源、查询时换面或固定3费仿真。原提交、获取同步、复制/转手及3/4由公共层处理，材料继承和退役仍须CN校准；见[契约](m3-native-hand-mirrors.md)。

真实随机困住一段实际目标回合时，用TrapRandomHandCards(player_id, count, source_id)，数量是原接受时计划值、候选晚取，同批无放回，可能与前一批重叠；不要自行降法力值、公开隐藏候选或用全局回合数计时。已有LockHandCard仍可用于明确原单牌，范围和待CN政策见[契约](m3-renferal-hand-traps.md)。

原生满血保留附魔复生用CardDefinition.reborn_policy=full_health_enchantments及REBORN声明。真实匹配抽牌需在抽到时施放前取得局部法强时，用DrawMatchingSpellDamage(player_id, SPELL查询, source_id, amount)；普通存储授予用GrantStoredSpellDamage(原CardReference, amount, source_id)。不要手填CAST材料或改成玩家全局下一法术奖励；有限范围见[契约](m3-native-reborn-fire-draw.md)。

真实原随从属性奖励使用SetCapturedMinionStats(MinionReference.capture(entity), health=value, source_id=source_id)，复用旧属性层。真实原生手牌/牌库单事件成长可声明HandProgressSpec的zone=(Zone.HAND,Zone.DECK)，只允许普通MINION的重复单位完成回调，不能扩成任意区域或组合矩阵；旧候选移区失效与私有投影见[契约](m3-stored-growth-cards.md)。

真实自增益之后随机攻击敌方随从时，先交原BuffCapturedMinion，再用AttackRandomEnemyMinion(BoardPresenceReference.capture(state, source_id), player_id, source_id)。原源/玩家保持、候选晚取、选中防守方原驻留与原ForceAttack共同处理恢复和离场；有限范围及待CN边界见[契约](m3-beast-trigger-cards.md)。

持牌打出龙不能用后来场上牌面或单纯召唤代替；以原HandProgress承诺窗和提交卡面/附魔判定。召唤成长须核对原SuccessfulSummonRecord并绑定原来源驻留。固定明示家族传完整SummonByCard候选与cause，不从已实现列表筛池；声明和待CN边界见[契约](m3-entry-native-cards.md)。

原组召唤后给每个实际交付一个额外效果时，用SummonOrderedGroup(..., bonus_effects=True)。不要在同名衍生物上伪造能力、按当前场位抓目标或在第一次召唤后提前发完奖励；原CardSummonDelivery引用、奖励前缀及共享候选由公共层处理。具体限制和待CN边界见[契约](m3-summon-group-bonus.md)。

真实洗牌效果用deck_shuffles.shuffled(context, entries, player_id=...)或ShuffleDeckCards明确批次、原actor及接收牌库；不按循环插入张数计洗牌，也不从当前所有者猜原归因。只接受同步原随机区域原语；未知来源、位置放置及临时返回边界见[契约](m3-semantic-deck-shuffles.md)。

抽另一方牌库的物理卡时，用DrawMatching的owner_id指定原DECK，player_id指定实际抽牌者；匹配已用身份可用card_ids，最低DECK本地费用可用lowest_cost。不要先移牌再伪装普通抽牌或创建副本，CWD/爆牌/补抽和原引用由公共执行器负责；历史关联和待CN政策见[契约](m3-deck-history-native-cards.md)。

真实多目标复制先捕获候选的BoardPresenceReference，再将它交给原CopyMinion；各份当前材料须在自身真实接受窗口捕获，不能提前冻结共同附件时钟。旧整数目标仍可使用，归因继续用SummonCause.capture，成功后授予走on_summon。生命周期与待CN政策见[复制驻留契约](m3-six-cost-native-cards.md)。

三张真实持牌消费者继续声明既有HandProgressSpec。generic spell_cast_accepted允许已核对的SPELL转MINION目标，其他跨类/事件与普通UpgradeHandCard保持拒绝；额外授予能力不静默裁掉。持牌结束政策、原弃牌和完整形态见[契约](m3-held-draw-forms.md)。

LockHandCard是有限手动资格门禁，不改变报价或支付账户；当前复制保留原时钟，base复制及重置清除。真实不同费用抽牌和拟态原材料使用扩展的DrawPhysicalGroup，不按手牌末项猜原受益。完整声明和待CN政策见[抽牌保留契约](m3-draw-retention-limits.md)。

整组抽牌后选牌、减费、转交或增益可使用DrawPhysicalGroup及有限DrawGroupSlot/DrawGroupReward。普通槽与随机匹配槽保持不同空池政策，原始身份须有真实开局事实，不能从Scenario牌名补造；特殊defining_hand_source转交仍明确不支持。材料和窗口见[抽牌组契约](m3-physical-draw-groups.md)。

需要复制体首次入场即带额外关键词时，CopyStoredMinion的minion_grant必须有SummonCause，授予者与原因严格一致。死亡来源印刷复制交原DeathRecord；弃牌之后的收益用on_success；已施放法术归还要保存原分配而非新建同名牌，具体限制见[契约](m3-original-material-spells.md)。

使用`DrawMatchingWithFollowup`表达“先抽完，再对原抽牌奖励”，不要用最后手牌、draw_history总增量或逐张即时Buff代替。具名回调得到完成的原context.draw及同组奖励前状态，输出BuffStoredCard仍保留原驻留。健康死亡归因和必要真实衍生示例见[契约](m3-health-draw-beneficiaries.md)。

当前手牌费用判断不要以印刷费用代替未选择报价，也不能消费一次费用修正。加甲后的护甲、伤害后的手牌条件和消灭后的全场目标应在明确续接窗口读取；使用原吸血声明与技能复原原语，不另造治疗/技能账本，见[真实条件法术契约](m3-health-resource-spells.md)。

需要保存随机不同冻结目标时使用`FreezeRandomEnemyMinions`，已选引用过期不补抽；不同伤害的指定敌方主目标与随机其他目标使用`DamageEnemyAndRandomOthers`并提供原`SourceAllocationFact`。随机伤害死亡抽牌继续交原批归因，完整窗口和真实施法要求见[有限目标契约](m3-spell-target-sequences.md)。

真实伤害后的条件抽牌可使用既有Damage.on_result与原HealthResult、RuleContext捕获事实；需要后续新场面时应明确使用原续接接口。不要把稍后复生体当作原目标存活，也不要给具名衍生物重复定义白板。实例与窗口见[六张伤害法术契约](m3-health-sequence-spells.md)。

原归因战场复制可声明`CopyMinion(..., cause=SummonCause.capture(context), on_summon=behavior_id)`，每个实际交付在入场反应后续接。不能从最后场位猜目标，也不能以同ID的新驻留接替原复制体；原材料查询与私有分身示例见[契约](m3-copy-followups-hidden-pairs.md)。未声明时保持原复制行为。

真实卡面要求存储退役触发亡语时，声明`CardDefinition(..., deathrattle=behavior_id, stored_deathrattle=True)`；不能另绑重复的`on_discard`/`on_destroyed`。普通弃牌、销毁和溢出仍沿原区域效果，原退役事件和完整亡语计划由内核接受。有限载体与schema273见[存储亡语契约](m3-stored-deathrattles.md)。

法术授予亡语时，用已注册行为ID调用`GrantDeathrattle`，保留实际授予者的source_id。亡语主体的召唤需以当前亡语上下文捕获`SummonCause`，不能沿用原施法者或把召唤物当来源；自然死亡位置与主动触发位置分别声明。完整依赖、既有附件生命周期和内部位置边界见[剑龙骑术契约](m3-granted-deathrattle-cards.md)。

补满手牌使用zones.FillHandWithCard(player_id, card_id, source_id)，不在纯卡牌上下文猜默认上限10。固定随机家族用一次SummonByCard候选集，全部依次召唤用多个单项请求，均携带真实cause；详见[固定伙伴契约](m3-fixed-companion-cards.md)。

印刷随从使用StatRelationOperand.CONTROLLER_OPPONENT_TURN声明条件攻击；不要监听回合事件叠永久Buff。DrawMatching(..., selection="highest_cost")比较实际牌库本地费用，不能替换成手牌报价。武器吸血及生命周期仍用原声明，详见[契约](m3-native-weapon-turn-draw-cards.md)。

随从单位随机分配使用原SplitDamage，跨双方的少量分配可由逐项命名InvokeBehavior重查后提交RandomDamage；单次十点与一次不同目标批量抽样必须分清。随从主体使用MINION_ABILITY，不能借SPELL专用报价或真实施法号。实际入口、生命期与待CN边界见[原生随机伤害契约](m3-native-random-damage-cards.md)。

最高费用复活可组合Resurrect(query=DeathQuery(cost_extreme="highest"), cause=SummonCause.capture(context))；按上个本人回合取全部法术时，读取query_previous_owner_turn的完整rows，不能用matched过滤无学派行，也不能用自动cast记录替代个人play记录。用法和待CN边界见[历史返还契约](m3-history-recovery-cards.md)。

一次销毁已捕获的多张牌库牌时使用DestroyDeckBatch(tuple_of_card_references, source_id)，不要用反应可穿插的多个单张请求模拟原批次。多次召唤须分别提交带实际cause的SummonByCard，materials是候选集；显式变形复用公共替换入口以保留正确物理来源。用法和边界见[物理区域契约](m3-physical-zone-cards.md)。

跟随原攻击时，使用ForceAttack(BoardPresenceReference.capture(ctx.state, source_id), captured_defender)，随从受击者同样捕获原驻留，英雄使用物理ID。离场重入场不重绑，未来引用在origin_state codec及执行拒绝；原整数请求继续原政策。原攻击与击杀条件读取原CharacterAttackRecord/COMBAT原因，勿用裸伤害、后来死亡或当前同名对象补事实。详见[原生攻击续接](m3-attack-followup-cards.md)。

传送门主体调用`SummonFromPool(..., cause=SummonCause.capture(context))`，传实际自动施法的上下文，不能只交来源ID或借外层抽牌法术。原召唤及池模块负责次数、选择和历史收据，卡牌不自行拼接接受事实；回溯编号复用及标准可达来源边界见[契约](m3-standard-portal-summon-source.md)。

已有直接旧召唤主体可用`summon_quantities.card_summon(context, player_id, card_id, position=None, stats=None)`显式传真实上下文；它在原数量门禁适用时交给现有`SummonByCard`，其余保持相同普通请求。不在解释器中猜来源，也不绕过无来源请求的明确拒绝。原生属性、顺劈及0反击政策和剩余旧路径边界见[契约](m3-static-provider-cards.md)。

真实下一张指定牌可用`AddCostModifier`的独立`combo_only`、`temporary_only`或既有种族筛选，有限`maximum_cost`只用于纯生命支付转换。不要用卡名白名单或整组换手租约代替实际临时资格。英雄禁疗到本人开始用`GrantHealthRule(..., until_owner_turn_start=...)`；原报价期限、排序与保存边界见[契约](m3-qualified-next-card-costs.md)。

显式玩家健康来源保存原物理事实与受益方，普通玩家效果默认保持原语义；逻辑伤害委托原健康层，下一真实对手期间复用原实例/费用/时钟。严格捕获、解码、玩家隔离和统一格式常量见[玩家健康来源契约](m3-player-effect-health-source.md)，实际进度与验收仅在两台账。

实际下一次技能费用、整局随从设费、开局双方上限/充能水晶和本方治疗增加沿现有公共层组合，扩展约定见[持续费用与真实开局契约](m3-persistent-economy-cards.md)。实际进度、验证与下一项仍只在两台账维护。

消灭后续接用sacrifice.DestroyCapturedMinion，受益者用BuffCapturedMinion保持原驻留；当前HAND种族与最低报价复制用zones.CopyLowestCostMinion。cross_zone.TakeCapturedMinion可绑定普通手牌原付款目标或已有直接引用，委托原永久无source转控。两项关键词用RequestChoice与GrantCapturedKeyword；完整材料/付款证明用法见[定向战吼契约](m3-targeted-battlecry-cards.md)。

原当前攻击力筛选抽牌用zones.DrawMinionWithAttack(player_id, attack, source_id)，空匹配skip，普通draw/burn与FrameCodec共享。持牌/灌注/目标种族条件通过PlayerTargetRuleSpec仅看玩家DTO，主体另用原事实查询；生命翻倍用DoubleStats，不重置已有受伤。完整用法及依据见[条件战吼契约](m3-conditional-battlecry-cards.md)。

当前属性战吼用命名InvokeBehavior读取，再交原Buff/DamageBatch；生命属性减少用负health Buff。敌角色/敌随从目标用原TargetSpec(IF_AVAILABLE)，与纯召唤绕过战吼一致。过滤物理抽牌用DrawMatching后接Imbue，不给原流程虚构random_choice通知；用法及待CN边界见[战吼卡契约](m3-simple-battlecry-cards.md)。

亡语自然死亡用ctx.death.attack读取原攻击快照，存活效果激活不得伪造死亡；原SplitDamage指定MINION_ABILITY避免法伤。当前持龙/最右牌用命名InvokeBehavior后查询，区域改费用CardReference/ModifyStoredCost，牌库底印刷新副本用AddToDeck的bottom与cost。实际依赖、装备和Imbue用法见[亡语卡契约](m3-death-followup-cards.md)。

逐次“施放后”订阅spell_cast_finished并读取原cast记录；card_played保留物理出牌含义。SummonCause.capture按实际发起来源判定cast/power归因，监听对象不冒充发起者。基础出牌/治疗事实、原攻击完成、对手手牌招募及邻接光环用法见[基础触发卡契约](m3-basic-trigger-cards.md)。

原生结束声明继续用EndTurnSpec指定controller/either，动态后段用命名InvokeBehavior读取当前局面。需要按来源身材召唤固定token时用source_stat_summons.SummonBySourceStats，传原MinionReference、完整正数接受身材及SummonCause；当前驻留有效时重读，失效保留接受材料，统一委托SummonByCard。原接受窗口及待CN边界见[结束卡牌契约](m3-native-end-cards.md)。

最高攻击/最低生命等主体先形成完整原引用候选，再用`spell_targets.RandomSpellTarget`，随机后`ApplySpellTarget`守原随从生命周期。按原抽牌费用条件使用`spell_sequences.DrawIfCheap`；手牌批量属性继续复用BuffMinionsInZones。有限用途和待CN政策见[属性与抽牌契约](m3-stat-draw-spells.md)。

有限递减AOE、按原批次死亡抽牌、原抽牌减费用`hs_sim.engine.spell_sequences`的三个有限请求，绑定实际cast/health batch/CardReference；不要自行修改抽牌历史、按当前手牌末尾选目标或重写伤害结算。各入口及内部政策见[伤害序列与抽牌契约](m3-spell-sequences.md)。

手牌边缘固定费用用hand_edge、在场本人传说卡面固定费用用controlled_legendary的IntrinsicCostSpec，均复用原完整CostPresenceMatch与付款，不在卡牌回调改价。传说目标用TargetPredicateSpec.printed_rarities，已证无标签用Rarity.NONE，未知不得当成普通。需在死亡/反应后保留原生命结果时用InvokeHealthResult并传原health_resolved事件。完整域、虚拟报价和待CN政策见[条件法术契约](m3-conditional-health-spells.md)。

从敌方角色偷取生命上限用`hs_sim.engine.health_theft.StealHealthToHero`，并列原引用用`RandomStealHealthToHero`；随从传MinionReference，英雄传物理ID，来源必须实际存在。最低生命等候选政策由真实卡牌的纯主体决定，不能用伤害/治疗近似或在随机等待后重绑对象。原属性生命周期、原子提交与待CN政策见[契约](m2-character-health-theft.md)；多次结束主体若需观察前次结果，使用命名InvokeBehavior逐次取当前场面。

接入同文核心别名时，核对完整当前卡面与旧主体的触发入口及目标声明，再明确替换名称、身材和元数据；连击不能移成战吼。普通“治疗至满”使用目标当前max_health形成Heal请求，保留公共过量治疗/转换语义，抽牌仍接原Draw；需精确校准的政策单独登记。连续效果若后段要观察前段反应后的局面，使用命名InvokeBehavior再查询，不在首个回调中提前捕获后续候选。具体用法见[内容包](cards.md)。

真实无限随从伤害用`InfiniteDamageMinion(ref, source_id)`，并列原引用组用`RandomInfiniteDamageMinion(tuple(refs), source_id)`，均从hs_sim.engine.infinite_damage导入。仅SPELL来源，原引用失效不改绑，防护仍正常执行；明确内部上限与RNG政策见[契约](m2-infinite-health.md)。不要自行传大整数、用Destroy代替或将显示“∞”门槛用于战斗，也不能据本入口宣称攻击/费用无限值已支持。

真实攻击者变形用原窗口接受的MinionReference及TransformCapturedMinion，不重建实体或取消普通驻留。由某次死亡复活用ResurrectMinion(..., death_id, position=..., source_id=..., cause=SummonCause.capture(ctx))，原完整印刷卡面/组件、巨型入场和数量由内核处理，不能重放战吼；关联口径与待CN政策见[契约](m4-reactive-secrets.md)。

真实“伤害余量给英雄”使用`DamageExcessToHero(MinionReference.capture(target), amount, source_id)`，从hs_sim.engine.excess_damage导入；来源必须是实际SPELL。不要先发完整Damage再从damage_dealt补算余量，也不要为第二份再次加法伤。原目标失效、数值层、同批提交和待CN政策见[契约](m2-excess-damage.md)；其他过量用途不能假装为此有限入口。

原实例回手用ReturnCapturedMinion(ref,source_id,to_owner=...,cost=...,on_success=(...))；随机回手并对同一对象减费用RandomReturnCapturedMinion(tuple(refs),source_id,cost)。成功门槛、原引用失效和反应等待见[契约](m3-return-followups.md)。BuffStoredCard可对物理手牌/牌库武器加攻击，但武器health必须为0，不能把耐久当生命修改。

按本回合敌英雄实际受伤次数减费用HeroDamageTakenCostSpec('cost.enemy-hero-current-turn-damage-count-v1')；双方无随从固定金额用唯一board_no_minions IntrinsicCostSpec。普通法术复用BoardMinionCostSpec('enemy')及HandCountCostSpec('friendly')，后者计物理自身、虚拟另加一张假设卡。原完整操作数、时钟与付款顺序见[伤害次数与区域费用](m3-damage-packets-zone-costs.md)，卡牌回调不能维护第二份计数或手动扣费。

原相邻手牌使用submitted_hand_neighbors(ctx)配合ModifyStoredCost，下一种族减费用AddCostModifier(...,uses_remaining=1,tribes_any=(...))；英雄本回合治疗后的生命账户声明pay_health_if_hero_healed并使用原唯一治疗条件事实。实际原位置、引用失效、支付顺序和有限用途见[契约](m3-submitted-neighbors-next-costs.md)，不能在卡牌回调中改写手牌索引、余额或付款缓存。

真实手牌其他龙、场上休眠或本回合神圣/暗影条件费用，使用原IntrinsicCostSpec的三个有限condition和对应history_profile_id；不能在卡牌回调中改写费用缓存。完整依据进入原condition_facts并绑定原付款subject，虚拟预览不分配实体；见[当前条件费用](m3-current-presence-costs.md)。原字段布局/schema267保持，新语义由core311与注册表保护。

原物理招募需要对实际成功主体继续授予效果时，使用`SummonFromZone(..., cause=SummonCause.capture(ctx), on_summon=behavior_id)`；回调的target是原delivery的实际存活引用，不读取最后场位。额外副本分别接受续接，失效主体跳过，等待、回滚与私有收据由内核负责；见[招募续接](m3-recruit-followups.md)。实际保存字段变更由schema267/core310保护，不能自动认证旧记录。

群体消灭用hs_sim.engine.effects.DestroyBatch(tuple(ids), source_id)，一次标记后交共享死亡检查；只有原场上随从/地标参与，不能用多个Destroy替代同批效果。随机回手用RandomReturnToHand(tuple(ids), source_id)，沿公共RNG选择和原拥有者交付/满手死亡政策。新内容的分段InvokeBehavior、明确目标谓词与副种族来源约定见[内容包契约](cards.md)。保存布局保持，核心指令的版本由mechanics签名控制；卡牌语义变化另升内容包版本。

真实卡牌按效果分批接入时使用[卡牌内容包入口](cards.md)，复用下述公共指令与生命周期；历史代表包默认身份保留。目标版本、完整池与官方校准由独立台账维护，分类提示不自动生成可执行效果。

拼装包在注册表冻结前用`Registry.register_assemble_template`登记能完整还原原卡的`AssembleTemplate`。来源行为返回`hs_sim.engine.assemble_offers.Assemble`，引用明确版本的审核候选池；抽样、真正半边选择和新定义交付由公共入口负责。只为实际审核片段声明兼容性，保留主卡身材/费用与不可变配方身份，未知内容明确报错。现有有限范围及显式空/小池政策见[拼装契约](m4-assemble.md)，不是完整正式池声明。

原生存储/创建溢出按实际分配事实与接收者复用CardDestructionRecord/B150独立接受；11非BOARD生产函数保原抽取/创建/交付，原监听后本牌主体沿原解释器，无新账本、模块、字段、账户或组合。BOARD回手普通死亡独立，未分类native来源仍明确拒绝。见[溢出契约](m3-native-overflow-body.md)，prototype-v282/core-effects-v276/schema247，观察82/命令12/replay1及生产FP保持；生成/返回政策与精确CN仍开放，实际执行与下一项只在两台账。

满手BOARD随从回手失败保留原owner/controller及死亡材料，标记普通消灭后由原死亡协调器记录/移除/适用亡语、残骸与复生；目的容量只决定失败，不成功回手重置或先改控制。正常回手和存储溢出保持独立，无新模块/字段/账户/组合；恢复/回放/信息复用原解释器，见[满手回手契约](m2-full-hand-return-death.md)。prototype-v281/core-effects-v275，schema246/观察82/命令12/replay1及生产FP保持。native存储burn与精确CN仍开放，实际执行与下一项只在两台账。

显式HAND/DECK销毁由DestroyStoredCard与原DestroyDeckCard共享原引用、移区和续接；原生on_destroyed从离区实体独立接受，当前复制沿原溯源政策，执行者为当前物理卡。没有弃牌/场上死亡替代或新触发器；context.destruction及恢复/事件/回放/信息沿原解释器，见[存储销毁契约](m3-stored-card-destruction.md)。prototype-v280/core-effects-v274/schema246拒旧1～245，观察82/命令12/replay1与生产FP保持；无新持久字段/模块/账户/授予或组合。未知native burn明确报错，分类/接受窗及精确CN仍开放，实际执行与下一项只在两台账。

已装备武器物理转控以TransferWeapon/EquippedWeaponReference保持原实体、owner和材料，明确安装引用；复用原equip_entity目的替换及WEAPON同区移区，源转出不死亡，更新双方槽/英雄贡献而不清攻击使用。引用、事件与waiting恢复/回放/信息沿原解释器，见[武器转控契约](m2-weapon-transfer.md)。prototype-v279/core-effects-v273/schema245拒旧1～244，公开转移使player-view-v81，命令12/replay1及生产FP保持；无新持久字段/账户/模块/组合。装备计数/精确CN窗口开放，实际执行和下一项只在两台账。

英雄当前生命赋值以SetHeroHealth写原damage，保留最大生命/护甲/附魔，物理目标替换失效不映射新英雄，死或待销毁目标不能复活。原实际英雄变化/事件封套、死亡检查、待选和回放共享；玩家仅公开数量/当前生命。见[剩余生命契约](m2-remaining-hero-health.md)。prototype-v278/core-effects-v272/schema244拒旧1～243，公开事件域升player-view-v80，命令12/replay1及生产FP保持；无新持久字段/账户/模块/组合。超上限钳制及精确窗口待CN，实际执行与下一项只在两台账。

效果直接法力消耗以SpendMana复用原临时优先投影、永久/临时/过载账目，ManaConsumptionRecord冻结实际两端和原来源/CAST；原费用保持。原法术法力输入合并付款与消费两完整前缀，无新公式，回调/恢复/回放/信息沿原解释器。见[直接消耗契约](m2-mana-consumption.md)。prototype-v277/core-effects-v271/schema243拒旧1～242，公开mana_consumed使观察player-view-v79，命令12/replay1及生产FP保持；一历史字段/两冻结费用字段，无新账户/模块/组合。精确CN/正式来源开放，执行与下一项仅在两台账。

直接护甲减少由LoseArmor复用当前安装英雄账户，固定量封顶/None全清，ArmorLossResult六字段冻结实际delta；原反应后回调保存原扣除上下文，伤害/生命/费用事实隔离。事件及帧恢复沿原管线，玩家仅公开正量armor_lost，观察player-view-v78、命令12/replay1及生产FP保持。见[直接护甲契约](m2-armor-loss.md)。prototype-v276/core-effects-v270/schema242拒旧1～241，无新持久字段/模块/账户/组合；事件窗口/精确CN开放，实际执行与下一项仅在两台账。

原生英雄技能次数由HeroPowerUseAuraSpec和既有原生能力保存，纯effective_use_limit按当前控制者活源取有限max/无限None；基准/已用/付款保持，来源生命周期与选择恢复/回放沿原管线。玩家有效上限共用查询，观察player-view-v77允许空上限，命令12/replay1及生产FP保持。见[次数贡献契约](m2-hero-power-use-auras.md)。prototype-v275/core-effects-v269/schema241拒旧1～240，一能力字段，无新模块/计数缓存/账户/组合；max/多槽/准确CN开放，执行与下一项仅在两台账。

双方英雄技能禁用复用原印刷HERO_POWER_SUPPRESSOR内核标记、公共手动资格/effect失败和被动原捕获状态；普通更新及安装/替换继续，已接受主体保留。来源生命周期/恢复/回放与玩家边界沿原管线，暂无新状态字段、模块、账户或组合。见[禁用契约](m2-hero-power-prohibition.md)。prototype-v274/core-effects-v268/schema240拒旧1～239，玩家接口和生产FP保持；内部枚举47非官方机制分母，精确CN/完整来源开放，实际执行与下一项仅在两台账。

周期法术费用以原every_nth_per_turn和FirstPlayCostFact.cast_rows/cast_history_length保存完整物理施法前缀，本人当前实际回合已接受物理根决定序号；原首张/周期随从继续手牌依据，付款与生命周期/恢复/回放/信息沿原管线。反制/无目标排除和全自动起源是明确本地政策，不能据历史数值公告认证CN。见[周期法术契约](m2-periodic-spell-cost-auras.md)。prototype-v273/core-effects-v267/schema239拒旧1～238，玩家接口及生产FP保持；两个冻结操作数字段，无新模块/账户/组合，实际执行与下一项仅在两台账。

下一次法术限定法伤以原next_spell_damage玩家实例和SpellCastRecord.spell_damage_effects保存待用/领取身份，成功物理主体接受时原子移交，整次主体可读、后续独立施法隔离，未使用在实际当前回合清理。普通与整预算法伤共享cast_id查询，主历史和预算嵌套CAST使用同一解码；等待/回滚/回放/信息沿原管线，无新运行模块或组合。见[限定窗口契约](m2-next-spell-damage-window.md)。prototype-v272/core-effects-v266/schema238拒旧1～237，玩家接口与生产FP保持；精确CN和完整来源开放，实际执行与下一项仅在两台账。

玩家本回合法术目标规则以原PlayerEffectSpec.turn_rule/target_policy和实例created_turn进入公共目标查询，来源离场后保持、真实结束清理统一退休，不占奥秘区；原Spell接受状态复用，非法术证明保持。没有新账户/状态字段/模块或组合。见[目标规则契约](m2-player-spell-target-rules.md)。prototype-v271/core-effects-v265/schema237，玩家接口和生产FP保持；自动精确CN/正式范围开放，实际执行与下一项仅在两台账。

原生关键词光环condition=controller_turn以当前控制者/实际行动玩家决定英雄免疫，真正开始前刷新已有贡献和缓存；结束效果保持旧回合，跳过不切换。条件改always仍核对原生声明，来源生命周期/恢复/回滚/玩家边界共享；没有新模块或状态字段。见[回合条件契约](m2-controller-turn-keyword-auras.md)。prototype-v270/core-effects-v264，schema236及玩家接口/生产身份保持；精确CN和完整范围开放，实际执行与下一项仅在两台账。

原生周期随从费用光环以CostAuraSpec.every_nth_per_turn和原FirstPlayCostFact.ordinal复用完整出牌前缀；无需新时钟、预算或模块，付款/生命周期/等待/回放沿原管线。仅REV_021必要实验，周期法术及其他起源明确未完成，不以手牌根推定施法。见[周期费用契约](m2-periodic-play-turn-cost-auras.md)。prototype-v269/core-effects-v263/schema236，生产身份/玩家接口保持；实际执行与下一项仅在两台账。

原生首张费用光环在原CostAuraSpec声明first_per_turn，以付款者当前实际回合的完整付费手牌前缀报价；来源进入不重置首张，实际付款冻结原价，生命周期/等待/回滚/玩家隔离复用原管线。FirstPlayCostFact保存原窗并与保留历史绑定，没有新费用模块/账户/状态缓存或组合。见[费用契约](m2-first-play-turn-cost-auras.md)。prototype-v268/core-effects-v262/schema235，正式池/间接起源/完整卡雷苟斯和精确CN仍开放；实际执行与下一项仅在两台账。

每局一次玩家约束可用旧PlayerEffectSpec永久标记与AddPlayerEffect实际提交表达，来源实体变化不重置；必要TOY_385实验以既有出牌历史判断条件，先标记后安排额外回合。没有新整局模块/状态字段/版本或组合。见[既有表达契约](m5-player-once-per-game.md)。仅付费手牌受限配方，其他主体/间接与精确CN仍开放；实际执行与下一项仅在两台账。

原生有限触发的reset=turn预算属于每物理附件，trigger_turn随实际新回合刷新双方；CheckLimitedTrigger冻结budget_turn防旧窗借新预算，先消耗再主体。默认实例次数及法术迸发/暴怒保持，分类结束组合明确拒绝。仅TOY_651必要实验；七族原行调查没有据标签数宣称范围完整。见[回合预算契约](m5-turn-scoped-limited-triggers.md)。prototype-v267/core-effects-v261/schema234拒旧1～233，玩家接口/生产FP保持；实际执行与下一项仅在两台账。

TransformDefiningHandCardFromPool复用完整版本候选、整数抽样和原生自身变形，保持物理接收者/获取/原始来源，未知符合条件候选不删池。完整私有request/context/本方回合见证/有序权重/结果/RNG证明局部重演并重算池，空池不耗RNG；等待与回滚沿原解释器。仅三必要来源及六目的受限实验，卷轴原形禁止手动为待CN政策。见[随机选面契约](m3-native-hand-transform-pools.md)。prototype-v266/core-effects-v260/schema233结构、玩家接口与生产注册表保持；实际执行和下一项仅在两台账。

原生回合变形来源以独立defining_hand_source能力保存原始卡牌ID及物理来源，HAND本方回合开始沿原事件解释器执行。TransformDefiningHandCard共享印刷重置，清旧附件后只保留同一来源/见证与接收者获取；三类来源固定原物理类型。外部变形/离手依明确本地退役政策；带来源的当前复制/转手明确拒绝。见[原生来源契约](m3-native-defining-hand-source.md)。prototype-v265/core-effects-v259/schema233拒旧1～232，玩家接口保持；固定目的卡面不是完整真实卡或正式随机池，未CN校准。实际执行和下一项仅在两台账。

TransformStoredIntoCopy通过双CardReference保持接收者实体/归属/区域/槽位/获取，清除旧卡面与附件后沿原CopyCard.current安装来源当前材料和新附件ID，原来源政策保持。自复制先冻结；来源/接收者stale则跳过，复合材料明确报错。完整安装后才发布私有变形通知，不新建或出牌；无新字段/账户/模块/组合。见[物理复制变形](m3-stored-copy-transform.md)。这不等于完整连续定义来源或国服认证，实际执行与下一项仅在两台账。

普通TransformStoredCard以CardReference捕获HAND/DECK物理卡牌，与原TransformCapturedMinion共享印刷重置、明确数值保费、epoch/实例更新及私有身份隐藏。法术/武器补上同一入口，不新增触发系统、状态字段、账户或组合。重复手牌回合源已有HandProgressSpec；普通变形清除旧监听，不能冒作泽鲁斯等真实连续变形来源。见[存储变形契约](m3-stored-card-transform.md)。完整来源/随机正式池/国服仍开放；实际执行与下一项仅在两台账。

物理手牌/牌库结构与手动出牌资格分别由hand_playable和manual_playable表达。后者默认true，当前卡面false可正常持有、抽取和复制，但原手动接受前验证/枚举、解释器入口及原付款收据都拒绝；变形与重置沿原当前卡面生命周期。没有新实体缓存、账户、效果执行器或组合，也没有把完整殒命暗影当成白板注册。见[资格契约](m3-manual-play-eligibility.md)；自动CAST、生成候选与完整来源/CN仍需独立证据。实际执行与下一项只在两台账。

永久不可交互场上载体以原无限期DormancyState共享场位、普通操作资格和休眠期间触发，显式原生permanent_dormancy声明禁止唤醒并与保存状态绑定。必要虚空传送门沿原自然结束主体及两次召唤执行，无新执行器/关键词/组合；普通条件和定时休眠保持。见[永久载体契约](m4-permanent-board-carriers.md)。混合UNTOUCHABLE标签不批量映射，其他主体、特殊移除及精确CN开放。prototype-v261/core-effects-v255/schema231拒旧1～230，观察76/命令12/replay1及生产64/合成3保持；默认注册表身份保持，实际执行与下一项只在两台账。

印刷支付账户由原CardDefinition.cost_payment不可变声明启动物理/生成及冻结费用代数，原MANA/HEALTH/ARMOR/CORPSES账户、费用覆盖、资格/付款和生命周期保持。创建、抽取、复制/重置/变形依据固定卡面，原等待/事务/回放/玩家隔离共享；没有新的支付器/实体缓存/账户/组合。见[印刷账户契约](m2-native-cost-payment.md)。两必要构筑代表与JAIL未适配原行分开，受限发现不等于正式池，精确CN保持开放。prototype-v260/core-effects-v254/schema230拒旧1～229，观察76/命令12/replay1及生产64/合成3保持；默认注册表指纹保持，实际执行与下一项仅在两台账。

直接牌库创建复用原AddToDeck/card_creation.install，只追加CreatedMinionGrant；数值/关键词/身份在首个创建及入库事件前完成，不经过手牌。所选DiscoveryMinionGift声明hand/deck_top有限目的地，原完整绑定/实际ChoiceResult/私有收据冻结并核对，甜美梦境+4/+5沿原top创建，正常抽取/复制/重置与事务/回放/玩家隔离共享。见[牌库创建契约](m3-deck-creation-grants.md)。八配方受限实验保留12原描述与四未知主体，完整族/正式池/精确CN开放，无新执行器/账户/组合。prototype-v259/core-effects-v253/schema229拒旧1～228，观察76/命令12/replay1及生产64/合成3保持；实际执行与下一项仅在两台账。

真实普通赐福配方复用原CreatedMinionGrant/成对发现与战斗，休憩饱足声明+2/+2扰魔、梦境行者声明冲锋、鹰身人之爪声明普通圣盾/风怒；没有新机制模块或组合。见[普通配方契约](m3-dark-gift-keyword-recipes.md)。七配方受限实验保留全部12原描述，五特殊主体/正式池/精确CN未覆盖，不能凭已有self重复或存储复制推称完整接入。原prototype-v258/core-effects-v252/schema228、观察76/命令12/replay1及生产64/合成3保持；实际执行与下一项仅在两台账。

黑暗之赐的独立成对发现基础复用原DiscoverFromPool/POOL_DISCOVERY，显式版本赐福库存保存三种不同资格绑定，原选择解释器注入完整ChoiceResult后由原AddToHand原子交付所选配方。创建identity仅借原附魔保留，私有收据不提供给玩家；恢复/回放/回滚及原复制/重置共享。见[成对发现契约](m3-paired-discovery.md)。疯狂生物只接受限3费随从与四配方实验，12本地描述保留，未知主体/其他来源/正式池/精确CN开放，不泛化动态主体或组合。引入时prototype-v258/core-effects-v252/schema228，观察76/命令12/replay1和生产64/合成3保持；实际执行与下一项仅在两台账。

随从创建的普通数值/关键词授予复用原AddToHand/card_creation.install，末尾minion_grant保存不可变CreatedMinionGrant；原附魔和能力在首个创建/入手/烧毁事件前安装，原费用、来源、附件ID、生命周期、waiting/回放/回滚及玩家接口共享。只包含普通数值和七个真实赐福必要关键词，没有任意战吼/亡语/触发程序、新账户/模块或组合。见[创建授予契约](m3-created-minion-grants.md)，四真实隔离配方及两普通随从验证，狡诈拷问者仅传说发现来源证据；完整成对发现/正式池及精确CN开放。引入时prototype-v257/core-effects-v251/schema227，观察76/命令12/replay1和生产64/合成3保持；实际执行与下一项只在两台账。

满血保附魔复生是原复生返回规则的可选政策：原两关键词授予和AbilityInstance携带reborn_policy，冻结死亡材料决定规则，原复制入口重建新印刷本体并保留授予/附魔、重分ID，再消费全部复生和重算外部光环。普通1血复生保持；来源、期限、选择恢复/回放/回滚与玩家边界共享，无新模块/关键词/动作/事件或组合。见[复生契约](m2-full-health-reborn.md)，只有回荡恐怖描述/附魔与淡水鳄完整必要隔离配方；成对发现/完整池和精确CN开放。引入时prototype-v256/core-effects-v250/schema226，观察76/命令12/replay1及生产64/合成3保持。实际执行与下一项只在两台账。

[其他命名基础对照](m0-nonpower-named-foundation-map.md)核对52个来源标签与现有独立声明/读取，休眠、巨型、泰坦、灌注等复用原入口。黑暗之赐的满血保附魔复生有真实差异：普通复生固定1血且不复制附魔；已有冻结死亡材料与附件层是复用基础。印刷替代支付及永久不可交互物体仍逐载体核查，不由标签自动生成新执行器或外推酒馆规则。此为静态来源说明，实际执行/下一项仅在两台账。

[命名power标签对照](m0-named-power-foundation-map.md)将本地93命名标签与原公开声明/读取、载体类型及契约关联，保留全引用和完整原行pin。它是静态查阅路由，没有新增执行器或卡牌，不能代替完整来源/机制范围/正式池与CN证明。HandRepeatSpec(echo=False)和Echo副本费用政策已有分离；FORGETFUL、免沉默与视觉/模式标签按真实载体解释，不统一生成新能力。实际进度和下一项仍只在两台账。

本局永久英雄技能加伤复用命名阶段定位当前英雄、GrantHealthRule无到期附件和原HERO_POWER报价；技能换槽保留载体，英雄替换沿原持续附件复制重分ID，旧英雄不重复提供。提交前/交付后等待、支付/反制/事务/回放和玩家接口共享，无运行模块、关键词、账户或协议变化。见[永久加伤契约](m2-whole-game-hero-power-damage.md)，只有野火与火焰冲击完整必要隔离适配。官方22.0.2支持跨技能保留，精确CN/完整来源仍开放，不建立组合族；实际验收与下一项只在两台账。

原生英雄技能伤害加成复用原HealthRule的DAMAGE/SOURCE ADD、HERO_POWER分类和当前友方控制者；原英雄技能主体声明基础值，实际伤害报价读取有效来源，生命周期/选择恢复/回放与玩家接口共享。没有运行模块、关键词、持久状态或协议变更；见[英雄技能加伤契约](m2-hero-power-damage.md)。只有完整AT_003英雄之魂和HERO_08bp火焰冲击必要隔离适配，永久本局消费者/完整来源与精确CN开放，不建立组合族。实际验收与下一项只在两台账。

独立亡语禁止复用原自然/主动接受、公开目标规则和解释器；原生随从来源属性决定当前门禁，一个DeathRecord收据区分明确未接受的自然亡语，结构材料/尸体和已接受计划保持。来源沉默/离场/复制/休眠沿原实体生命周期，原英雄致死协调器及队列覆盖校验共享，不扩展特殊授予或组合。见[亡语禁止契约](m2-deathrattle-prohibition.md)。只有死亡守望者/装死/血法师三个必要完整隔离代表；prototype-v255/core-effects-v249/schema225，Keyword46，观察76/命令12/replay1及生产64/合成3保持，精确CN与完整来源开放。实际执行/下一项只在两台账。

持续冻结防护复用原关键词光环、Freeze、current复制与稳定刷新；一个CANT_BE_FROZEN属性阻止新增并清除已有冻结截止，来源离场不恢复旧截止，攻击次数和召唤限制保持。原unfrozen/freeze_unchanged、等待/回放/事务与玩家接口共享，无新持久字段/模块/组合，见[冻结防护契约](m2-freeze-prevention.md)。原沉默标签按载体解释，不推出全局免沉默；只有活化龙息/寒冰箭必要隔离适配。prototype-v254/core-effects-v248/schema224、Keyword45，观察76/命令12/replay1与生产64/合成3保持。精确CN和完整来源开放，实际结果/下一项只在两台账。

延系的独立基础复用原最近已关闭本人回合、冻结提交种族/单学派、完整匹配行与on_play/IntrinsicCostSpec；国服公告定义为上一回合，不是上一张牌。只有三个完整隔离代表，未改运行模块、持久状态、关键词或协议，见[延系基础契约](m3-kindred-basics.md)。按延系身份抽牌/下一次重复等真实消费者与精确CN仍开放，不建立组合族。实际执行和下一项只在两份台账。

攻击期间免疫作为原战斗属性，共享原宣告窗口/验证后交换攻击者角色；原有效武器/本体、普通防护与目标资格复用，平时及防守不免疫。原ActionWindow捕获已有入场引用，同ID新入场不继承旧攻击；无新攻击流程、状态账户或组合，见[基础契约](m2-attack-scoped-immunity.md)。只有完整长弓/愤怒的小鸟必要隔离代表；prototype-v253/core-effects-v247/schema223拒旧1～222，Keyword44、观察76/命令12/replay1与生产64/合成3保持。实际结果和下一项只在两份台账。

法术伤害加成系数是原Damage末尾的默认1操作数：原健康窗口按实际来源控制者/学派取得S，再执行base+k*S，基础值不乘；批次冻结、独立重算、原结果/事务/等待和玩家隔离复用。仅必要AT_004完整raw/pin隔离代表，无新伤害管线、状态账户或组合，见[加成系数契约](m2-spell-bonus-multiplier.md)。prototype-v252/core-effects-v246/schema222拒旧1～221；观察76/命令12/replay1及生产64/合成3保持。实际结果与下一项只在两份台账。

主动疲劳由单次TakeFatigue与空牌库Draw共享原玩家计数和无来源伤害，主动入口不产生抽牌事实。可选on_fatigue取得原事件名义数值及递增时捕获上下文，在原伤害检查点后继续；防护不撤销递增，终局/事务/帧/回放沿原解释器。只有必要ETC_068隔离代表；准确CN及完整来源开放，见[共享疲劳契约](m2-explicit-fatigue.md)。实际进度与下一项只在两份台账。

牌库属性总量分配复用原起始随从费用和条件、当前DECK有序物理捕获与两普通存储增益；商余计算为纯卡牌行为，无新内核模块/状态/协议或RNG。已接受引用离区按原epoch守卫跳过，其他计划不重分配；生命周期、付款、等待恢复/回放及玩家隔离共享。见[属性分配契约](m3-deck-stat-allocation.md)。必要CATA_213仅完整隔离实验，隐藏余数顺序/精确检查点及CN待校准；实际进度与下一项只在两份台账。


单次随机获取及仅生成实体初始减费可复用原CheckDeckCondition、印刷候选GenerateFromPool(count=1)和CostSpec创建前装入；不新增执行器/状态字段或协议。原同ID牌/玩家费用不改，当前/基础复制、移动/重置、来源离场及等待恢复/回放沿原生命周期；见[生成实例费用契约](m3-conditional-generated-costs.md)。必要JAIL_806仅隔离有限实验池，完整正式池与精确CN开放；实际进度与下一项只在两份台账。


当前牌库数量条件普通战吼目标可由原IF_AVAILABLE随从域、带版本的纯玩家目标谓词（只读本人deck_count）及原付费输入/目标证明表达，无需新增条件flag。原CheckDeckCondition/Damage/来源吸血与解释器、等待恢复/回放共享；原提交和实际主体条件为不同原窗口，精确CN待校准。见[条件目标契约](m3-deck-count-conditional-targets.md)，必要BAR_916仅完整隔离实验；实际进度与下一项只在两份台账。


当前牌库数量条件持续自身攻击仅扩原StatRelationSpec的CONTROLLER_DECK_COUNT及两可选阈值字段，旧四操作数保持None；当前controller全部DECK数量复用B91查询，原条件层/派生缓存/事件归一/活跃与生命周期/捕获域共享。无新模块/状态字段/效果/执行器/动作或组合，新动态授予仍拒绝；见[自身攻击契约](m3-current-deck-count-attack.md)。必要JAIL_311完整实验、精确CN/正式池待校准；实际进度与下一项只在两份台账。


当前牌库数量条件费用扩展原IntrinsicCostSpec的current_deck_count及显式阈值/比较符，旧条件新字段保持None；单个物理SPELL固定减费复用原intrinsic-before-local/本地/外部/最低费用/账户管线。完整原有序DECK匹配进入旧Stage条件槽，临时CostQuote与实际CostUseReceipt各一current_deck字段绑定原支付依据，后续区域变化不重定价。原CardDefinition/Stage布局保持；见[当前牌数费用契约](m3-current-deck-count-costs.md)。必要JAIL_307完整实验、未签名来源不认证，精确CN/正式池待校准；实际进度与下一项只在两份台账。


当前物理牌库数量由DeckCountCondition(card_count,comparison,scope=current)声明，严格非负整数，at_most/at_least含等号；所有当前DECK槽位均计数，原构筑容量/原事实不代替当前数量。复用原CheckDeckCondition解释器及Draw/帧/回滚/玩家投影，原七条件语义及Check四字段保持，无新持久计数或执行器。必要JAIL_456仅完整实验，BAR_916目标/吸血与持续定价/属性独立界定；见[当前牌库数量契约](m3-current-deck-count.md)。精确CN待校准，实际进度与下一项只在两份台账。


起始无法术由原DeckCondition('starting','no_spells')有限谓词表达，scope/predicate两字段保持；原构筑全部定义查验后以PoolQuery(SPELL)判断不存在，当前区域/费用/卡面/硬币不改写原事实，未知opening/定义拒绝。原其他语义及CheckDeckCondition/check/register/帧/回滚/私有投影保持，无新payload、状态或执行器；JAIL_806仅raw依据，完整随机获取/减费主体及合法池另行处理；见[起始无法术契约](m3-starting-deck-no-spells.md)。精确CN待校准，实际进度与下一项只在两份台账。


起始不同印刷费用种类由冻结DeckCostDiversityCondition(min_distinct_costs,cost_basis,scope)声明，只允许严格非负整数及printed/starting；原构筑全牌型费用逐行查验后去重，0合法，同费重复只计一种，种类数≥显式最小值。原六类条件、CheckDeckCondition/解释器/帧/回滚/私有投影共享，无新状态或执行器；TLC_100仅raw需求证据，≥10是卡文推定未CN确认，自定义地标与完整适配另行处理；见[费用种类契约](m3-starting-deck-cost-diversity.md)。实际进度与下一项只在两份台账。


起始套牌随从费用求和由冻结DeckMinionCostSumCondition(total_cost,cost_basis,scope)声明，只允许严格非负整数及printed/starting；原构筑每槽MINION的印刷费用相加精确比较，重复分别计入，非随从排除但所有定义查验，空随从和0。原五类条件、CheckDeckCondition/解释器/帧/回滚及私有投影共享，无新持久字段或执行器；CATA_213仅raw需求证据，属性分配与完整适配另行处理；见[费用求和契约](m3-starting-deck-minion-cost-sum.md)。精确CN政策待校准，实际进度与下一项只在两份台账。


绑定原随从的单次开始/结束死亡可以由GrantLimitedTrigger/LimitedTriggerSpec的原附件、原来源及固定施放者条件表达。原消耗前守卫、消费后RuleContext.trigger、Buff当前到期、EndTurnSpec(either)、Destroy/死因及帧共享，无新计时或执行器；完整腐蚀术/力量的代价只作必要隔离实验，精确CN时序/来源与全部生命周期仍待校准；见[延迟死亡契约](m3-bound-minion-death.md)。实际进度和下一项只在两份台账。


原手牌跨回合期限由ScheduleHandRemoval保存完整原引用和目标本人真实结束计数，GameState.hand_deadlines保留不可变根与关闭收据。原CardReference、owner_turn_history、RemoveFromGame、选择帧/回滚/恢复/回放及私有玩家投影共享；准确原手牌生命期与三结束窗为待国服校准的明确内部政策。只在可见手牌槽显示剩余结束次数，完整根与控制队列私有；见[期限契约](m3-hand-deadlines.md)。实际进度与下一项只在两份台账。


起始套牌印刷费用上限由冻结DeckCostCeilingCondition(cost_limit,cost_basis,scope)声明，只允许非负整数、printed/starting，原构筑全部牌型逐条查验后≤比较，当前改费或换牌不重写原事实。原PoolQuery/CheckDeckCondition与四类既有声明共享，无新持久字段、计时器或执行器；见[费用上限契约](m3-starting-deck-cost-ceiling.md)。JAIL_860完整raw仅证据，完整原生延迟/法力政策另行界定；实际验收与下一项只在两份台账。


当前牌库所有随从费用严格比较由冻结DeckMinionCostCondition(cost,comparison,cost_basis,scope)声明，只允许非负整数、less/greater、local/current，等号不满足，非随从排除但所有定义完整查验。原local_cost/CheckDeckCondition和SummonFromZone共享，原三类条件及其查询主体保持；只有AV_100隔离适配，派发时来源保存费用捕为阈值、条件原执行窗读牌库，命中只招募一个原实体。无新模块、持久字段、效果、执行器、事件、动作或组合，新增一个四字段typed payload；见[随从费用比较契约](m3-current-deck-minion-cost-comparison.md)。引入时prototype-v239/core-effects-v233，schema215和观察/命令/回放保持。精确CN层/窗/空子集待校准，实际结果与下一项只在两份台账。


起始套牌费用奇偶由原两字段DeckCondition的starting/all_even_cost或all_odd_cost有限值声明，读取原MatchSetup/original_deck全部牌型固定印刷cost，0为偶数，所有定义完整查验；当前/保存费用及手牌外部报价不代替。原费用/派系主体、CheckDeckCondition/check/register与开局/费用/技能生命周期保持，无新模块、payload、持久字段、效果、执行器、事件、动作或组合。只有GIL_692隔离适配，显式HERO_POWER设1费并绑定原物理技能；见[起始费用奇偶契约](m3-starting-deck-cost-parity.md)。引入时prototype-v238/core-effects-v232，schema215及观察/命令/回放保持。原印刷费用/开局窗/技能形态政策待CN，实际结果与下一项只在两份台账。


起始套牌法术派系由冻结DeckSpellSchoolCondition(spell_school, scope=starting)声明，原MatchSetup/original_deck与SPELL子集事实明确；非施法牌排除、已知None法术失败、每条原定义完整查验，空子集全称真为待CN内部政策。原两类条件/分支执行器保持，PoolQuery、OpeningHook、ReplaceHeroPower及目标/Damage共享；只有SW_448与精确关联EX1_625t隔离适配。无新生产模块/模型字段/效果/执行器/动作/事件或组合，新冻结两字段payload注册；见[起始法术派系契约](m3-starting-deck-spell-schools.md)。引入时prototype-v237/core-effects-v231，schema215及原观察/命令/回放保持。精确CN空法术/开局窗未校准，实际结果与下一项只在两份台账。


当前牌库费用排除由冻结DeckCostCondition(cost, cost_basis, scope)声明，仅显式local/current和严格非负整数；原DeckCondition两字段及固定谓词保持，原CheckDeckCondition/check执行器共享。原local_cost及PoolQuery费用区间读每物理实体保存费用、完整查验定义后聚合，不要求无关metadata，未知仍拒绝，不借用手牌外部报价或消费用途。新三字段payload显式注册，无新模块、持久字段或执行器。必要ICC_853原4费4/4中立传说亡灵，只授原吸血/嘲讽；见[费用排除契约](m3-current-deck-cost-exclusion.md)。引入时prototype-v236/core-effects-v230，schema215原结构及拒旧1～214、观察74/命令11/replay1保持；费用依据与精确国服窗口待校准，实际执行及下一项只在两份台账。


当前空牌库只扩原DeckCondition的current/empty有限谓词，保留scope/predicate两字段，starting/empty拒绝。只查询指定玩家已验证的物理DECK列表是否为空，不依赖无关卡面metadata；无随从/无中立/无重复不能代替空。原其他谓词主体、所需metadata守卫、CheckDeckCondition类/check/register及帧/恢复/回放/事务共享；未知存档定义仍拒绝。无新模块/模型/状态/字段/执行器或组合。必要DAL_554原7费6/6中立传说无种族，按冻结正文六次原Summon，Token原6费6/6元素，见[结构条件契约](m3-current-deck-empty.md)。引入时prototype-v235/core-effects-v229，schema215布局及拒旧1～214、观察74/命令11/replay1保持；精确国服政策待校准，实际执行及下一项只在两份台账。


当前牌库无随从牌只扩原DeckCondition的current/no_minions有限谓词，保留scope/predicate两字段。按每物理实体当前CardDefinition.kind及原PoolQuery(kinds=(MINION,))完整遍历后聚合；空为真，非随从牌型不等于全法术。仅类型查询不要求无关职业metadata，未知定义仍明确拒绝；原无重复/无中立的所需元信息守卫保持。原CheckDeckCondition类/check/register、已选分支与解释器/恢复/回放/事务共享，无新模块/字段/执行器或组合。必要RLK_211原5费邪能法术和RLK_211t原3/3吸血恶魔只复用单次Summon先二再条件二，见[有限类型契约](m3-current-deck-no-minions.md)。引入时prototype-v234/core-effects-v228，schema215布局及拒旧1～214、观察74/命令11/replay1保持；精确国服政策待校准，实际执行及下一项只在两份台账。


当前牌库无中立牌只扩原DeckCondition的current/no_neutral有限谓词，保留scope/predicate两字段。按每物理实体当前卡面及原PoolQuery(include_neutral=False)/matches_metadata完整元信息遍历后聚合；重复/别名/其他职业不当中立，早先中立不掩盖后续unknown。原CheckDeckCondition类、check执行器和register完整保持，分支只在执行时选一次，后续改变牌库不反向改选；原帧/恢复/回放/事务/玩家共享，无新模块/状态/字段/执行器或组合。必要DMF_241完整8费7/5圣骑士传说德莱尼，只复用原四关键词授予，见[有限条件契约](m3-current-deck-no-neutral.md)。引入时prototype-v233/core-effects-v227，schema215布局及拒旧1～214、观察74/命令11/replay1和生产代表保持；国服精确政策待校准，实际执行及下一项只在两份台账。


本局历次本人回合实际承伤费用由hero_damage_taken_costs.py有限纯消费者表达，读取B76完整原DamageRecord和hero_damage_taken(own_turn_only=True)，不传当前turn而缩小为一回合。原目标/active_player/damage_dealt含护甲计量、完整所有行及原实体/顺序/伤害游标冻结；已接受根允许后续伤害但保持旧价。两个冻结类型、默认None卡牌声明及显式私有stage叶，原物理/生成报价、付款、typed帧和解释器共享，无新State/Player/Entity字段、伤害器、事件、动作或组合。只支持普通随从一个profile，其他公式合并拒绝；必要TTN_462完整9费4/4术士史诗无种族隔离声明，见[承伤费用契约](m3-hero-own-turns-damage-costs.md)。引入时prototype-v232/core-effects-v226/schema215拒旧1～214，观察74/命令11/replay1及生产代表保持；精确国服政策未校准，实际执行及下一项只在两份台账。


实际伤害历史由DamageRecord保存原完整HealthResult，GameState只加damage_history与next_damage_id；health_history.py共用两健康流的存储/物理目录/严格解析及一次边界事件遍历，原healing_history API和有限消费者保持。damage_records/hero_damage_taken/hero_power_damage只读原实际单位、目标归属/历次本人回合及直接技能原卡面来源，护甲与失血区分，系统FATIGUE无卡牌信用、未知正量来源拒绝。首次原事件捕获前整批提交，原数值/转换/吸血/检查点/生命周期/typed帧/回溯共享，无新伤害执行器/事件/动作或组合。仅BAR_547完整8费8/8法师传说亡灵隔离声明，另两raw仅证据，见[伤害历史契约](m3-damage-history.md)。引入时prototype-v231/core-effects-v225/schema214拒旧1～213，观察74/命令11/replay1及生产代表保持；直接/间接技能信用与精确国服政策仍待校准，实际执行及下一项只在两份台账。


hero_healed_this_turn在原IntrinsicCostSpec提供固定healing.hero-this-turn-v1条件，按报价玩家的原目标英雄/全局回合/正实际恢复判断；一HeroHealedTurnMatch冻结完整全部治疗前缀，进入原Stage.condition_facts有限类型。三个纯函数复用原B74查询，原before-local固有操作、物理/生成报价、付款、等待/恢复/回放及玩家边界共享，无新模块、State/Player/Entity/CardDefinition/Stage字段、执行器/Effect/事件/动作或组合。仅ICC_700完整3费3/3中立稀有亡灵隔离声明、CORE仅raw证据，见[本回合英雄被治疗费用契约](m3-hero-healed-turn-costs.md)。引入时prototype-v230/core-effects-v224/schema213拒旧1～212，观察74/命令11/replay1与生产代表保持；准确目标/窗口/转换/吸血/英雄更换与层序待CN，实际执行及下一项只在两份台账。


实际治疗事实由healing_history.py复用完整原HealthResult及原整批数值/吸血，首次原事件捕获前一次提交；HealingRecord冻结完整原包，State只有连续游标和历史。healing_records/restored_health/hero_was_healed严格纯查询分别表达原来源单位与目标英雄本回合正恢复，未知成功来源明确报错；零/受阻/转换和原生命周期/等待/恢复/回溯/玩家边界共享，无新治疗执行器/Effect/事件/动作或组合。仅必要DAL_799完整5费4/4德鲁伊史诗野兽、突袭及普通复制战吼隔离声明，见[实际治疗历史契约](m3-healing-history.md)。引入时prototype-v229/core-effects-v223/schema212拒旧1～211，观察74/命令11/replay1及生产代表64/合成3保持；归属、整批可见窗与精确国服规则待校准，实际执行及下一项只在两份台账维护。


套牌之外出牌费用复用原PlayerPlayedClassCostSpec/Fact与完整物理出牌根，有限profile读取OpeningState.original_entities及两方original_deck，按source_id与实际payer筛选。两nullable原身份操作数进入原冻结证明、严格字典及typed恢复；旧职业/turn要求两项None，Scenario未知物理来源明确报错。四个纯函数共享原开局/报价/付款/FrameCodec，无新生产模块、State/Player/Entity/开局/出牌/卡牌/阶段字段、执行器/Effect/事件/动作或组合。仅必要DRG_109完整8费8/8法师史诗元素隔离声明，见[原开局物理身份费用契约](m3-player-nonstarter-play-costs.md)。引入时prototype-v228/core-effects-v222/schema211拒旧1～210，观察74/命令11/replay1及生产代表64/合成3保持；物理变形/转移及精确国服窗口/来源/层序待校准，实际执行及下一项只在两份台账维护。


本局本人实际尸体单位费用由player_corpse_spend_costs.py直接读原B71完整corpse_spend_history及spent_corpses查询；固定/上限/CORPSES付款共享实际单位，零行/另一payer保留，退款不抹原量。两冻结费用类型、一默认None声明及显式player_corpses叶进入原报价/一次付款/字典和typed帧；原State/Player/Entity、CorpseSpendRecord、资源/上限/付款/FrameCodec源码保持，无新执行器/事件/动作或组合。仅必要RLK_744完整9费8/8邪恶符文亡灵隔离适配，见[本局实际尸体费用契约](m3-player-corpse-spend-costs.md)。引入时prototype-v227/core-effects-v221/schema210拒旧1～209，观察74/命令11/replay1及生产代表64/合成3保持；精确国服窗口/来源/费用顺序待校准，实际执行及下一项只在两份台账维护。


成功实际残骸消耗由原resources.py、resource_operations.py及PaymentPlan登记同一完整有序State前缀；CorpseSpendRecord保存实际单位/余额/时钟和实际具备的来源，上限复用原结果及operation_id，pending完成后历史保留。corpse_spends/spent_corpses只读状态；零成功保留零行、退款不抹原单位、增益/略过/失败不计量，原等待/回滚/回溯和终局共享。原付款纯投影同步账户与记录，私有完整事件包绑定有效原前缀，不向玩家导出；一冻结模型、一State字段和一内部付款标记，无新模块/资源执行器/Effect/事件/动作/真实适配或组合，见[成功残骸消耗契约](m3-corpse-spend-history.md)。引入时prototype-v226/core-effects-v220、schema209拒旧1～208，观察74/命令11/replay1及生产代表64/合成3保持。精确CN政策未校准；实际执行和下一项只在两份台账维护。


本回合本人使用牌数费用在原PlayerPlayedClassCostSpec增加有限cost.player-played-card-count-turn-v1，显式card_class=None；普通物理MINION沿原完整手牌出牌根按实际payer/已捕获全局turn筛选，旧整局指定职业profile保持。原played_cards、完整卡面/获取/付款收据、全部有序行/turn/action、原报价/支付/前缀/字典及typed帧共享；无新字段、模型类型、模块、事件/动作或执行器。原已付金额保留原turn，不在回合推进后重新定价；None只用于新全牌型profile，不默认成旧圣骑士。仅必要AV_134霜狼将领完整普通4费3/3中立稀有隔离适配，原TID_077声明种族对齐生产elemental、raw/pin保持，见[本回合出牌费用契约](m3-player-played-turn-costs.md)。引入时prototype-v225/core-effects-v219，schema208字段/布局保持及旧1～207拒绝；观察74/命令11/replay1、生产代表64/合成3保持。接受/反制/开局前根来源与费用层顺序待CN校准；实际验证及下一项只在两份台账维护。

不同本人已施放法术派系费用在原PlayerSpellCountCostSpec增加有限profile cost.player-distinct-spell-school-count-v1，普通物理SPELL沿原hand/payload接受资格按非空原印刷派系去重；旧普通MINION次数profile及counts_for保持。原冻结价格行增加spell_school，原注册卡面逐行核对，包括未计入行；无第二历史、State/Player/Entity/CardDefinition新字段、模型类型、模块、Effect/事件/动作或执行器。同一原报价/付款/完整前缀/字典及typed帧恢复共享，仅必要TTN_085诺甘农的智慧完整Draw(2)隔离适配，见[不同派系费用契约](m3-player-spell-school-costs.md)。引入时prototype-v224/core-effects-v218/schema208，拒旧1～207，观察74/命令11/replay1及生产代表64/合成3保持；本人归属、未结接受窗、费用层顺序及准确国服规则仍待校准，不能仅凭卡文外推全自动来源。实际验证及下一项只在两份台账维护。

previous_owner_turn_elemental在原IntrinsicCostSpec提供固定MINION/elemental最近已关闭本人区间条件，旧previous_owner_turn_type继续按本牌种族/学派；原完整true/false关系、报价与一次付款共享。保留证明按已冻结selected.query.kind核对提交行，支持法术查询随从；同条件操作原序保留，不开放混合条件或另一数量公式。有限查询及CS2_118/WW_025必要声明对齐生产race18的小写elemental，未改全局匹配或raw/pin。没有新模块、模型类型、字段、Effect/事件/动作或执行器，仅必要TRL_313完整普通伤害/费用隔离适配，见[上回合元素费用契约](m3-previous-owner-elemental-costs.md)。引入时prototype-v223/core-effects-v217，schema207布局与旧1～206拒绝保持，观察74/命令11/replay1及生产代表64/合成3保持；实际验证及下一项只在两份台账维护。

连续本人回合元素数量费用由player_elemental_streak_costs.py读取原完整owner/play前缀，复用原历史守卫、完整类型收集器、区间进展检查和通用物理卡面行；无新回合/出牌/付款执行器、State字段或可变连续缓存。固定原印刷ELEMENTAL、实际payer、每本人区间一次；开放空区间暂延续、关闭空区间断段、本牌提交前报价为待CN校准的有限政策。两冻结费用类型、一个默认None声明和显式player_elemental_streak叶沿原报价/一次付款/字典及typed帧；旧bool与其他数量费用保持，仅必要WW_025隔离适配并复用CS2_118，见[连续元素数量费用契约](m3-player-elemental-streak-costs.md)。引入时prototype-v222/core-effects-v216/schema207拒旧1～206，观察74/命令11/replay1及生产代表64/合成3保持；实际执行和下一项只在两份台账维护。

query_owner_turn_history在原owner_turns.py纯读取完整本人区间/冻结提交卡面，保留全部true/false、空/current/pending/interrupted区间及outside原提交；共用完整提取的原守卫与种族/单学派匹配，旧最近closed查询及其unknown范围保持。两冻结只读值不进入State、专用codec字段或玩家接口；沿原frozen模型自动类型集合，无显式注册，无新模块/字段、时钟/连续缓存、执行器或组合；需要连续数量的费用消费者另审原窗口与完整前缀。仅必要CS2_118隔离声明，见[完整本人回合类型关系契约](m3-owner-turn-type-history.md)。prototype-v221/core-effects-v215/schema206及观察74/命令11/replay1、生产代表64/合成3保持，无协议迁移；执行与下一项只在两份台账维护。

成功召唤图腾数量费用由player_summon_count_costs.py消费原完整successful_summon_history，选择复用原_matching_rows、当前成功时种族及实际payer；同一完整有序前缀/选择/数量/分配/时钟进入原固有报价和一次付款。原窗口完整重取，紧凑精确前缀允许后续追加而不认证未签名原来源；无新State字段、召唤/支付执行器或组合。两冻结费用类型、一个默认None声明及显式player_summons叶进入原严格字典和typed帧，仅必要OG_028隔离适配，见[有限成功图腾费用契约](m3-player-summon-count-costs.md)。prototype-v221/core-effects-v215/schema206拒旧1～205，观察74/命令11/replay1及生产代表64/合成3保持；执行与下一项只在两份台账。

成功随从召唤由successful_summons.py在原minion_summoned发布时统一记录，普通出牌及现有效果入口共享；一冻结记录保存原分配/玩家/事件和印刷/当前种族，两私有State字段进入原严格保存/恢复/回放。summoned_minions/summon_count只读原历史，未知种族过滤明确报错；无新召唤执行器/Effect/事件/卡牌或组合机制，原玩家视图不接收私有台账，见[成功召唤历史契约](m3-successful-summon-history.md)。引入时prototype-v220/core-effects-v214/schema205拒旧1～204，观察74/命令11/replay1及生产代表64/合成3保持；实际执行和下一项只在两份台账维护。

英雄生命阈值费用引入时只扩展hero_missing_health_costs.py与原HeroMissingHealthCostSpec/Fact的有限profile：本人当前health≤15固定减5，原缺失生命差值默认保持；最大生命/护甲/历史伤害不替代当前值。完整原英雄身份与max_health/health继续进入原报价/付款/严格字典和typed读取，原窗口整份重查、紧凑保留英雄允许后续生命/替换而不认证未签名来源。必要AV_141t冰雪之王洛克霍拉完整raw/pin，原突袭/风怒、生命周期、选择和回放共享，见[英雄生命费用契约](m3-hero-missing-health-costs.md)。prototype-v219/core-effects-v213，schema204布局与拒旧1～203保持，观察74/命令11/replay1及生产代表64/合成3保持；无新模块/类型/字段/执行器，实际执行和下一项只在两份台账维护。

本人当前英雄护甲费用由player_armor_costs.py纯消费原hero_id、Entity.armor和完整原分配payload；线性减费与无甲0费两个真实有限profile共享同一护甲事实，不以生命或历史增甲替代。原窗口整份重查，紧凑分配允许后续合法护甲/英雄变化而不认证未签名来源。两冻结类型、一默认None卡牌声明和显式player_armor叶进入原费用/付款/保存，无新护甲、生命、群伤、状态、事件或执行器。必要AV_108裂盾一击/TOY_907安全护目镜完整raw/pin，原DamageBatch(5)/GainArmor(6)复用，见[当前护甲费用契约](m3-player-armor-costs.md)。prototype-v218/core-effects-v212/schema204拒旧1～203，观察74/命令11/replay1及生产代表64/合成3保持；实际执行和下一项只在两份台账维护。

本人当前武器攻击力减费由player_weapon_attack_costs.py纯消费原equipped_weapon、Entity.attack和完整原分配payload；英雄总攻击/印刷攻击不替代，原破损或doomed槽保留身份而计0。原接受窗重取整份事实，紧凑分配允许后续合法变化而不认证未签名来源。两冻结类型、一默认None声明和显式weapon_attack叶进入原费用/付款/保存，不新增装备、战斗、状态、事件或执行器。必要NEW1_022完整raw/pin、CORE原行仅证据，见[装备攻击力费用契约](m3-player-weapon-attack-costs.md)。prototype-v217/core-effects-v211/schema203拒旧1～202，观察74/命令11/replay1及生产代表64/合成3保持；实际执行和下一项只在两份台账维护。

本回合抽牌减费只扩展player_draw_count_costs.py的原有限profile与普通Spell入口，原DrawRecord/drawn_cards按实际payer及当前全局turn筛选，此前回合/对手/疲劳完整保留但不计量；旧接受根仍用原turn和数量，新报价重新筛选。原本局profile、完整事实、数量公式、报价/付款/phase证明/保存/恢复复用，无新模块/字段/账本或执行器。必要TTN_841只返回原临时英雄攻击Buff，见[抽牌费用契约](m3-player-draw-count-costs.md)。prototype-v216/core-effects-v210，schema202布局及拒旧1～201保持，观察74/命令11/replay1和生产代表64/合成3保持；实际执行和下一项只在两份台账维护。


本局本人实际抽牌费用由player_draw_count_costs.py复用原draw_history/drawn_cards，完整原DrawRecord/选择/金额进入共享固有报价；原窗口重查全部字段，紧凑历史允许合法phase和原cast/replacement链接推进，不认证未签名来源。两冻结类型、一个默认None声明和显式player_draws叶，无新State/Entity/Player字段、抽牌账本/缓存或执行器；必要TOY_530见[抽牌数量费用契约](m3-player-draw-count-costs.md)。prototype-v215/core-effects-v209/schema202，观察74/命令11/replay1及代表64/合成3保持，实际执行和下一项只在两份台账登记。


普通随从与法术共用minion_death_costs.py的原两类有限死亡数量输入，普通Spell入口只扩大原声明类型门槛。实际死亡、完整原记录/选择/金额、费用与一次付款、原Draw(2)、选择恢复和回放均复用，无新模块、公式、状态/卡牌/阶段字段或执行器；必要BRM_001见[死亡数量费用契约](m3-minion-death-costs.md)。prototype-v214/core-effects-v208，保存布局schema201不变，观察74/命令11/replay1及代表64/合成3保持；具体执行及下一项只在两份台账登记。


本人回合生命变化费用由hero_health_change_costs.py消费原不可变事实及纯数量，完整前缀/金额进入共享固有层。单一默认None卡牌声明及显式阶段叶保留原物理/生成/付款/历史/恢复/玩家管线，无新State/Entity/Player字段、生命或费用执行器、事件/动作或计数缓存；必要SCH_140见[费用契约](m3-hero-health-change-costs.md)。prototype-v214/core-effects-v208/schema201，观察74/命令11/replay1及生产代表64/合成3保持；实际执行和下一项只见两份台账。

实际英雄生命变化由单一不可变事实及hero_health_history.py纯数量记录，原数值/支付/英雄/本人区间继续共享。GameState只有完整历史/游标两个字段，无新生命执行器/事件类型/卡牌字段或Player累计缓存；原同批捕获、回溯有效时间线、负上限终局、保存与私有信息沿原机制，见[基础契约](m3-hero-health-changes.md)。prototype-v212/core-effects-v206/schema200，观察74/命令11/replay1保持；该B56事实基础的现行费用消费者见[费用契约](m3-hero-health-change-costs.md)，实际执行及下一项只见两份台账。

原生牌库自身监听只在原HandProgressSpec增默认HAND的zone，DECK限定普通随从单事件完成回调；原候选/AdvanceHandProgress/移区更新能力ID及SummonStoredCard共享，无新模块/状态/候选字段/执行器。原手牌顺序保持，牌库来源及旧候选受原ID/实际驻留检查；DECK内部计数不投影玩家进度。必要CFM_637及准确CN/后置来源边界见[基础契约](m3-deck-self-listeners.md)，prototype-v211/core-effects-v205/schema199，观察74/命令11/replay1保持；实际执行及下一项只见两份台账。

最高/最低费用弃牌只扩展原DiscardMatching.selection的两个值，复用原物理候选、纯quote_unselected_cost.amount、同值物理抽选及DiscardCard；不支付/消费用途，空/唯一极值不消耗RNG，旧random/first与逐次反应后重查保持。没有新模块、字段或执行器。必要BT_301/TRL_551和准确CN/多张来源边界见[基础契约](m3-extreme-cost-discard.md)，prototype-v210/core-effects-v204/schema198，观察74/命令11/replay1保持；实际执行及下一项只见两份台账。

成功弃牌的独立复制由原CopyEntryMaterial.discard_copy/DiscardRecord和原CopyCard扩展表达：原接受上下文一次冻结局部材料，多个交付共享材料且分配独立实体/附魔/获取，旧手牌期限清理；原CopyCard/附件/材料应用/容量/帧和解释器复用，没有新模块/状态/执行器。新profile只支持原受影响玩家current手牌追加，不能借作普通召唤；原HAND/DECK复制保持。必要TRL_252及国服政策边界见[复制材料契约](m3-discard-copy-materials.md)，prototype-v209/core-effects-v203/schema197，观察74/命令11/replay1保持；实际执行及下一项只见两份台账。

普通成功弃牌材料由原DiscardRecord绑定，在既有BuffStoredCard/ReturnToHand.discard使用原墓地实体/epoch；原数值附魔、保留物理移区、新手牌获取、帧和解释器共享。旧获取期限清除，普通战场回手仍重置；原材料满手失败用新epoch终结，没有新模块/状态/执行器。原材料只接受普通数值成长及原受影响玩家回手，不开放任意墓地CardReference或复制。必要UNG_836及精确CN边界见[原材料契约](m3-retained-discard-return.md)，prototype-v208/core-effects-v202/schema196，观察74/命令11/replay1保持；实际执行及下一项只见两份台账。

自身被弃后的印刷新本体召唤已由原on_discard/DiscardRecord及Summon/入场表达，无新内核、模块、协议或状态。必要KAR_205新本体3/4使用独立实体/原印刷安装，原弃牌实体和事实保留；原满场、召唤限制/死亡/选择/恢复/事务及玩家共享。该新本体政策不泛化到原材料保留/回手/复制，精确CN待校准。见[原能力契约](m3-discard-summon.md)，prototype-v207/core-effects-v201/schema195、观察74/命令11/replay1保持。

原生本牌被弃主体由CardDefinition.on_discard/原印刷附件声明，成功弃牌后捕获原DiscardRecord及RuleContext.discard，交原BehaviorCall/解释器/帧；source为本牌，player为弃牌时控制者，无额外play/cast。原监听及手牌工作后追加为本地政策，on_select新上下文不自动继承discard；生命周期/恢复/replay/玩家共享，无新模块、状态计数、事件、动作或授予。仅BT_300必要Draw(3)，材料/批次/完整U59/CN开放。见[公共契约](m3-own-discard-bodies.md)。当前prototype-v207/core-effects-v201/schema195拒旧1～194，观察74/命令11/replay1保持。

按本局成功弃牌数量持续自身加攻仅扩展原StatRelationOperand/CONDITIONAL_ATTACK正系数声明，读当前controller原discarded_cards，写原conditional_attack派生整数。原弃牌提交后、监听捕获前纯刷新，数值/活动资格/生命周期/捕获域/恢复/replay与玩家共享；无新模块、执行器或字段，新的条件授予继续拒绝。仅ICC_841必要原生实验，精确CN/完整U59开放。见[公共契约](m3-discard-count-attack.md)。当前prototype-v206/core-effects-v200/schema194拒旧1～193，观察74/命令11/replay1保持。

本局成功物理弃牌沿原HAND到GRAVEYARD管线，在实际原事件确定后、监听捕获前提交不可变DiscardRecord，复用原卡/原因SourceAllocationFact及获取身份。GameState只加discard_history/next_discard_id，纯discarded_cards查询不推进对局；原事件、检查点、选择、随机、恢复/replay/玩家隔离共用，没有新弃牌执行器。无真实卡适配，连续加攻/返还材料和精确CN开放。见[公共契约](m3-discard-history.md)。当前prototype-v205/core-effects-v199/schema193拒旧1～192，观察74/命令11/replay1保持。

玩家整局种族突袭由原PlayerEffectSpec默认空keyword_auras及不可变PlayerKeywordAuraSpec声明，原实例/当前种族/连续关键词并集、突袭攻击、生命周期/恢复/replay及玩家公开效果共享。只支持persistent/tribal/RUSH，没有新模块/执行器/状态字段；必要BOT_238只接隔离战吼、夹具原技能，五种动力装置/CN/完整族开放。见[公共契约](m4-player-keyword-auras.md)。当前prototype-v204/core-effects-v198/schema192拒旧1～191，观察74/命令11/replay1保持。



卡牌行为描述“要做什么”，底层处理器负责“怎样修改状态”，规则策略负责“何时及按什么顺序结算”。大多数新增卡牌只需要第一层。



本文解释主工程 `prototype-v207` 的开发API；实际执行与阶段整体验收以[项目状态](project-status.md)为准。开发顺序与阶段验收参照 [长期实施计划](roadmap.md)，完成后同步更新 [项目状态](project-status.md)。附件保留/重置和复生的详细语义见 [M1 生命周期契约](m1-lifecycle.md)。

原生光环的当前卡牌身份筛选复用原玩家属性ID匹配；AuraSpec/KeywordAuraSpec默认空card_ids、原扁平附件aura_card_ids，仅原生普通战场声明，原数值/关键词和生命周期/JSON/完整帧/恢复/玩家隔离共享；未知/非随从ID冻结前报错，非空授予后置。无新模块/执行器/缓存。见[基础契约](m2-card-identity-auras.md)。当前prototype-v203/core-effects-v197/schema191拒旧1～190，观察74/命令11/replay1保持；完整身份/别名及精确CN开放。

原生顺劈由CardDefinition.cleave默认False声明及纯本体附件提供；当前原生随从或当前有效装备武器决定最终受击随从左右相邻包，同批原DamageBatch与一次CombatExchange保持主目标反击/次数/磨损，完整有序额外包严格校验；无新伤害执行器或英雄缓存。沉默/复制/转控、等待恢复/事务/回放/玩家隔离沿原管线。见[基础契约](m2-cleave-combat.md)。当前prototype-v202/core-effects-v196/schema190拒旧1～189，观察74/命令11/replay1保持；授予/复合及精确CN后置。

随机改打错误敌人的必要食人魔步兵表达复用原RequestChoice的sample_size/零项自动on_select，刷新实际窗口、抽等权keep/redirect，再抽当前错误敌人并调用原RedirectAttack；原攻击机会/战斗/生命周期/恢复/事务和玩家隔离保持。内部choice_skipped/计数沿旧接口，不请求玩家选择；没有新增随机/攻击执行器、模块、Effect或状态字段。见[独立表达契约](m2-wrong-enemy-attacks.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确CN资格/空池/内部计数/反应时序与其他来源开放。

随机强制攻击只修原RandomForceAttack角色受击范围：攻击者仍限随从，受击允许当前存活英雄，原结构关系、有序一配对一权重/一次RNG和ForceAttack及动作窗/战斗保持。等待已选引用恢复、英雄替换取消、正常次数、事务和玩家信息共享，无新Effect/状态/声明/模块/事件/动作。见[基础契约](m2-random-forced-attacks.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；仅钢鬃掠夺者隔离适配，英雄资格/随机/强制/原暴怒时序待CN，U44整族开放。

学派限定法伤在原CardDefinition/AbilityInstance末尾各加默认空spell_damage_schools，正数原生普通随从提供；纯spell_damage_sources同时支持原普通包与原随机分配预算，按当前/捕获学派匹配，None只通用，省略参数保留聚合标量。原批次/预算/原贡献证明和生命周期/等待/恢复/信息共享，无新伤害执行器、缓存、事件或动作。见[基础契约](m2-school-spell-damage.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确学派/预算/通用查询待CN，动态/存储授予及其他来源后置。

本回合临时控制在原ChangeControl新增until_end_of_turn/source_id默认参数，纯Enchantment.control_return_player_id保存实际前一控制者。共享原物理转控与到期/沉默/移除撤销，变形/跨区取消，当前复制不带物理归还；原结束反应/等待/死亡/信息共享。无新机制模块、时钟、事件或动作。见[基础契约](m2-temporary-control.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；准确冲锋/沉默/变形/结束/满场归还待CN，休眠满场死亡和重叠临时来源明确不支持。

指定当前种族的持续费用光环由原CostAuraSpec默认空tribes_any声明，仅印刷普通友方随从纯负数减费；CostSpec/空范围GrantCostAura保持，非空授予拒绝。原CostQuoteInput完整附魔重算当时当前种族，生成用新卡初始身份；matches_cost_contribution由原报价和紧凑物理/生成验证共享，来源/付款关系/有序层/零费/有限用途/原付款冻结沿原管线。原生完整卡面/数量校验覆盖当前/死亡/捕获域，无新报价器/状态或缓存。见[基础契约](m2-tribal-cost-aura.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确种族/来源/支付窗待CN，U23整族未完成。

指定当前种族的持续属性光环在原AuraSpec加入默认空tribes_any，扁平能力以aura_tribes_any重建声明；仅印刷普通非融合场上always/非相邻，原GrantAura不扩展。原同时属性层以has_any_tribe/current筛选，旧已结算生命来源选择、生命撤销钳制、死亡/生命期/战斗/等待/恢复/玩家共享，无新数值执行器或派生缓存。见[基础契约](m2-tribal-stat-aura.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；准确受益身份/健康/来源/死亡/攻击窗待CN，U23整族未完成。

指定当前种族的持续冲锋光环在原KeywordAuraSpec加入默认空tribes_any，只开放必要原生普通场上CHARGE/always/非相邻。has_any_tribe/current共享双种族/all排除与未知报错；原外部aura_keywords并集、生命期/死亡/攻击次数/接受/等待/事务/恢复/玩家共享，无新冲锋执行器或状态字段，不扩展可选授予。见[基础契约](m2-tribal-keyword-aura.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；准确受益依据/来源/死亡/攻击窗待CN，U23整族未完成。

独立武器存在条件自身攻击扩展原StatRelationSpec的CONTROLLER_HAS_WEAPON/CONDITIONAL_ATTACK/正量，装备条件复用equipped_weapon。Entity.conditional_attack为原状态依赖的自身派生整数，原数值和外部光环后加条件、再零下限；本地受伤量与最终自身生命层保持。原事件规范化及健康钳制后刷新、model/FrameCodec原捕获域校验，原战斗/接受/磨损/生命周期/恢复/玩家共享；新条件授予仍拒绝，无新GameState/Player字段、事件、动作或执行器。见[基础契约](m2-weapon-presence-attack.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确数值/装备/事件/死亡/接受/准备/显示待CN，U22整族未完成。

独立武器存在条件冲锋扩展原KeywordAuraSpec的self/controller_has_weapon/CHARGE，仅普通印刷非融合本体；equipped_weapon共享原当前槽耐久/销毁谓词，零攻击武器仍满足。Entity.conditional_keywords单独保存GameState依赖的自身派生贡献，原本体/永久/外部同名并集保持，事件前及时规范化，model/FrameCodec在原捕获状态域校验。原冲锋/召唤限制/攻击次数/接受及生命周期共享，未新增GameState/Player字段、事件、动作或条件授予；见[基础契约](m2-weapon-presence-keyword.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确存在/事件/死亡/接受/显示待CN，U22整族未完成。

独立受伤来源对当前武器的持续攻击扩展原AuraSpec默认friendly_minions/always与有限friendly_weapon/self_damaged形状，仅印刷普通非融合来源，原扁平附件保存范围/条件。stat_auras.py重算当前控制者武器的aura_attack，原生命钳制后和事件前分别规范化，不创建永久增益；原装备回合贡献、死亡、磨损、准备战斗、恢复/replay和玩家视图共享。本武器攻击profile的条件授予及其他条件明确不支持，本项无新GameState/Entity/Player字段、事件或动作；见[基础契约](m2-self-damaged-weapon-aura.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；精确来源/健康/事件/死亡/战斗窗口与层序待CN，U22整族未完成。

独立受伤持续风怒扩展原KeywordAuraSpec：默认condition=always保持旧外部/手牌光环；self/self_damaged/WINDFURY仅印刷普通非融合本体，原关键词并集合并，条件消失保留其他来源。事件前只规范化本体条件，原伤害/治疗回调与waiting上下文及时更新；原最大攻击次数和已消费次数共享，不反复授予或重置次数，原准备战斗/生命周期/恢复/replay/玩家合法攻击保持。受伤profile仅支持风怒，其他已知条件见各独立契约；新条件授予明确拒绝，本受伤profile未加状态字段、计数器、事件或动作；见[基础契约](m2-self-damaged-keyword.md)。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持；准确关键词/攻击接受窗、健康与非活动显示待CN，U22整族未完成。

独立受伤持续加攻扩展原StatRelationSpec/typed附件与stats.py纯查询：SELF_DAMAGED/CONDITIONAL_ATTACK/正整数amount，按既有健康结果在原数值和光环后、零下限前计算，不改基础攻击、伤害或永久附魔。连续受伤不叠加、满血撤销，原已准备战斗和死亡冻结保持；原FINAL_ATTACK自身生命等式只约束自身生命关系。仅印刷普通非融合随从；新条件可选授予明确拒绝，原生命周期/恢复/replay/玩家当前攻击共享。没有新状态字段、事件、动作或任意表达式图；默认空关系完整指纹保持，关系amount改变其附件格式。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m2-self-damaged-attack.md)，条件层序/健康钳制/准确窗口/非活动显示待CN，其他条件关键词/其他条件/特殊来源及U22整族仍开放。

独立本局原职业出牌数量由play_history.py的played_cards单一card_class筛选和纯matches_played_class复用原完整FrozenPlayedFaceFact，用既有PoolQuery/matches_metadata明确排除中立，不以当前英雄或变形重判。player_played_class_costs.py仅单一可玩印刷职业的普通随从减费、最低零，完整原卡面/获取/窗口/有序游标/物理上界与selected冻结到player_played_class，原付款/恢复/replay/玩家价格共享，后来出牌不重价。原反制/未结手牌根计入本地profile，自动施法/召唤/技能不添根，新付款前自身不计入；精确CN时点/退款待校准。没有新GameState/Entity/Player字段、事件、动作、出牌台账或递归原报价；默认player_played_class_cost=None及显式数量叶改变指纹/保存格式。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-player-played-class-costs.md)，费用层顺序/特殊来源/正式卡面与CN仍开放。

独立本局实际过载水晶量由overload_history.py在原overload_added发布处保存不可变OverloadRecord，只累加实际正量；初始余额/转锁/解锁/0量不增加，纯overloaded_crystals查询不改变账户。原玩家/owner回合/动作及mana_changed事件对和完整目录校验，玩家与pending两端严格int，拒绝数值相等的布尔/浮点冒充。player_overload_costs.py仅普通随从的cost.player-overload-v1，以实际payer本局水晶量减费、最低零；完整原记录/窗口/游标/分配与数量冻结进入player_overload，共享报价/付款/恢复/回放/玩家价格，后来真实过载不改原付款。GameState仅新增overload_history及next_overload_id两个字段；没有Player累计缓存、第二套法力执行器、新Entity/Player字段、玩法事件或外部动作。默认player_overload_cost=None及显式原量叶改变指纹/保存格式。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-player-overload-costs.md)，精确发布窗/费用层顺序/特殊来源与CN仍开放。

独立死亡随从次数费用由普通随从或法术通过minion_death_costs.py复用完整原DeathRecord及DeathQuery，仅友方本局/双方本回合两个profile，每原死亡记录减一费、最低零。controller取死亡时归属；武器/地标销毁保留完整前缀但不计随从量，不按实体或卡牌ID去重。完整原turn/记录/selected/游标/分配上界和数量冻结进入minion_deaths，原付款/恢复/回放/玩家报价共享，后来死亡或回合推进不重价；序列化复用原_death_from_dict，不另造死亡结算/记录器。默认minion_death_cost=None及显式minion_deaths改变指纹/保存格式，无新Entity/Player字段、事件或动作。现行prototype-v214/core-effects-v208/schema201仍拒旧1～200；普通法术入口不改变保存布局，观察74/命令11/replay1保持。见[基础契约](m3-minion-death-costs.md)，精确死亡可见窗/层顺序/特殊复制及CN仍开放。

独立本局法术法力费用由player_spell_mana_costs.py复用原PlayRecord和submitted_cost，按实际payer原SPELL/MANA物理付款根的真实法力消耗减费、最低零。获取前/跨回合/临时法力保留；替代账户及无付款自动施法不增加，反制/未结付款计入本地profile，精确CN待校准。完整原类型/账户/法力两端/获取/有序前缀/分配上界和数量冻结进入player_spell_mana，共享报价/付款/恢复/回放/玩家费用，后续恢复法力或新增付款不重写原报价；不递归报价或另造计数器。默认player_spell_mana_cost=None及显式player_spell_mana改变指纹/保存格式。无新Entity/Player字段、事件或动作。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-player-spell-mana-costs.md)，特殊归属/层顺序/特殊复制/CN及整族仍开放。

独立本人本局技能次数费用由player_hero_power_count_costs.py复用原hero_power_history，按实际payer原manual接受根每次减一费、最低零。获取前/此前回合/旧技能使用保留，effect及自动失败不加手动量，完成/中断可正常推进。原完整行/游标/支付身份/分配上界和数量冻结进入player_hero_powers，共享报价/付款/恢复/回放/玩家价格，不按今天历史重新定价。默认player_hero_power_count_cost=None及显式player_hero_powers改变指纹/保存格式，无新Entity/Player字段、事件或动作。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-player-hero-power-count-costs.md)，未结窗/效果归属/层顺序/特殊复制/CN仍开放。

独立本人本局施法数量费用由player_spell_count_costs.py复用原cast_history，按实际payer的原hand已接受主体根每次减一费、最低零。反制及repeat/effect/draw/history不加本人原根数量，获取前历史计入；精确未结窗和重复归属待CN校准。PlayerSpellCountCostFact冻结完整有序原施法行、游标、分配上界及数量金额，进入原固有报价/付款/恢复/回放/玩家价格；紧凑历史允许原自动主体合法推进，保持原身份和冻结数量，不以今天历史重新定价。默认player_spell_count_cost=None与显式player_spells改变指纹/保存格式，无新Entity/Player字段、事件或动作。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-player-spell-count-costs.md)，层顺序/特殊复制与CN仍开放。

独立英雄缺失生命费用由hero_missing_health_costs.py提供当前payer英雄max_health-health每点减一费、最低零的纯操作数。复用原生命/上限政策及英雄替换，物理与生成报价一致；HeroMissingHealthCostFact冻结原英雄身份、归属、分配上界、健康数量与金额。原付款/恢复/回放/玩家价格共享，紧凑历史绑定保留原英雄身份并按旧数量重算，不从今天的健康重新定价。默认hero_missing_health_cost=None和显式hero_missing_health改变指纹/保存格式，无新Entity/Player字段、事件或动作。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-hero-missing-health-costs.md)，费用顺序/特殊复制/精确CN待校准。

独立手牌数量费用由hand_count_costs.py提供friendly_other/enemy每张减一费、最低零的纯操作数。物理quote_input明确source_id，生成保持None并按额外新牌假设；同名不替代物理身份。HandCountCostFact保存双方有序HAND物理ID、原分配上界/来源及数量/金额，进入原固有阶段；原真实提交必须含本人HAND来源，已接受费用不随后续获取改写。共享报价/付款/恢复/回放/玩家价格，不保存对手卡面或写费用缓存。默认hand_count_cost=None及显式hand_cards改变指纹/保存格式；引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-hand-count-costs.md)，生成假设/费用顺序和特殊来源待CN。

独立场面数量费用由board_minion_costs.py提供有限friendly/all每个减一费、最低零的纯操作数；原base之后、原条件/本地/外部层之前进入共享intrinsic报价。完整双方BOARD目录、原分配上界和数量/金额保存到BoardMinionCostFact；原手牌付款先冻结，物理来源不能借未来上界或计入尚未入场的自身。真实选择恢复、历史校验、玩家价格/枚举沿原管线，不写实体费用缓存。所有定义新增默认None声明、固有阶段显式board_minions导致指纹与schema变化；无新Entity/Player字段、事件或外部动作。引入时prototype-v201/core-effects-v195/schema189拒旧1～188，观察74/命令11/replay1保持。见[基础契约](m3-board-minion-costs.md)，休眠/将死驻留与费用顺序待CN，其他真实公式继续开放。

原生模块化构筑由modular_decks.py保存有限蓝图/功能模板/完整两个模块与外观选择，只编译实际请求的完整普通印刷随从；原主卡格式资格与共享传说身份组保持。双方配置独立，原实体/开局/复制/沉默/复活及私有信息复用，无新效果或保存字段；未知模块明确拒绝，注册表指纹绑定选择和卡面。当前规则201/效果195/schema189，观察74/命令11保持。见[基础契约](m3-modular-deck-basics.md)，完整主体/池/导入/CN开放。

独立奇闻由fabled_decks.py声明有限主卡/伴生构筑身份，宿主expand_fabled_cards可显式展开，DeckSpec仍传完整物理原卡组；普通30槽内含伴生；奇闻强化版复用容量声明40张/九伴生，沿原实体/洗牌/换牌执行。只有完整本职业合法原组豁免不可收藏及成员空稀有度，成员身份组仍最多一份，原禁限/数量/符文保持，侧板及异职业特殊来源后置。原构筑身份固定，声明进入指纹；无新效果、状态或保存字段。规则201/效果195/schema189，观察74/命令11保持，见[基础契约](m3-fabled-basics.md)，精确CN及整族仍开放。

独立卡组容量由deck_size_rules.py按每副原主卡的单一合法来源校验，不改双方共用格式默认值；禁限/原职业/数量/符文保持。初始生命复用原OpeningHook与SetStats，没有新状态/效果格式或第二套开局。声明进入指纹，原构筑身份固定；多来源优先级明确拒绝，组合后置。当前规则201/效果195/schema189，观察74/命令11保持，详见[基础契约](m3-deck-size-basics.md)。

独立虚空由void_decks.py保存玩家私有VoidCard原牌驻留，SendDeckToVoid随机留一，GetFromVoid逐次消费原牌并复用普通区域/获取/满手烧牌。本人开始收益复用整局玩家效果，普通自然抽牌保持；没有新的玩家字段或命令。当前规则201/效果195/schema189，私有历史校验成员但不认证历史随机来源，精确国服政策仍待校准。见[基础契约](m3-void-deck-basics.md)。

独立游客由tourists.py按原始主卡组中的单一本职业来源开放有限审核目的地池；原印刷职业、普通禁限/数量/生成过滤保持，DK目的地复用原符文。声明进入指纹，原构筑身份固定，无新状态/效果格式。见[基础契约](m3-tourist-basics.md)，当前不开发组合机制。

法术石基础复用`HandProgressSpec(amount_basis='event_amount', upgrade_cost_policy='clear_local')`。每实际事件只完成当前阶段，单位收据与原见证一起保存；默认单位计数和普通升级保留费用不变。没有新增法术石模块，详见[基础契约](m3-spellstone-progress.md)。

实际Overload正增量发布overload_added，复用event_amount进度；mana_changed仍是可用法力变化。初始化、转锁和解锁不产生新增事实，详见[过载契约](m3-overload-facts.md)。

阴谋回合成长复用repeat手牌进度，圣契持续减费复用玩家AddCostModifier与明确类别ID；没有新增模块或快照字段。两项分别表达，详见[独立基础契约](m3-scheme-libram-basics.md)。

共同spell_cast_accepted内部事实覆盖各物理来源，普通手牌进度按cast ID去重/升级；失败尝试和被回溯撤销的旧日志分别处理，详见[基础契约](m3-spell-cast-progress.md)。

治疗实际量、尸体实际获得和原英雄攻击声明已分别证明复用事件/普通手牌进度，未新增内核模块或字段；资格与待校准政策见[独立契约](m3-spellstone-qualifications.md)。

紫水晶的原伤害来源资格复用HealthResult及普通单位进度，来源后续转控不改写原归属，见[冻结来源契约](m3-amethyst-qualification.md)。未新增内核模块、事件或字段。

出牌与装备资格复用completed原PlayRecord和weapon_equipped，分别排除召唤、自动安装与死亡，见[独立资格契约](m3-spellstone-play-equipment.md)。红宝石完整主体需正式池，隔离适配明确报错；未新增内核模块、事件或字段。

等级法术由独立mana_ranks模块按最大水晶5/10同步手牌/牌库及新获取，复用upgrade_face；可选静态族/政策版本进入注册表指纹，未声明时既有规则与指纹保持，见[阈值契约](m3-mana-ranks.md)。未增加实体字段、事件或schema。

未鉴定由独立unidentified模块在实际手牌材料完成后固定抽选四结果，当前形态保存身份；可选族/政策版本进入注册表指纹，复用随机、区域和换面，无新字段/事件/schema。换牌与复制等精确政策待M6，见[身份契约](m3-unidentified-basics.md)。

谐振/失谐两个形态互为HandProgressSpec下一阶段，复用原连续身份/见证与换面，表达本人结束的独立持牌轮换；无新模块/事件/字段/schema。精确国服窗口待M6，见[轮换契约](m3-harmonic-basics.md)。

饮料有限使用复用三个印刷余次形态与成功主体尾部AddToHand；每次单独支付，新后继不复制前杯本地费用，末杯无后继。无新关键词/模块/字段/schema，精确国服窗口待M6，见[续杯契约](m3-drink-refill-basics.md)。

地图原发现选项与当回合实际收牌的物理身份由hand_choice_followups.py私下保存；普通池、选择、区域和出牌管线继续复用，奖励只选择原未选项，不重抽候选。严格恢复与本人最小投影见[跨动作发现跟随](m3-hand-choice-followups.md)，精确窗口及完整池仍待M6/M0。

下一张德莱尼的一次增益与两次复制复用PlayerEffectSpec、minion_play_accepted、冻结提交种族和RemovePlayerEffect；两次使用两个命名阶段，来源回手再打出允许领取旧效果。没有新模块或字段，当前付费物理入场政策待CN校准，见[独立匹配契约](m3-next-draenei-basics.md)。

抽到时召唤复用repeat手牌进度、原成功HAND抽牌事实、RevealHandCard、SummonStoredCard和Draw，移动同一物理随从到声明场面，补抽仍属原抽牌者；没有新增模块、字段或版本。满手／满场／优先级为待CN校准政策，见[独立抽取契约](m3-draw-summon-basics.md)。

换牌库与手牌换牌库底部复用一次捕获的原物理引用和MoveCard，保留原实体、原顺序及既有恢复／信息政策；没有新Swap模块或字段。必要本回合结束临时保存／取回已补独立模块，其他来源和精确CN朝向／窗口仍开放，见[独立区域契约](m3-zone-exchange-basics.md)。

地标有序换面已经由LocationFaceReference/AdvanceLocationFace表达，保留原物理实体和使用生命周期，只替换印刷面与epoch；过时缺入口描述不作为新模块依据。接口和边界见[地标换面契约](m4-locations.md#场上有序换面)。

永久复制对手手牌复用RemoveFromGame与CopyCard：原组整批私有移除，普通current复制逐张推进，没有临时历史或取回；必要来源仅隔离适配。无新模块／字段／版本，精确材料和窗口待CN，见[独立表达契约](m3-permanent-hand-basics.md)。

独立预备使用 `hand_actions=(HandActionSpec('prepare', 'prepare', 1),)`，第三参数为最低投入而非固定费用；沿用 `Game.quote_hand_action` 和 `UseHandAction`。当前仅支持随从/法术静态声明，额外主体和授予后置，详见[预备契约](m3-prepare.md)。

独立伪装使用普通随从`CardDefinition(disguised=True)`，主机动作通过`PlayCard(..., board_player_id=2)`选择场面，省略即己方。玩家命令使用相对自己的`side: 'enemy'`。主体上下文player_id仍为出牌者，伪装牌相对场面的文本使用接受时source.controller；不要用转控效果模拟首次落位。详见[伪装契约](m3-disguised.md)，不预先开发组合权限。

回合调度使用独立`QueueTurns`/`SkipTurns`，保存被延后的自然后继，真实开始沿原流程执行，跳过不建立自身区间。临时关键词和冻结用实际自身序号计时，详见[回合基础契约](m3-turn-scheduling.md)。本批只补独立基础，不扩展组合机制。

独立比费使用`Joust`和`joust_result(ctx.event)`，复用物理牌库查询、存储费用与公共解释器；胜负及选中引用一次捕获，卡牌奖励使用现有效果。玩家只见揭示卡ID/费用，不追踪隐藏牌库实体。牌库顺序、复杂费用与空池仍是待国服校准的内部政策，详见[比费契约](m3-joust.md)。

独立进化是`adapt-options-v1`配方库：`register_adapt_options`显式注册必要选项/植物，`adapt(ctx, target_ids, registry)`返回已有RequestChoice和附件效果。没有新增Effect类型、持久状态或第二套选择逻辑；静态注册表在宿主对局冻结，来源包需显式版本。详见[进化配方](m3-adapt.md)。

独立移除使用`RemoveFromGame((CardReference或MinionReference, ...), source_id=None, reveal=False)`。全部目标先离场再沿检查点继续，不能用Destroy/DiscardCard/DestroyDeckCard代替；setaside和实体身份不进入玩家观察。详见[移除契约](m3-nondeath-removal.md)，不新增取回或具体部件组合接口。



## 1. 组合已有指令



行为回调接收 `RuleContext` 并返回 `Effect` 序列。例如对指定目标造成伤害，然后抽一张牌：



```python

from hs_sim.engine import CardDefinition, CardType, DamageKind, Registry

from hs_sim.engine.effects import Damage, Draw



registry = Registry("my-mechanisms-v1")



def strike_and_draw(ctx):

    return [Damage(ctx.target_id, 2, ctx.source_id, DamageKind.SPELL), Draw(ctx.player_id)]



registry.register_behavior("custom.strike_draw", strike_and_draw)

registry.register_card(CardDefinition(

    id="custom.spell", name="机制测试法术", kind=CardType.SPELL,

    cost=2, requires_target=True, on_play="custom.strike_draw",

))

```



这是定义片段。创建对局时还需注册英雄等场景引用的所有定义。批量同时伤害使用 `DamageBatch(tuple(...))`；连续返回多个 `Damage` 会在每条伤害之间检查死亡和触发，语义不同。



回调得到状态副本，修改它不会修改对局。通过 `ctx.player_id`、`ctx.source_id`、`ctx.target_id` 和 `ctx.event` 决定效果；不要写全局状态、读系统时间或用全局随机数。随机效果通过 `RandomDamage` 或受信任处理器调用引擎唯一 RNG。



普通三参数 `Damage` 默认是 EFFECT；法术直伤请显式传入 SPELL，不能依赖来源类型自动推断。`GrantSpellDamage` 与印刷 `spell_damage` 支持可叠加法伤。详见 [M2 伤害与目标契约](m2-damage-targeting.md)。



## 2. 目标规则、触发和光环



- `TargetSpec` 声明区域、类型、关系和 REQUIRED/IF_AVAILABLE/OPTIONAL 模式；`register_target_rule(id, callback)` 提供额外的严格 bool 条件。旧 `requires_target=True` 仍表示必选活体角色，不能与 TargetSpec 混用。`Game.legal_targets`、出牌校验和合法枚举共用规则。

- 对当前攻击力/生命/最大生命/损伤/耐久、受伤、当前关键词和印刷/当前种族等可表达条件，优先使用 `TargetPredicateSpec` / `register_target_predicate`，普通目标及独立战吼/连击主体均可重建原候选；见[声明式目标筛选](m5-target-predicates.md)。任意自定义回调仍需符合各来源的玩家观察与恢复证明契约，不能冒充内置规则。

- 对依赖玩家可见资源、费用或公开计数的条件，使用 `register_player_target_rule(PlayerTargetRuleSpec(id, version), handler)`，处理函数仅接收纯玩家DTO。普通根与独立BC/Combo可重建原观察，原窗口与后续实时资格分别处理；见[玩家条件原输入](m5-player-target-inputs.md)。旧visibility=player注册不自动取得该主体来源权限。

- 随从种族修改使用 `ChangeMinionTribes(reference, TribeChangeSpec(...))`，声明添加/设定/移除、来源、到期及沉默政策；以 `has_any_tribe(..., basis='current')`查询有效身份，`printed`查询卡面。跨区 `MinionScope.tribe_basis`默认printed，可以明确选择current；见[动态种族契约](m5-dynamic-tribes.md)。

- `on_play` 对应普通主动出牌效果，战吼单独声明 `battlecry`；`Summon` 不调用两者。`deathrattle` 在统一死亡检查后执行。

- 静态定义在实体创建/重置时安装成 `AbilityInstance`，结算使用实体当前能力。不要在效果里重新查询静态卡牌的关键词或亡语来判断当前能力，这会绕过沉默、授予和消耗。

- `TriggerSpec(event="card_played", behavior_id="...")` 声明事件订阅。当前战场随从、已装备武器及英雄技能位置支持普通触发。回调自行检查事件的玩家、来源和条件。

- 触发来源与上下文在事件捕获时快照；已捕获触发不会因来源随后死亡而丢失。同批死亡随从先全部离场，再处理死亡事件和亡语。亡语的最后状态通过 `ctx.death: DeathRecord` 读取，不能依赖已经失去光环或发生后续变化的墓地实体。

- `AuraSpec(attack=1, health=1, include_self=False)` 提供友方随从攻击/生命光环。由内核重新派生，不能把光环写成反复叠加的永久增益。



常用事件为 `card_committed`、`minion_summoned`、`card_played`、`attack_declared`、`damage_dealt`、`damage_prevented`、`shield_lost`、`healed`、`minion_died`、`card_drawn`、`card_burned`、`turn_started`、`turn_ended`。M1 新增 `ability_granted`、`attachments_expired`、`silenced`、`card_returned`、`transformed`、`control_changed`、`card_shuffled`、`minion_reborn` 等事件。这些是原型接口，不保证对应官方全部触发窗口。`damage_dealt.amount` 包含护甲吸收部分，`data` 另含 `health_damage` 和 `armor_absorbed`。



## 3. 附魔、动态能力与生命周期



使用效果创建附件，不能直接修改 `entity.attack_bonus`、`entity.keywords` 等派生缓存。例如以下行为为合法随从目标提供本回合 +2 攻击力，并授予复生：



```python

from hs_sim.engine.effects import Buff, GrantKeyword

from hs_sim.engine.model import Keyword



def empower(ctx):

    return [

        Buff(ctx.target_id, attack=2, source_id=ctx.source_id,

             expires_turn=ctx.state.turn),

        GrantKeyword(ctx.target_id, Keyword.REBORN, source_id=ctx.source_id),

    ]

```



这是行为片段；对应卡牌仍须注册并配置随从目标规则。`expires_turn` 是全局回合编号，设为 `ctx.state.turn` 表示本回合结束时到期；`None` 表示没有自动到期时间。不能授予已经过期的附件。



| 效果 | 当前用途 |

| --- | --- |

| `Buff(target_id, attack=0, health=0, source_id=None, expires_turn=None)` | 创建独立加法附魔；攻击可减少，当前公共接口的生命增益要求非负 |

| `SetStats` / `SwapStats` / `DoubleStats` | 有序设值、快照交换/翻倍，均支持来源与到期；`StatReference` 在执行时读取目标属性，见 [属性运算契约](m2-stats.md) |

| `EquipWeapon` / `ModifyWeapon` | 新建装备、调整攻击/耐久；武器从手牌正常打出用 `PlayCard` |

| `ReplaceHeroPower` / `RefreshHeroPower` / `SetHeroPowerUses` | 新实体替换、刷新使用次数、显式修改上限；正常使用必须走 `UseHeroPower` |

| `ReplaceHero` | 英雄替换原语，见 [武器与技能契约](m2-equipment-powers.md)；从手牌打出英雄牌使用 [M4 英雄牌入口](m4-heroes-history.md) |

| `GrantKeyword` | 授予关键词能力实例 |

| `GrantDeathrattle` / `GrantTrigger` / `GrantAura` | 授予亡语、事件订阅或友方攻击力光环；行为 ID 必须已注册 |

| `RemoveEnchantment(target_id, enchantment_id)` | 按唯一 ID 移除一个属性附魔，不影响其他附件 |

| `Silence(target_id)` | 移除允许沉默的附魔和能力，随后重新派生属性与光环 |

| `ReturnToHand` / `ShuffleIntoDeck` | 保持实体 ID，按契约重置状态并变更区域 |

| `Transform(target_id, card_id)` | 保持实体身份/位置/当回合攻击记录，重建新定义的属性与能力 |

| `CopyMinion(target_id, player_id, position=None, mode='current')` | 创建新实体；`current` 复制当前状态，`base` 使用印刷定义 |

| `ChangeControl(target_id, player_id)` | 保持 owner 和附件，变更 controller、位置和入场顺序 |



同一个实体可以有多个同类能力；亡语和触发分别执行。圣盾和复生是旗标机制，一次消费会标记全部当前有效的同名实例，不把重复授予当作额外层数。复生由死亡内核执行，卡牌只需声明或授予 `Keyword.REBORN`。



`Keyword.LIFESTEAL` 与 `Keyword.STEALTH` 使用动态关键词实例；`Freeze` / `Unfreeze` 操作实体冻结状态。详见 [战斗状态契约](m2-combat-status.md)。



属性模型已支持有序设值/交换/翻倍，费用附魔/光环/有限次修正也已接入；一般条件持续时间仍未完整覆盖。更多能力不应通过写缓存或单卡特判绕开公共内核。



## 4. 新增或替换底层机制



已有原语无法表达时，定义不可变 `Effect` 子类并注册处理器：



```python

from hs_sim.engine.resolver import default_mechanics



mechanics = default_mechanics("my-effects-v3")

mechanics.register(MyEffect, handle_my_effect)

game = Game.from_scenario(scenario, registry, mechanics=mechanics)

```



处理器接收 `Resolution` 和效果，可返回后续效果序列。优先展开成已有原语；需要修改状态时，使用结算器的区域操作和 `emit`，使变更进入事件与统一检查点。处理器在事务副本上运行，动作结束时检查状态不变量。处理器中不能保存快照、分叉或重入玩家操作。



完整可运行示例：[examples/extend_mechanics.py](../examples/extend_mechanics.py)。



```powershell

python -m examples.extend_mechanics

```



修改已有机制使用 `mechanics.replace(EffectType, handler)`，须采用自己的机制版本；整个 `core-effects-v` 版本族均为保留名称，不能用于替换。单体、攻击及范围伤害都汇入 `DamageBatch` 处理器，可在同一入口修改伤害策略；替换时必须保留 `CombatExchange` 的耐久与攻击结算责任。不要直接调用另一个处理器来绕过注册分发或检查点。



## 5. 版本与回放



注册表和处理器集合在创建对局时冻结。改变回调语义须提升相应 `Registry.version` 或 `Mechanics.version`。改变调度/死亡检查还需要新增并实现 `Ruleset.id`；当前只接受原生 `prototype-v160`，拒绝不能正确恢复的 `Ruleset` 子类。



| 层 | 当前版本 | 兼容约定 |

| --- | --- | --- |

| 规则 | `prototype-v160` | 不把旧时序静默按新规则运行 |

| 默认效果处理器 | `core-effects-v160` | 恢复时版本和效果类型签名必须匹配 |

| 合成 / 代表机制包 | `synthetic-mechanics-v3` / `representative-m5-v64` | 选择相同注册表，校验指纹 |

| 对局快照 | 严格整数 schema 155 | 显式拒绝 schema 1～154；旧快照需对应原引擎，无隐式迁移 |

| 动作回放外层 | schema 1 | 外层结构未变，当前 `origin` 是 schema 155 快照；旧起点仍不兼容 |

| 玩家观察 | `player-view-v68` | 本人可见手牌祈求进度、自己的祈求成功数与青玉计数；隐藏主牌身份/区域、牌库身份、捕获局面和证明保持私有 |

| 玩家命令 | `player-actions-v10` | 沿固定座位与选择授权，不输出全知状态 |



指纹包括静态定义、行为/目标规则 ID、效果类型全名和显式版本，**不包含 Python 函数体**。版本管理由扩展作者负责。回放加载要求提供相同代码；JSON 不会下载、导入或执行脚本。



回放起点是含完整 RNG、附件、能力使用状态和死亡历史的快照，后接成功操作及每步状态/事件摘要。恢复后产生新分支：已有日志保留，仅记录恢复后的操作。可在动作完成或正式等待选择的提交边界保存快照；处理器运行中禁止快照。



CLI 的 `simulate` 和 `replay` 默认使用合成包，指定 `--card-set representative` 使用真实代表卡实验包；两次运行须选同一个包。其他自定义包通过 Python API 运行和重放。可运行代表场景见 [复生场景](../examples/scenarios/reborn.json) 与 [操作序列](../examples/actions/reborn.json)：



```powershell

python -m hs_sim target

python -m hs_sim simulate examples/scenarios/reborn.json --actions examples/actions/reborn.json --card-set representative --replay-out outputs/reborn-replay.json

python -m hs_sim replay outputs/reborn-replay.json --card-set representative

```



摘要用于发现损坏和重算分歧，不是签名。当前使用 Python `random.Random`，跨 Python 版本的长期回放兼容性未保证；可复现实验应固定运行版本。



## 6. 新机制验收



1. 通过公开 `Scenario → Game.apply` 测试正常结果与关键边界。

2. 覆盖死亡、触发顺序、满场/满手牌等相关交互；新增时序写入版本契约。

3. 随机机制验证同种子可重算，扩展异常验证状态、事件、历史和 RNG 一起回滚。

4. 未知定义、行为或效果明确报错；不从卡牌文本推断逻辑，也不把未支持机制当作无效果。

5. 改变附件、区域或死亡语义时，验证复制/重置、沉默/到期、来源失效和快照/回放；更新生命周期契约与已知差异。



中途选择现在使用 `RequestChoice` / `SelectChoice` 与可序列化结算帧；完整候选池与特殊抉择时序仍需后续实现。当前 `Action` 是显式封闭集合，增加玩家操作需同步修改编解码、合法性检查、分发与回放测试。不要让回调直接读取控制台输入。



## 7. 费用与资源扩展



出牌和技能通过 `Game.quote_cost` 获取包含光环和玩家修正的实际费用；`Entity.cost` 只是本地费用。`CostSpec`、`ModifyCost`、`AddCostModifier` 与 `GrantCostAura` 负责不同来源的修正。资源变化用 `GainTemporaryMana/RefreshMana/ChangeManaCrystals/SetManaCap/Overload/UnlockOverload`，不要直接改派生法力。`SpendResource` 在执行时决定可选分支，避免读取过早的回调快照。详见 [费用与资源契约](m2-resources.md) 和 [资源组合测试](../tests/test_m2_resources.py)。



## 8. 伤害与治疗规则



静态 `health_rules` 或动态 `GrantHealthRule` 为在场实体附加 `HealthRule`，用显式分类/派系/关系选择作用范围。普通治疗请区分 `HealingKind`，同时治疗使用 `HealBatch`；吸血经过同一规则层。转换、重定向和数值层的优先级、循环拒绝与批次处理器责任见 [伤害与治疗规则契约](m2-health-rules.md)，不要用收到伤害后的普通触发伪造伤害替换。



## 9. 挂起选择与扩展数据



卡牌返回 `RequestChoice`，选项为不可变 `ChoiceOption`。固定分支组合现有效果；需要处理整个结果时注册 `on_select` 行为，通过 `ctx.choice` 读取规范化选择。等待期间由 `SelectChoice` 提交，来源玩家可以不是当前回合玩家。



等待边界的快照保存完整解释器帧，不保存 Python 栈。自定义效果和嵌套数据必须可严格编码：效果用 frozen dataclass 并注册 handler，额外 frozen dataclass 或 enum 用 `mechanics.register_payload_type` 显式登记。元组可递归包含已登记值；可变容器、任意对象、函数及未登记类型不能进入挂起队列。不要把运行状态保存在回调闭包中。



所有候选在抽样前验证，已抽候选在恢复后不重抽；原操作预算跨多个选择累计，异常回滚到最后已提交边界。API、原型时序、数量限制和完整示例见 [M3 选择契约](m3-choices.md)；运行 `python -m examples.resume_choice` 可验证暂停保存、恢复、分支及逐步回放。



## 10. 构筑与开局扩展



`CardMetadata` 描述职业、稀有度、可收藏性、构筑身份、数量例外、符文和种族；未知字段保持未知，不能静默允许加入卡组。牌组合法性由独立 `DeckPolicy` 提供版本池与禁用信息，不能从执行注册表反推正式合法池。`DeckSpec` 与 `MatchSetup` 交给 `Game.from_decks`，初始英雄通过 `initial_hero_power` 明确关联技能。



`OpeningHook` 在 `before_deal` / `after_mulligan` 阶段展开纯行为，复用公共结算器；原始卡组与当前牌库分开记录。生成牌进入手牌可用 `AddToHand`，满手明确烧牌。完整用法和仍未实现的特殊规则见 [M3 构筑/开局契约](m3-opening.md)，端到端演示为 `python -m examples.play_constructed`。



## 11. 玩家信息与事件输出



`Game.observe(viewer)` 和 `player_events(viewer, after=cursor)` 是只读玩家 DTO；内部实体 ID、完整状态与调试事件不可直接用于玩家输出。`RevealHandCard` 显式向指定座位揭示手牌身份，生成已知牌可使用 `AddToHand(..., revealed_to=(1, 2))`。普通 `AddToHand` 仍只向持有者显示牌面。



新增效果不能依赖“后来牌已公开”去过滤旧日志，也不能默认将自定义 `Event.data` 发布给玩家。自定义公共事件需要扩展白名单、投影和隔离测试；区域迁移用公共原语，洗入必须退休追踪句柄。选择提示和元数据是实现主动交给选择方的内容，应按实际可见性填写。详见 [M3 信息契约](m3-information.md)。



`Game.for_player(viewer)` 已提供受限动作、只读观察修订值和固定错误码。`legal_actions/apply/ActionResult` 的原 Game 接口仍是宿主接口。自定义目标/技能条件如需给玩家调用，须通过 `visibility='player'` 注册，接收 `PlayerRuleContext` 的纯观察副本；不能在闭包中捕获全知局面。未迁移的条件及不支持的隐藏目标域明确报错，详见 [玩家操作契约](m3-player-api.md)。



## 13. 发现与随机生成扩展



通过 `Registry.register_pool_card` 登记独立的印刷元数据，用 `register_pool` 注册带目标/模式/版本的成员与权重清单。行为返回 `DiscoverFromPool` 或 `GenerateFromPool`，过滤条件使用不可变 `PoolQuery`，不能把执行注册表当成候选池。所有合格候选都须可执行后才能抽样；候选池和构筑合法池各自维护。完整 API、限制与示例见 [生成池契约](m3-generation.md)，下一步区域原语见项目状态。



## 14. 手牌/牌库操作与候选



使用 `AddToDeck` 生成新牌；对已有牌先捕获 `CardReference`，再组合 `MoveCard`、`CopyCard` 或 `DiscardCard`。区域内检索用 `DrawMatching` / `DiscardMatching`，定向抽牌必须显式提供空库策略。交互选择用 `ChooseFromZone`，玩家仍通过既有 `SelectChoice` / PlayerPort 提交；不要将宿主牌库 ID 作为普通玩家目标发送。类型、状态保留、重复牌、时点及可见性契约见 [手牌与牌库](m3-zones.md)，运行 `python -m examples.zone_operations` 验证组合与恢复。





## 15. 额外手牌主动操作



`CardDefinition.hand_actions` 显式声明 `HandActionSpec`；`UseHandAction` 进入校验、枚举、固定座位命令与回放。当前种类为 trade/forge，独立法力费用复用公共账目，不消费普通出牌优惠。升级目标和纯行为在冻结注册表前检查；重复锻造可以声明自引用形态并以 `on_use` 返回公共效果。



不要把替代手牌操作写成零费法术或直接调用 `Game.apply`。来源卡的 `on_play`、普通目标要求和战场容量与该操作分开；玩家使用条件需显式声明 `visibility='player'`。操作/升级/后置行为都在同一事务及可恢复解释器中执行。隐藏牌面变化和交易时的揭示由信息台账处理；详见 [交易与锻造契约](m3-hand-actions.md) 及 [完整实验对局](../examples/play_hand_actions.py)。星舰发射与地标已通过各自场上对象和动作实现；泰坦能力已通过独立随从动作实现，不能借此伪造手牌来源。



## 星舰与非活跃场地实体



组件声明 `Keyword.STARSHIP_PIECE`，舰体声明不可重复的 `starship_for` 职业元组，发射专用行为使用 `on_launch`，免费发射返回 `LaunchStarshipEffect`。组件合并与发射由内核负责，不在单卡回调直接改写状态。建造实体占 `board` 位置但 `entity.active` 为假；区域容量与活跃随从计数必须区分。组合实体复制、回手、洗入、复生必须携带 `components` 并通过 `install_base` 重建。完整规则、限制和后续扩展见 [M4 星舰契约](m4-starships.md)。





M4 协议扩展提供 `InvokeBehavior` 执行时回调、`LaunchStarshipEffect.followup` 成功后续队列、非施法 `SplitDamage` 和 `AddToHand.cost` 初始费用。数据必须保持不可变且能够进入帧；协议等描述设置 `choice_only=True`，不能作为普通卡创建。参见 [协议契约](m4-protocols.md)。





M4-01b-03a 新增 `GrantRandomBonusEffects` 与 `SummonFromCandidates`，分别表达版本化额外效果和卡牌明示的完整固定候选召唤；后者不从已实现列表推测候选。`CardMetadata.factions` / `PoolQuery.factions_any` 与种族独立，未知元数据仍明确失败。魔免检查位于共享目标谓词；恢复、玩家命令和回放复用现有框架。完整契约、证据缺口和实例见 [额外效果与人族生成](m4-bonus-effects.md)。



## 地标与共享场位



声明 `CardType.LOCATION`、正耐久和 `on_use`，不设置角色攻击/生命或 `on_play`。手牌打出只付费并放置；`UseLocation` 才校验目标、消费耐久及进入冷却。能力目标使用现有 `TargetSpec`，自定义玩家可见条件仍须声明可见范围；生成地标使用 `PlaceLocation`，耐久/早开/销毁使用 `ModifyLocation`、`RefreshLocation`、`DestroyLocation`。



遍历 `board` 时必须区分场位容量、活跃随从和角色。地标的关闭状态不等于星舰的非活跃建造状态，不能使被动触发或费用光环一并失效。地标的特殊复制/转控/变形、自动激活以及伤害/治疗规则持有能力仍未纳入本批契约。详细时序、序列化、公开命令与代表例子见 [地标契约](m4-locations.md)。



## 英雄牌与发射历史



可打出的英雄定义使用 `CardType.HERO`、`hero_card=True`、`hero_armor` 和 `initial_hero_power`；保持原职业的英雄额外声明 `keep_hero_class=True`。用原有 `PlayCard` 打出，由内核替换英雄/技能后执行出牌主体；战吼使用独立 `battlecry` 声明。不要把初始英雄、英雄牌或英雄技能混作同一种手牌，入口共用 `CardDefinition.hand_playable`。



生成与区域筛选的职业读取 `PlayerState.hero_class`；`deck_class` 仅表示构筑起点。星舰原始发射进入 `GameState.starship_history`，行为可返回 `RelaunchStarships(player_id)` 再次发射；不得直接修改历史或用扫描现存舰体/事件日志代替历史状态。完整契约、暂定规则与验证见 [英雄牌/雷诺与发射历史](m4-heroes-history.md)。



## 休眠生命周期扩展



[休眠契约](m4-dormancy.md) 定义独立 `DormancyState`、`MakeDormant` / `AwakenMinion` / `AdvanceDormancy`、`on_awaken` 和 `dormant_triggers`。普通能力读取共同活跃资格；倒计时使用带实例 ID 的可序列化队列，避免过期任务推进新状态。印刷休眠统一从入场/基础重置入口初始化，复制策略显式区分；卡牌回调不直接修改状态。



## 有限次随从能力



泰坦使用 `Keyword.TITAN` 和三个 `ActivatedAbilitySpec`，行为返回公共效果，展示描述使用 `choice_only`。`UseMinionAbility` 复用目标规则、玩家条件、事务和回放；状态存入独立能力实例。不要把能力伪装成手牌法术或在卡牌回调直接改攻击次数。能力伤害显式声明 `DamageKind.MINION_ABILITY`；效果驱动战斗使用 `ForceAttack`，默认敌方角色关系，显式 `combat_relation='friendly_minions'` 只允许同控制者的不同随从；攻击者仍限随从。完整范围、等待选择、公开日志及复制/沉默约定见 [泰坦与有限次能力契约](m4-minion-abilities.md)。



任务通过 `QuestSpec` / `QuestStageSpec` 声明，进度由带实例/阶段保护的 `AdvanceQuest` / `ResetQuestProgress` 修改。任务/任务线保证起手，支线任务不保证；公开区域与奖励选择共用玩家观察、事务和存档。详见 [任务契约](m4-quests.md)，持续玩家效果和奥秘见后续章节。



## 玩家长期效果



用 `Registry.register_player_effect(PlayerEffectSpec)` 注册独立规则，行为返回 `AddPlayerEffect` / `RemovePlayerEffect`；持续法术通过 `ongoing_effect_id` 共用出牌前容量检查。持续期、回合计时和来源保留由内核负责，不要把整局能力绑定到当前英雄或活着的来源随从。`PlayerAuraSpec` 提供显式卡牌过滤的加法属性光环，`RuleContext.player_effect` 提供捕获实例；定义与实例必须能进入快照和恢复帧。完整支持范围、暂定时序与示例见 [玩家效果契约](m4-player-effects.md)。



## 奥秘与干预效果



用 `Registry.register_secret_condition` 注册只返回布尔的纯条件，实体法术声明 `Keyword.SECRET` 和 `SecretSpec`。普通出牌由内核处理支付、反制与隐藏部署；内部生成使用 `SetSecret`，主动移除使用 `RemoveSecret`。奥秘回调使用 `RuleContext.window` 的显式 ID 返回 `CounterSpell`、`RedirectAttack`、`SummonAttackTarget`、`RedirectSpellTarget` 或 `SummonSpellTarget`，不要自行修改队列、猜测实体 ID 或重入 Game。反制与法术目标替换是不同阶段。`ReturnToHand` 的 `to_owner=True` 与 `cost=CostSpec(delta=2)` 可组合拥有者回手和额外费用。条件、窗口、隐藏信息、容量以及未支持边界见 [奥秘契约](m4-secrets.md)。



## 出牌条件和历史



`RuleContext.play` 提供原始出牌事实，`play.combo`、`play.outcast` 和 `prior_turn_plays` 用于行为分支，不能在牌移出手牌后重新计算原位置。`played_cards` 可按玩家、回合、类型、完成状态及 before_id 查询；召唤、技能、交易和锻造不计为打出。`target_condition="combo"` / `"outcast"` 控制是否启用原 TargetSpec，必须声明对应印刷关键词。恢复分支可用 `InvokeBehavior(..., play_id=context.play.id)` 显式引用原记录。未知条件和裸关键字授予明确拒绝；更多来源/条件需扩展契约。见 [出牌历史与条件](m5-play-history.md)。



## 有限次被动触发



定义 `limited_triggers=(LimitedTriggerSpec.spellburst("my.burst"),)` 并声明 `Keyword.SPELLBURST`；暴怒使用 `frenzy` 和 `Keyword.FRENZY`。这两种关键词要求专用能力实例，不能只 GrantKeyword。一般有限次事件使用 `LimitedTriggerSpec("event", "my.behavior", condition_id="my.condition", uses=2)`，条件经 `register_trigger_condition` 注册，必须返回 bool，失败不消费；条件状态副本不能用作持久存储。



动态能力使用 `GrantLimitedTrigger(target_id, spec, source_id=None, expires_turn=None)`。行为的 `context.trigger` 包含刚消费后的实例，`context.play` 在施法事件中保留原出牌记录。武器允许法术迸发但不将其传给英雄；暴怒只接受随从。复制当前状态保留次数，基础重置新建印刷次数；未知行为、条件和旧格式快照明确拒绝。选择/恢复、时序假设及代表见 [有限次触发契约](m5-limited-triggers.md)。



## 储存卡增益与手牌换形



使用 `CardReference.capture(entity)` 冻结实体、区域、控制者、卡名和修订号，不手工省略 `zone_epoch`。`BuffStoredCard(reference, attack=2, health=3)` 修改手牌/牌库随从的普通附魔；`UpgradeHandCard(reference, card_id)` 保留附件并更换同类型印刷形态。生命转耐久需显式 `health_to_durability=True`，目前仅支持随从变武器及已定义的授予能力。跨区域往返或形态往返后旧引用失效，需在新行为上下文中重新 capture。自动腐蚀/注能应通过 HandProgressSpec 声明，由公共调度处理资格与计数。见 [升级基础](m5-hand-upgrades.md)。



## 手牌进度声明



`CardDefinition.hand_progress=HandProgressSpec("infuse", 3, "registered.infused")` 声明注能门槛；腐蚀使用 `HandProgressSpec("corrupt", upgrade_card_id="registered.corrupted")`。对应关键词须一起声明，目标形态、condition_id、on_progress/on_complete 预先注册。重复完成用 repeat=True 加回调，多段升级让下一形态具有自身声明；不要在回调闭包或卡名级变量中计数。完整生命周期与恢复约束见 [手牌进度契约](m5-hand-progress.md)。



## 额外出牌条件与获取



通过 context.play.finale / manathirst / quickdraw 读取本次冻结结果。MANATHIRST 需在定义中同时声明 Keyword.MANATHIRST 和正整数 manathirst 门槛；多个门槛可另读取 play.mana_crystals。target_condition 支持这三种条件，必须有匹配关键词及目标策略。普通生成/抽取/复制/回手效果会自动记录成功获取，不直接改 hand_entry_id 或伪造历史。初始场景手牌视为对局前持有；要测试新获取，执行真实生成或抽取。见 [额外出牌条件契约](m5-play-conditions.md)。



## 磁力声明



可从手牌打出的非组合随从使用 `keywords=(Keyword.MAGNETIC,)` 与 `magnetic_tribes=('mech',)`；额外种族只在有牌面证据时加入。行为仍声明持续触发、亡语、光环等公共能力。不要在 on_play 中手工合体或创建第二个宿主。PlayCard.position 决定普通打出或合体，玩家 DTO 的 magnetic_target 只是派生句柄提示。当前合体不运行材料战吼，自动/效果驱动合体另待契约。见 [磁力及生命周期](m5-magnetic.md)。



## 巨型及存储卡召唤



CardDefinition 使用 `Keyword.COLOSSAL` 和有序 `colossal=(AppendageSpec(card_id, side), ...)`；附肢必须注册为普通物理随从，支持同名不同 ID，禁止递归/组合模板。不要在战吼里手写巨型附肢；公共入场会负责分步容量、反应和恢复。`SummonStoredCard(CardReference.capture(entity), player_id, position)` 移动手牌/牌库中的同一实体，保留属性，失败不公开暗牌；它不是复活池或自动施法。更多来源、生命周期和时序假设见 [巨型契约](m5-colossal.md)。



## 兆示及主动亡语



行为使用 `Herald(player_id, source_id, grant_keywords=())`；不要依靠 HERALD 标记或出牌事件自动计数。士兵/附肢声明 `herald_scaling=True`，职业士兵另声明 `herald_soldier_for`；每职业一个映射。参数效果使用 `instance_multiplier(context.death or context.source)`，不读取玩家后来的进度。`TriggerDeathrattles` 主动调用时 context.death 为 None，应读取冻结的 context.source；真实死亡才有死亡记录。详见 [兆示契约](m5-herald.md)。



## 相邻光环与生成牌费用



印刷 `AuraSpec(..., adjacent_only=True)` 与动态 `GrantAura` 使用同一物理相邻范围，不能同时 include_self。`AddToHand`、`AddToDeck`、`GenerateFromPool` 支持 cost=CostSpec(...)、expires_turn=当前回合；只允许手牌/牌库目标。生成费用在创建事件前安装，随机池全候选类型预检。完整声明与示例见 [相邻光环/生成费用契约](m5-herald-extensions.md)。



## 条件消灭与奖励



使用 `MinionReference.capture(entity)` 捕获场上随从身份；`DestroyForBuff(victim, beneficiary, attack, health, source_id)` 和 `SacrificeAdjacent(beneficiary, attack, health, side, source_id)` 只在实际接受牺牲后安排奖励。不要用裸 Destroy/Buff 序列模拟成功条件，也不要在卡牌代码中直接写死亡历史。时序、失效条件与星舰边界见 [牺牲契约](m5-sacrifice.md)。



## 有序分支与指定卡牌费用



需要玩家选择执行顺序时，使用 `ChooseInOrder(player_id, options, count, source_id)`；已选项移除，分支全部完成后才请求下一项。需要玩家级指定卡面减费时，使用 `CostSpec(card_ids=(...))` 搭配 `AddCostModifier`；不要根据名称子串匹配或将全局减费复制进每个实体。完整序列化和边界见 [机制契约](m5-deathwing.md)。



## 牌库销毁与牺牲替换



使用 `DestroyDeckCard(CardReference, on_destroy=(...))` 或 `DestroyDeckMatching` 销毁牌库卡；不要调用普通 Destroy 或 DiscardCard 来伪造牌库死亡。只有物理移除成功才排入后续，事件反应可先挂起。声明 `DeckSacrificeSpec(card_ids=(...))` 替换指定友方卡面的相邻牺牲；生命周期与信息边界见 [牌库销毁契约](m5-deck-destruction.md)。



## 持续关键词光环



使用 `CardDefinition.keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY),)` 让活跃场上随从向当前友方英雄提供风怒。`GrantKeywordAura` 授予可沉默/到期的光环附件；友方随从范围可选择包含自身或物理相邻。不要循环 GrantKeyword，否则来源离场和受益者复制会残留能力。消耗型关键词明确拒绝，范围与恢复约束见 [关键词光环契约](m5-keyword-auras.md)。



## 按当前属性生成



从已捕获上下文读取 `attack = context.source.attack`，然后以 `PoolQuery(min_cost=attack, max_cost=attack)` 配合 GenerateFromPool 使用。当前攻击力包含光环/附魔；候选费用为印刷费用。不要把可变实体或闭包放入查询，也不要在第二张生成牌入手时重新读取数值。捕获窗口与奥拉基尔例子见 [动态生成契约](m5-alakir.md)。



## 法术重复执行



在随从定义上声明 `spell_repeats=(SpellRepeatSpec(),)`，或通过 `GrantSpellRepeatAura` 动态授予。不要复制 PlayCard、重复扣费或手工发送 card_played。需要沿用的抉择设置 `RequestChoice.repeat_key` 与法术 source_id；发现保持默认 None。行为每遍重新计算，出牌条件与目标保持捕获值，详见 [重复施放契约](m5-spell-repeats.md)。



## 生命损失与上限增长



随从通过 `health_loss_replacements=(HealthLossReplacementSpec(),)` 或 `GrantHealthLossReplacement` 声明替换。主动生命损失使用 `LoseHealth`，上限增长使用 `GainMaxHealth`；不要将生命费用伪装为 Damage 或将增长伪装为 Heal。类别筛选、到期和保存参见 [生命损失契约](m5-health-loss.md)。



裂变牌以 `ShatterSpec(left_card_id, right_card_id)` 声明普通法术卡族；两片各有独立行为，根牌定义合并效果，见 [公共手牌契约](m5-shatter.md)。不需要卡牌代码自行轮询手牌或分配实体。



印刷回响通过 `HandRepeatSpec` 与 `Keyword.ECHO` 声明；通用临时生成使用 `CreateTemporaryCard`。到期、费用下限及复制保留由内核维护，见 [回响与临时手牌](m5-echo.md)。



双生法术、微缩/巨化使用 `HandDerivativeSpec(keyword, card_id)` 指向独立终结形态。原牌和衍生物各自注册，资格捕获及生成交给内核；不能直接授予孤立生成关键词。见 [衍生形态契约](m5-hand-derivatives.md)。



实时手牌能力使用 `KeywordAuraSpec` 的手牌范围；持久授予用 `GrantStoredKeyword(CardReference, keyword)`，旧区域引用不命中新实体状态。见 [手牌能力契约](m5-hand-keywords.md)。



区域召唤使用 `SummonFromZone`，死亡候选使用 `DeathQuery`/`death_candidates`；`Resurrect` 可按死亡记录或卡牌身份选择，`ResurrectMinion` 使用指定死亡 ID。共用 `SummonStats` 在召唤触发前设值，见 [召唤来源契约](m5-summon-sources.md)。



自动施法使用 `CastSpell` 或携带 `CardReference` 的 `CastStoredSpell`。通过 `RuleContext.cast`/`spell_conditions` 读取施法来源与条件；不要伪造 `PlayRecord`。宿主可用 `cast_spells` 区分尝试/成功与 hand/repeat/effect 来源，见 [施法契约](m5-spell-casts.md)。



抽到施法需配对声明 `Keyword.CASTS_WHEN_DRAWN` 与 `CastWhenDrawnSpec`。抽后行为通过 `after_draw` 登记，不放在法术效果末尾；它等待整个补抽链完成。使用 `RuleContext.draw` 读取抽取上下文，宿主查询用 `drawn_cards`。见 [抽取契约](m5-draw-casts.md)。



历史来源使用 `SpellHistoryQuery`、`DiscoverSpellHistory`、`RecastSpell` 与 `RecastFromHistory`；版本池批量使用 `CastFromPool`。显式选择成败、来源、去重、目标与候选刷新政策，不把历史列表长度冒充所有卡文计数。见 [历史与批量契约](m5-spell-history.md)。



## 回溯声明



法术/随从使用 `Keyword.REWIND` 与 `rewind=RewindSpec(retries=1)` 声明单次手动打出的重试预算。行为可读 `RuleContext.rewind_attempt` 决定回溯后候选；保留/重试由内核提供并沿用 SelectChoice。卡牌代码不能自己恢复状态或重置 RNG。多次回溯可用 `RewindSpec(retries=2, next_card_id="remaining_one")` 声明严格递减的同牌卡面链，末形态不含回溯；注册时检查完整链，不能改变身材/费用/行为。实例/附件与原出牌支付报价保留，详见 [次数卡面和 R-092](m5-rewind-forms.md)。随从声明 `retain_rewind_outcomes=True` 或通过 `GrantRewindRetention` 授予，可捕获不叠加的保留结果能力；每个激活只记一次支付/出牌/施法，按 [R-093 契约](m5-rewind-outcomes.md) 累计执行。英雄技能回溯已通过内部验收；检查点规则见 [R-091](m5-rewind.md)。洗牌消费者读取恢复后的完整语义操作事实，原诊断日志仅由有效时间线提供边界见证，见[洗牌契约](m3-semantic-deck-shuffles.md)。



M5-12a：`Dredge` 提供独立底部物理候选与捕获续接；`CardPreview` 不含牌库追踪身份，`CopyStoredMinion` 复用正常入场。见 [探底契约](m5-dredge.md)。



M5-12b-01：`Excavate` 通过版本化 `ExcavationProfile` 声明完整职业映射；不可变 `ExcavationRecord` 保存奖励与进度，玩家视图仅给出公开计数。未知奖励在抽样前明确拒绝，见 [发掘契约](m5-excavate.md)。



M5-12b-02a：死亡查询可按明确费用依据选择极值；`Resurrect.on_summon` 捕获成功主体，`GrantCapturedKeyword` 在每个授予步骤校验入场身份。续接及历史支持选择恢复，见 [复活续接契约](m5-resurrection-followups.md)。



M5-12b-02b：`GenerationPolicy` 显式允许个别默认禁用关键词；`DiscoverFromPool` 支持多轮、重复身份策略及逐次/全部选后交付。带类型选择记录保存当时的职业和来源，恢复验证候选与选项结构，见 [特殊生成与连续发现](m5-discovery-delivery.md)。



M5-12b-02c：`MinionScope` 捕获三区域物理随从；`BuffMinionsInZones` 复用已有引用增益，`TransformCapturedMinion` 与 `TransformMinionsInZones` 提供区域变形和独立费用依据/保留策略。选择续接保存固定候选条件，隐藏换形撤销旧知识，见 [跨区域批次](m5-cross-zone.md)。



M5-12b-02d：`ChangeHeroMaxHealth` 显式选择上限变化后的剩余生命策略；`StealHeroHealth` 原子更新双方永久属性，再发出事件。它们复用英雄附魔、类型化恢复和公共死亡检查，不进入伤害/治疗/支付路径，见 [生命转移契约](m5-health-transfer.md)。



M5-12c-01：`ImbueProfile` 显式声明全部职业映射，`Imbue` 记录玩家历史并协调技能替换，`imbue_value` 捕获效果参数。成长与物理技能次数分离，无技能职业与缺适配分别处理；技能回溯、间接激活、被动技能和额外技能位置的独立入口已接入，特殊来源仍按真实卡需求处理；具体范围见 [灌注契约](m5-imbue.md)及[项目状态](project-status.md)。



M5-12c-02a：`TriggerHeroPower` 按执行时的当前位置触发技能；与 `UseHeroPower` 共用独立 `HeroPowerRecord` 和完成过程，付费/次数、目标/选择策略分开声明。`RuleContext.power` 提供捕获记录，技能回溯已接入，详见 [回溯契约](m5-power-rewind.md)，见 [激活契约](m5-power-activations.md)。



M5-12c-02b：英雄技能用 `on_use` + `Keyword.REWIND` + `RewindSpec` 声明每次激活的回溯预算；不支持手牌卡面链。内核统一处理检查点、费用/次数和结果关联 `power_id`，回调仅组合普通效果，见 [技能回溯契约](m5-power-rewind.md)。



M5-12c-03a：`passive_hero_power=True` + 普通 `TriggerSpec` 声明被动技能，不提供手动入口；技能区域监听按安装顺序捕获、开始前复核位置与能力身份。`is_first_play` / `played_cards(tribes_any=..., registry=...)` 查询固定卡牌身份，见 [被动技能契约](m5-passive-powers.md)。



M5-12c-03b：`RandomBuffStoredMinion` 选取一个物理存储随从，扩展的 `BuffStoredCard(cost=...)` 同时提交属性与费用附件。`TransformMinionFromPool` 对指定引用共用批量变形的费用档准备与执行；见 [定向修改契约](m5-directed-modification.md)。



M5-12c-03c：`SummonFromPool` 在执行时验证版本池候选、检查场位再抽样，连续调用逐次重新检查场位。传送门复用物理洗入、抽到施放和玩家灌注累计，在施法行为中捕获费用查询；见 [R-105 契约](m5-imbue-portals.md)。



M5-12c-03d：`quote_generated_cost` 与实际手牌共用费用核心，`ChooseFromPools` 对各组独立抽样并冻结选择；`CreateTemporaryCard(cost=..., cost_expires_turn=...)` 在创建事件前装入期限与费用。支付能力不等于完整出牌合法性，见 [R-106 契约](m5-pool-offers.md)。



M5-12d-01：主技能 `hero_power_id` 与有序 `additional_hero_power_ids` 分别保存；派生 `hero_power_ids` 供统一枚举，`AddHeroPower` 安装额外实体。手动动作、费用/次数、在位监听和观察/恢复处理所有已安装技能；刷新/替换/间接触发的空引用默认指主位；12d-02 已支持捕获引用的定向操作，见 [技能生命周期](m5-power-lifecycle.md)。见 [多技能契约与 R-107](m5-multiple-powers.md)。



M5-12d-02：`HeroPowerReference` 冻结安装身份；定向技能操作复核引用，过时引用跳过。安装成本在事件前提交；英雄替换显式声明保留/移除额外技能。观察 v42 新增移除事件。具体接口与 R-108 见 [技能生命周期契约](m5-power-lifecycle.md)。



M5-12d-03：[多技能组合验收](m5-power-combinations.md)覆盖回溯、保留结果、替换/移除、终局/异常和玩家边界。37 项专项及 18 动作的真实代表人工场景通过；该批验收时未改内核，当前运行版本见项目状态。运行 `python -m examples.power_combinations` 可重现玩家接口、两处待选恢复和终局回放。



M5-13a-01：`health_resolved` 保存不可变 `HealthResult`；`health_result`/`ctx.health_result` 读取捕获事实，三个共享条件判断超杀、荣誉消灭与过量治疗。常驻能力复用触发声明；`Damage`、`Heal`、`RandomDamage` 的 `on_result` 指向注册行为，批次结束后续接，不会复制到吸血包。事件仅供宿主，观察 v42 保持；接口、数值/身份校验及 R-109 见 [伤害与治疗结果契约](m5-health-outcomes.md)。死亡原因持久归因已由 13a-02 内部验收。



M5-13a-02：实体 `death_cause` 暂存首次致死事实，离场时冻结到 `DeathRecord.cause`，救回/跨区/变形清除旧实体归因；`was_honorably_killed(ctx.death)` 提供亡语公共查询。伤害结果负载复用 HealthResult，显式消灭可用 `Destroy(target_id, source_id=None)`，未知来源不猜填。冻结来源与恢复/私有边界、科尔拉克代表及 R-110 见 [死亡归因契约](m5-death-attribution.md)。



M5-13b：`completed_manual_power(state,event)` 验证手动完成事件与冻结激活历史；`is_inspire(state,event,player_id)` 提供共享归属条件，可组合普通TriggerSpec或有限次condition_id。激励自身无新持久计数/队列；已捕获反应生命周期沿用公共契约。两张必要代表、选择/回溯/多技能组合和R-111见[激励契约](m5-inspire.md)。



M5-13c：`ChooseOneSpec`/`ChooseBranch`声明激活前分支，动作与PlayRecord/SpellCastRecord/HeroPowerRecord记录`branch_id`；玩家命令使用`branch`。显式合并分支、自动来源策略、主体内选择以及组合生命周期见[抉择契约](m5-choose-one.md)。新增历史字段使snapshot升至71，玩家观察43/命令7；旧1～71拒绝。



M5-13d-01：战吼使用`CardDefinition.battlecry`，通用`on_play`不推导战吼身份；44条已有代表已显式迁移。`BattlecryRecord`记录实际激活、结束/中断和保留回溯结果遍数，`RuleContext.battlecry`供可信行为查询；见[战吼契约](m5-battlecries.md)。身份增量的原始验证见该契约；当前场上重复见下文，动态战吼授予、玩家次数政策、真实抑制及间接来源仍须补齐。



v73复验：play_hand_actions.py 为 50 动作/261 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。



M5-13d-02a：[场上战吼重复与独立批次](m5-battlecry-repeats.md)通过47项专项，新增铜须这一必要代表。`BattlecryRepeatSpec`与动态光环共用附件生命周期，捕获次数计划，`batch_id/repeat_index`与回溯结果遍数分离；原目标、独立选择、组件与恢复契约见文档。玩家次数政策、真正抑制和间接/历史来源仍归M5，R-114归国服校准。



M5-13d-02b：[玩家战吼次数与到期](m5-battlecry-modifiers.md)通过55项专项。AddBattlecryRepeatModifier与RemoveBattlecryRepeatModifier表达有限次/本回合/长期政策，独立于来源存续和持续区域容量；同一次手牌主体集合只消费一次，重复与回溯沿用捕获计划。新增公开用途/期限投影使当时观察升至44；历史v75为schema74、命令7，R-115与真实反制/历史来源仍待后续。



M5-13d-02c-01：[整次随从出牌反制](m5-minion-counters.md)新增Zone.PLAY/pending_plays、CounterCard/CounterMinion与分阶段窗口。v76先处理承诺反应再入场捕获战吼，有限次数不会由被反制随从消耗；旧的入场后生命周期测试使用minion_summoned。恢复校验绑定区域、窗口、出牌结果与继续步骤。历史v76为schema75/观察45/命令7，异议仅用于公共机制验证；奥卡尼秘密选择和载体存续已在下述v77/02c-02接入，R-116留国服校准。



M5-13d-02c-02：[秘密选择与载体反制](m5-counter-policies.md)提供CounterPolicySpec/GrantCounterPolicy，复用私有RequestChoice与能力实例生命周期；实时检查窗口并原子消费，隐藏策略只对控制者投影，公开日志只揭示实际使用的分支。控制/复制通过事件时私有收据保存已知事实。schema76/view46，其他版本见上表；R-117未国服校准。



M5-13d-02d：[战吼身份与费用](m5-battlecry-costs.md)用CardAbilityCondition统一真实/基础生成匹配，以CostAuraSpec显式声明付款者关系。报价按双方活跃来源及统一附件顺序计算，创建/存储验证共用条件；schema77，观察46/命令7保持，R-118未国服校准。



M5-13d-02e：[公共能力筛选](m5-ability-filters.md)扩展PoolQuery.ability与独立PoolCard.battlecry；物理附件、基础池元数据和死亡冻结附件提供明确上下文，未知不等于false，匹配但未实现的候选仍报错。schema78，观察46/命令7不变；R-119未国服校准。



M5-13d-03a：[间接战吼与历史候选](m5-battlecry-sources.md)提供TriggerBattlecry、RepeatBattlecry、RepeatBattlecries与BattlecryHistoryQuery；当前载体/原能力/历史依据分离，共用调度与恢复，不伪造手牌出牌或复制其他附件。schema79；观察46/命令7及代表包42保持，R-120未校准。



M5-13d-03b：[出牌战吼历史](m5-played-battlecries.md)将捕获声明纳入PlayRecord，新增PlayedBattlecryQuery及整次出牌主体重演。实际激活记录使用played_history/history_play_id，不伪造旧卡出牌；反制/原窗口/选择属于显式R-121政策。schema80/代表包43，观察46/命令7保持。



M5-13d-03c：[触发式首次战吼重演](m5-triggered-battlecries.md)以现有事件/历史原语组合伯尔纳，31项专项、4171项全量与65示例通过。只升级代表包44，内核81/schema80保持；R-122待国服校准。



M5-13d-02f：[起始与当前牌库条件](m5-deck-conditions.md)提供显式条件查询和可保存分支；未知起始事实/元数据拒绝。深岩矿工布莱恩仅组合条件与永久次数政策。45项专项、4216项全量与66示例通过；规则/效果82、代表包45，schema80/观察46/命令7保持，R-123未校准。



M5-13d-03d-01：[有上限的历史战吼序列](m5-battlecry-sequences.md)按捕获主体筛选和计数，冻结选择/顺序及类型化完成标记。48项专项、4264项全量与67示例通过；规则/效果83，代表包45与schema80保持。R-124未校准，本批未新增卡牌。



M5-13d-03d-02a：[来源生命周期与历史归属](m5-sequence-lifecycle.md)区分原历史玩家和本次执行玩家，增加在场/形态/沉默检查及转控/自身目标政策。45项专项、4309项全量与68示例通过；规则/效果84、schema81，代表包45/观察46/命令7保持。R-125未校准，无新增卡牌。



M5-13d-03d-02b：[沙德沃克与混合历史重演](m5-shudderwock.md)仅组合已有公共能力；38项专项、4347项全量及69示例通过。内核84/schema81保持，代表包46、282记录/283定义；R-126上限/嵌套窗口仍待国服校准。下一项连击独立主体与重复机制。



M5-13d-02g-01：[独立连击主体与可恢复激活](m5-combo-activations.md)，55项专项、4402项全量及70示例通过。内核85/schema82/代表包47，282记录/283定义保持；两个既有代表迁移，连击条件法术仍走原施法主体。下一项02g-02独立重复与有限次消费，R-127保留。



M5-13d-02g-02：[连击重复与玩家次数](m5-combo-repeats.md)，56项专项、4458项全量及71示例通过。内核86/schema83/观察47，代表包47、282记录/283定义保持。提交和条件成立的主体接受分别捕获/消费，回溯结果不再扣次数；R-128保留。下一项临时潜行等来源依赖与必要组合。



M5-13d-02g-03a：[临时关键词与回合期限](m5-timed-keywords.md)，53项专项、4511项全量及72示例通过。内核87/schema84/观察48；代表包47、282记录/283定义保持。开始/结束边界、首次入场绑定、复制/转控/休眠/磁力/星舰、暂停恢复与公开期限已覆盖；R-129待国服校准。下一项13d-02g-03b必要鲨鱼之灵代表与幸运彗星独立实验池/来源政策。



M5-13d-02g-03b：[真实连击来源组合](m5-combo-sources.md)，38项专项、4549项全量及73示例通过。鲨鱼、彗星、迪菲亚头目/强盗共四条必要记录，独立56条原始候选审计和不完整六项实验池。内核87/schema84/观察48保持，代表包48、286记录/287定义。下一项13d-02h玩家法术次数政策，先按实际来源明确窗口；R-130与M0/M6/M7保留。



M5-13d-02h：[玩家法术次数政策](m5-spell-modifiers.md)，57项专项、4606项全量及74示例通过。玩家手牌提交收据、有限/长期用途、回合到期、现有较晚光环窗口及恢复/回溯/信息隔离，风潮与泰兰德只组合公共指令。内核88/schema85/观察49、代表包49，288记录/289定义；下一项13d-02i持牌期间施法条件，R-131与M0/M6/M7保留。



M5-13d-02i：[持牌施法条件](m5-held-spells.md)，54项专项、4660项全量及75示例通过。复用手牌进度，在主体接受时记录物理施法事实；驻留重置/当前复制和出牌冻结区分，历史战吼追溯原事实，效果历史缺失明确拒绝。必要代表双弓积骇纳迦只组合公共条件与次数政策。内核89/schema86/观察50、代表包50，289记录/290定义；下一项13d-02j特定卡动态重复附件，R-132和M0/M6/M7保留。



M5-13d-02j-03：[必要来源与候选审计](m5-card-spell-sources.md)，39项专项、4803项全量及78示例通过。完整保留436条原始范围和多职业/同名分组，固定6项不完整实验池；新增越狱构造师、暴风雪、烈焰风暴、炎爆术四项必要代表，修正吉德拉双职业。内核91/schema88/观察51保持，代表包51及293记录/294定义。下一项13d-02k-01亡语激活身份与来源记录；R-135、正式池/上线和M0/M6/M7仍保留。



M5-13d-02k-01：[亡语激活身份与来源记录](m5-deathrattle-activations.md)，54项专项、4857项全量及79示例通过。捕获与实际执行分离，保留旧回调窗口，三类真实死亡与主动触发统一记录，补齐印刷/授予/组件来源、挂起恢复及终局中断。内核92/schema89，代表包52，观察51/命令7保持；293记录/294定义不变。下一项13d-02k-02亡语重复计划与来源政策；R-136及M0/M6/M7保留。



M5-13d-02k-02：[场上亡语次数与重复计划](m5-deathrattle-repeats.md)，44专项、4901全量及80示例内部通过。保存次数来源及完整执行位置，每能力重复、额外执行读取更新局面，保持原死亡/复生检查点；内核93/schema90、代表包53，观察51/命令7保持。只新增男爵，294记录/295定义。R-137待校准；下一项13d-02k-03玩家亡语次数与期限，M0/M6/M7保持缺口。



M5-13d-02k-03：[玩家亡语次数与期限](m5-deathrattle-player-effects.md)，46专项、4947全量及81示例内部通过。复用PlayerEffect与owner边界时钟，捕获独立实例/规格，与场上次数取最大值；到期与暂停恢复沿用公共流程。内核94/schema91、代表包54，观察51/命令7保持；仅新增雪落墓地，295记录/296定义。R-138待校准；下一项02k-04固定主动亡语次数，M0/M6/M7保持缺口。



M5-13d-02k-04：[固定主动亡语次数](m5-fixed-deathrattles.md)，46专项、4993全量及82示例内部通过。主动轮次与来源次数分离，冻结完整载荷和执行位置，后续轮次读取新局面；共用原调度、预算与恢复。内核95/schema92、代表包55，观察51/命令7保持；仅新增约德尔狂吼歌手，296记录/297定义。R-139待校准；下一项02k-05自身/获得亡语范围，M0/M6/M7保持缺口。



M5-13d-02k-05：[自身与获得亡语范围](m5-scoped-deathrattles.md)，40专项、5033全量及83示例内部通过。逐项保存能力与次数，按自身/友方及印刷/授予筛选，自然死亡保留冻结自身政策；固定轮次、生命周期、恢复及磁力/星舰组合共用原流程。内核96/schema93、代表包56，观察51/命令7保持；天灾巨魔/丛林之魂/树人三条必要代表，299记录/300定义。R-140待校准；下一项02l-02技能主体身份与可恢复激活，M0/M6/M7保持缺口。



M5-13d-02l-02：[技能主体身份与可恢复激活](m5-power-payloads.md)，70专项、505相关回归、5103全量及84示例内部通过。根冻结完整on_use能力，批次/捕获/实际执行分别记录，保留原回调窗口、一次支付/使用/根完成及激励；选择、同实体嵌套、普通/保留回溯和严格恢复接入公共解释器。内核97/schema94、代表包57，299记录/300定义与观察51/命令7/replay1保持；本批没有新增重复次数机制或真实卡。R-141待国服校准；下一项02l-03场上技能重复，其后回合结束类别与TIME_064混合声明，M0/M6/M7保持缺口。



M5-13d-02l-03：[场上英雄技能效果重复](m5-power-repeats.md)，74专项、505相关回归、5177全量及85示例内部通过。冻结场上完整来源与max设值计划，每能力全部重复后再下一能力；首次保留原窗，额外执行读最新局面，各保留结果共享原根计划，一次支付/使用/根完成及激励保持。内核98/schema95、代表包58，只新增TOY_528伴唱机至300记录/301定义/14choice-only；观察51/命令7/replay1保持。R-142待国服校准；下一项02l-04回合结束主体类别与身份，TIME_064混合、条件/种族及M0/M6/M7继续保留。



M5-13d-02l-04：[自然回合结束主体分类与身份](m5-end-turns.md)，83专项、620相关回归、5260全量及86示例内部通过。显式EndTurnSpec区分自然结束能力与普通监听/计时，冻结完整有序批次和能力/玩家效果身份，捕获与实际执行分离，记录完成/守卫跳过/终局中断；保留普通原窗、有限次消费窗、英雄技能旧守卫及混合监听位置。诊断控制不增玩法检查点或游戏事件，完整接受证明保持到旧反应结束、时钟继续之前。内核99/schema96、代表包59；六条既有结束trigger迁移声明，没有新增真实卡，300记录/301定义/14choice-only保持，观察51/命令7/replay1保持。R-143待国服校准；本轮不含重复或主动API，下一项02l-05结束次数/期限，TIME_064混合后置，M0/M6/M7仍未完成。



M5-13d-02l-05a：[自然结束重复公共机制](m5-end-turn-repeats.md)，83专项、887相关回归、5343全量及87示例内部通过。每主体冻结场上/持续及有期限玩家来源的all/minion范围与max计划，完整主体/重复位置及共享首次守卫收据；保留原混合监听槽位、普通/有限/HP首次窗口，额外实际开始读取新局面。有限次绑定逐能力真实消费事件，HP拒绝不可达挂起首次Invoke；首次守卫失败整组跳过，完整接受证明贯穿最后额外及尾普通反应，owner自然时钟不重复。诊断控制不增玩法检查点或游戏事件。内核100/schema97/代表包60，300记录/301定义/14choice-only及观察51/命令7/replay1保持，无新真卡。R-144为内部候选待国服校准；下一项02l-05b ICC_901与CATA_480必要代表，主动/异阶段/TIME_064混合后置，L05及M0/M6/M7仍未完成。



M5-13d-02l-05b：[自然结束重复必要代表](m5-end-turn-representatives.md)，34专项、1176相关回归、5377全量及88示例内部通过。仅新增独立ICC_901与CATA_480完整原始pins：3费1/5场上all来源、3费圣骑士神圣法术玩家minion期限来源；复用公共max计划、一次原守卫/旧槽位、额外新局面、完整接受证明与owner时钟。CATA本地duration3含施放所属回合结束、剩余1先覆盖本批再到期；来源资格、广义范围、合并和Paladin Aura容量/重复实例政策仍未国服校准。内核100/schema97/观察51/命令7/replay1保持，代表包61，302记录/303定义/14choice-only；旧300完整行与M0历史及冻结inventories保持。R-145为代表profile，R-144为公共依赖；下一项02l-05c主动/异阶段结束能力公共入口，保留scope，TIME_064混合更后，L05及M0/M6/M7未完成。



M5-13d-02l-05c：[主动与异阶段结束能力公共入口](m5-end-turn-activations.md)，91专项、1094相关回归、5468全量及89示例内部通过。独立Selector/Request/profile与issuer身份，支持五类载体的owner/selected范围、真实cause、条件和同回合多根/嵌套；自然结束仍保留旧混合槽位及owner时钟，主动调用不制造结束事件、普通监听或计时。首次原窗/有限次消费窗、共享真实守卫收据、额外新局面和完整Finish接受证明保持；双父身份支持守卫监听三层嵌套。内核101/schema98拒绝旧1～97，代表包61及302完整记录/303定义/14choice-only、观察51/命令7/replay1保持，没有新真实适配。R-146内部候选待国服校准；1159条前审及历史依赖观察保持，下一项05d主动producer资格/选择政策与必要CATA_472代表；固定多轮特殊来源及TIME_064混合继续保留M5，L05/M0/M6/M7未完成。



M5-13d-02l-05d：[公共候选与随机结束producer](m5-end-turn-producers.md)。公共纯结构候选查询与随机一次producer已内部验收。五类载体owner/selected范围、current/printed/active依据、休眠/存活/消费与presence政策由注册profile声明；不执行主体条件、每物理载体一个权重。随机选择与主体/完整max计划同窗接受，外层每次实际亡语各自抽选，内层额外结束执行保持原选择；空池保存空根且不消耗RNG。producer_mode、原request、完整有序候选、完整selected及MT19937前后状态进入历史与Finish证明；原窗口重算池/主体/计划、局部重演抽样，允许后续主体合法推动RNG，不提供未签名存档来源认证。仅新增CATA_472灵感之槌完整raw/pin实验适配，active/live/unconsumed友方随从及选中后的全部结束主体为R-147本地政策，待CN校准。内核102/schema99拒旧1～98，代表包62及303记录/304定义/14choice-only；观察51/命令7/replay1保持。旧302完整行、历史前审和M0/frozen inventories保持；L05/M0/M6/M7及长期目标未完成。05e四族混合重复声明、共享生命周期和独立接受窗口组合，必要TIME_064来源由公共机制表达；固定多轮producer政策继续保留M5，当前仅有战棋固定两轮证据，不能借此宣称构筑来源已完成。



02l-05d实际终态：81专项、1316相关回归、5549全量及90示例内部通过；专项23.619秒、相关588.131秒、全量1883.387秒。原生8动作/53事件/3随机根/4位置/4选择，真实Maul外层两次独立抽选；全部waiting恢复、回放及模块CLI通过，owner时钟[3,3]。旧86示例摘要共同行为字段保持；仅内部证据，R-147未CN校准。



### 2026-10-03 M5-13d-02l-05e 四族混合重复组合（内部验收）



四族混合重复公共组合已内部验收。同一载体四个独立附件共用生命周期，各族分别捕获自己的max计划、主体和执行身份，跨族不共享次数或用途；已接受计划保留，后接受根按新局面重新捕获。保留各族不同首次窗口、额外新局面、既有检查点/支付/用途/时钟；补齐战吼整次出牌接受收据、亡语单调分配计数及贯穿整批的原接受证明和重复来源身份校验，拒绝中途裁队列/缩次数和跨族附件ID冒充。选择恢复、回溯、异常回滚及玩家隔离复用公共解释器。仅新增TIME_064必要静态四声明，无自身战吼/亡语/结束主体；TIME_064e只作独立原始证据，没有可执行附魔适配。内核103/schema100拒绝旧1～99，观察51/命令7/replay1保持，代表包63，304完整记录/305定义/14choice-only。旧303完整行、历史前审与M0/frozen inventories保持。R-148为内部组合契约，依赖各族既有规则，未国服校准。下一项02m-01：条件/种族重复来源前审与公共匹配契约，先确定条件对象、印刷/当前依据和接受窗，再补必要机制；动态主体授予、固定多轮结束producer、特殊来源及M0正式池/M6国服校准/M7批量接卡继续保留，不能以本批归档宣称重复整族完成。



02l-05e实际终态：65公共专项、16代表专项、1611相关回归、5630全量及91示例内部通过；公共57.706秒、代表18.090秒、相关727.359秒、全量2009.161秒。旧87示例摘要共同行为字段保持，schema及摘要哈希变化另行登记；原生全部waiting恢复、独立注册表回放与模块CLI通过。仅内部证据，R-148未国服校准。



M5-13d-02m-01-A1：[法术学派与双窗口](m5-spell-match.md)。M5-13d-02m-01-A1法术学派匹配及双窗口接受证明已内部验收。match与既有职业条件取交集，玩家提交与场上较晚窗口分别捕获全部匹配来源；单位/空/反制及FinishPlay后续接保持明确接受义务，嵌套真实出牌按有序帧义务关闭。完整状态仅存活动证明，历史保留紧凑收据；原提交目标绑定，较晚合法重定向保持。内核104/schema101/观察52，命令7/replay1及代表包63/304记录/305定义/14choice-only保持。本批未接代表卡，R-149未国服校准。下一项必要RLK_541 A2，再做持续条件/另一物理实体及逐族匹配；其他费用/主体/周期/+1/CAST轴与M0/M6/M7继续保留，不能宣称条件重复整族或最新正式池完整。



### 2026-10-04 M5-13d-02m-01-A2 必要法术学派代表



M5-13d-02m-01-A2必要RLK_541代表已内部验收。仅新增完整维萨鲁斯raw/PIN与奥术any总2的公共声明；旧304完整行、M0历史runtime及冻结inventories保持，公共内核没有新增分支。内核104/schema101/观察52/命令7/replay1不变，代表64及305记录/306定义/14choice-only。真实同职业奥术、非奥术/无学派、完整max来源、反制、离场、晚窗口、恢复/回放及玩家隔离已验证。R-150仍只覆盖真实付费手牌profile并依赖R-149，自动/effect/draw/history来源及CN/正式池未覆盖。下一项持续来源条件/另一实体B1，再做逐族匹配B2；其他费用/主体/周期/+1/CAST轴及M0/M6/M7继续保留。



合同见[必要代表验证](m5-spell-match-representatives.md)。



实际验收：[终态证据](../outputs/v109-verification.json)。15代表专项、770相关回归、5678全量及93示例内部通过；代表8.390秒、相关245.647秒、全量1177.607秒。原生10动作/49事件/7casts/2真实待选，次数[2,1,1,1,2]，每根仅支付一次；waiting独立注册表恢复/clone/回放与模块CLI一致。89旧/90当前摘要共同行为与字段保持，1265历史文件字节保留，历史v105存档与A1实际after逐字段比对，仅命名identity不同。只覆盖manual paid hand profile，R-150未国服校准，自动CAST与完整合法池未覆盖。



M5-13d-02m-01-B1：[持续来源条件与另一实体](m5-repeat-source-conditions.md)。M5-13d-02m-01-B1持续来源条件与另一物理实体已内部验收。实际board spell_repeat在原较晚接受窗完整查询见证，再与职业/学派相交；显式profile区分presence，another排除实际carrier ID。两原窗口及当前存续来源静态身份绑定，包括全部false；历史不重判当前见证。内核105/schema102，观察52/命令7/replay1及代表64/305记录/306定义/14choice-only保持；没有新增真实卡。仅manual paid hand profile，R-151未国服校准。下一项B2-01战吼原接受对象与物理self/种族匹配公共契约，再按族推进；费用/主体/周期/+1/CAST、动态主体、固定多轮producer、M0/M6/M7继续保留。



注册自定义RepeatWitnessProfile后再注册引用它的印刷声明；未知profile在register_card及动态授予时明确拒绝。条件声明入口为`RepeatMatchSpec(source_eligibility=RepeatSourceEligibility(profile_id="repeat.witness.controlled", tribes_any=("dragon",), exclude_carrier=True))`，再组合到`SpellRepeatSpec`。`exclude_carrier=False`表达普通控制存在，True排除实际物理载体。玩家SpellRepeatModifier与物理特定卡重复不接受此来源条件；公开match继续只含静态接收参数，私有schema102要求完整source_eligibility字段。接口仍待本批验收，不代表国服presence或完整条件重复整族已验证。



B2-01战吼匹配公共接口见[接受对象与条件契约](m5-battlecry-matching.md)。`BattlecryRepeatSpec`新增friendly/self与独立接收种族/持续来源条件；原接受对象使用物理载体当前面，历史不重判当前见证。玩家政策公开scope/match，观察v53；法术公开match形状保持。实际验证和下一项仅见[项目状态](project-status.md)，本段不作本批验收声明。



## 连击匹配扩展



`ComboRepeatSpec`增加friendly/self范围和独立match，`ComboRecipient`分别描述提交与实际窗的物理对象。场上来源可声明受注册profile约束的持续条件，玩家政策仅允许friendly及接收种族。玩家观察55只公开scope与detached recipient_metadata；完整原证明、来源条件和内部ID不进入玩家接口。两窗、空/取消、用途、完成义务及保留范围见[公共契约](m5-combo-matching.md)，实际验证以[项目状态](project-status.md)为准。



## 亡语匹配扩展



`DeathrattleRepeatSpec.match`组合原接受载体的印刷种族与持续来源条件，仍与既有kind、friendly/self和printed/granted范围相交。以下声明表达：控制另一只合格野兽时，友方龙的印刷亡语执行两次。



```python

from hs_sim.engine import (

    DeathrattleRecipientMetadataFilter, DeathrattleRepeatMatchSpec,

    DeathrattleRepeatSpec, RepeatSourceEligibility,

)



repeat = DeathrattleRepeatSpec(

    repetitions=2,

    origins=('printed',),

    match=DeathrattleRepeatMatchSpec(

        recipient_metadata=DeathrattleRecipientMetadataFilter(tribes_any=('dragon',)),

        source_eligibility=RepeatSourceEligibility(

            profile_id='repeat.witness.controlled',

            tribes_any=('beast',),

            exclude_carrier=True,

        ),

    ),

)

```



把声明放入来源随从的`CardDefinition.deathrattle_repeats`；动态授予使用既有`GrantDeathrattleRepeat`。`exclude_carrier`排除次数来源本身的物理ID，不是接收亡语的随从。来源载体限随从；玩家效果可声明接收种族，但不能声明物理self或持续来源条件。自然死亡与主动触发分别使用冻结死亡面及原live接受面，逐个亡语能力保存计划；已接受后不因见证或载体变形重算。完整接口和边界见[亡语契约](m5-deathrattle-matching.md)，实际验证仅见[项目状态](project-status.md)。





B2-04英雄技能持续来源条件与完整根证明已内部验收（109/schema106），R-155未国服校准。公共接口见[英雄技能匹配](m5-hero-power-matching.md)，实际结果与已知差异只见[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)；下一项B2-05结束回合来源匹配。



B2-05结束回合来源条件及完整原批次证明已接入110/schema107，尚待内部验证。公共接口见[结束回合匹配](m5-end-turn-matching.md)；执行结果、剩余边界与下一项见项目状态及机制清单。R-156未国服校准，本批不扩充真实卡。





## 手动法术费用匹配扩展



`RepeatMatchSpec.recipient_cost=RepeatCostFilter(...)` 可声明printed、local、submitted_quote和window_quote费用区间；费用与职业/学派/来源条件取交集。window_quote必须指定已注册 `CostQueryProfile`，默认 `repeat.cost.accepted_hand` 明确保存原手牌下限，不在墓地伪造手牌状态。实际付款余额差不能代替报价，actual_payment尚不支持。



扩展通过公共声明与效果表达，不修改接受窗口、不重新消费已接受计划；完整报价与支付前/真实回溯证明由内核负责。公开字段仅basis、minimum、maximum、quote_profile_id，完整来源/局面不得进入玩家DTO。接口及独立剩余范围见 [费用条件契约](m5-spell-cost-matching.md)；实际验收见 [项目状态](project-status.md)。



## 自身回合历史条件



使用 `query_previous_owner_turn(context.state, player_id, PlayedTypeQuery(...))` 读取最近已关闭自身区间的完整匹配结果，或以 `query_for_definition` 构造种族/学派查询。提交后换形不改原卡面，未知信息明确报错。通过结果组合公共效果；不要自己用turn-2、实时实体或获取时间推断过去。完整历史不进入玩家观察。字段和启动阶段见[自身回合历史契约](m5-owner-turn-history.md)；条件式固有费用由下面的公共声明表达。



## 条件式固有费用与付款证明



`CardDefinition.intrinsic_costs` 默认为空元组；可从手牌打出的随从或法术以有序 `IntrinsicCostSpec` 声明最近已关闭自身回合的同类型提交条件及set/delta/minimum操作。定义声明与完整true/false历史事实由内核冻结，未知信息完整校验后报错。物理报价按base→intrinsic→有序本地附件→外部费用→最终下限执行；生成报价在intrinsic之后应用initial CostSpec。不要直接修改实体缓存或自行扫描今日状态重判原费用。



原费用条件的local读取含固有阶段的本地结果，printed/submitted_quote/window_quote依据保持。所有真实手牌根保存完整付款接受证明，非Spell的诊断尾部贯穿Finish及其反应；所有挂起选择要求完整原边界证明，包括合法空owed。扩展不操作这些私有事实、不新增事件或移动支付窗口；完整契约、严格schema和玩家信息边界见[固有费用 API](m5-intrinsic-costs.md)，实际内部验收状态见两份台账。actual_payment、自动CAST费用匹配及其它历史条件仍未支持。



## 间接战吼的独立条件与目标



通过 `BodyTargetProfile(origin='indirect_battlecry', acceptance_window='indirect_invocation')`、`IndirectBattlecryBinding` 和每个实际声明的 `BodyTargetBinding` 注册完整来源，再由 `TriggerBattlecry(..., profile_id=...)` 进入公共 producer。场上授予只查结构；每次真实调用用 `BodyPlayReference` / `IfBodyCondition` 读取自己的冻结条件，目标从该调用的新局面确定，使用声明式规则或显式玩家原输入注册。不要复用付费证明、给玩家暴露物理附件 ID，或自行拼写解释器 Finish 控制步骤。来源、生命周期和恢复约定见[公共契约](m5-indirect-body-targets.md)。





自动整牌的物理主体通过 `GeneratedWholeTargetBinding` 和完整 `BodyTargetBinding` 注册自己的 generated_whole profile，由 `ReplayWholeCards(body_target_profile_id=...)` 在四种实际物理来源的安装结束窗接受。各主体条件、候选/目标和RNG独立，族重复和保留结果复用原选择；普通根用 body_only/preserve_root/explicit_root 分离，没有普通主体时不预选普通目标。指定主体模式另传 body_target_id，不能借用付费或间接绑定。恢复、玩家信息及未支持来源见[公共契约](m5-generated-body-targets.md)。


`generated_after_install_v1` 和 `generated_battlecry_repeat_after_install_v1` 可使用同一 `GeneratedWholeTargetBinding`，两者均建立实际连击身份且只执行一次；后者只让战吼接收重复政策。不要为了获得身份选择族重复 profile；来源许可、空/disabled 及恢复约定见[生成族身份契约](m5-generated-single-family.md)。

生成抉择随从使用同一 `ChooseOneSpec`，来源可传 `ReplayWholeCards(physical_branch_id=...)`，省略则读取安装前的随机/合并政策。独立目标绑定只能 `preserve_root`，沿原分支目标域；目标和各授予主体在入场后接受。重复/保留结果不重选分支，后一child重新接受，不借用手动或施法身份。抉择普通根不能另声明独立印刷battlecry/Combo；已有入场授予入口沿原公共来源权限，不作为继续扩张组合的要求。详见[生成抉择契约](m5-generated-choose-one.md)。


## 历史战吼的独立主体接受

先注册 `BodyTargetProfile(origin='historical_battlecry', acceptance_window='historical_invocation')`，再注册 `HistoricalBattlecryBinding(carrier_card_id, profile_id, declaration_card_ids=...)` 明确该载体允许的完整历史声明范围。五个实际历史重演接口均可传 `profile_id`；单项沿原 random/explicit 策略，集合与有界序列沿原 random 策略。已有绑定的载体不能省略 profile 退回旧路线，越界或未知声明使动作回滚，不过滤候选。

每次实际调用接受自己的执行席位、出牌前缀、水晶和声明门槛及目标域，`BodyPlayReference` / `IfBodyCondition` 沿真实记录读取条件，不伪造原付款或原手牌位置。current 序列转控以后下一主体使用新执行者自己的可见 DTO，历史归属保持；原接受不被之后等待/监听改写。自己的完整序列、父子完成和 Finish 由公共解释器处理，不手工拼写控制步骤。见[历史来源、目标与恢复契约](m5-historical-body-targets.md)。


## 英雄的分类结束与有限能力

英雄定义可使用 `TriggerSpec("turn_ended", "body", end_turn=EndTurnSpec())` 或 `LimitedTriggerSpec("turn_ended", "body", uses=2, end_turn=EndTurnSpec())`；普通事件的通用有限规格也可声明在英雄上。动态授予使用现有GrantTrigger/GrantLimitedTrigger，由公共附件保存独立ID与次数。主动/随机结束接口需要在EndTurnSelector中显式列出 `hero`，原五类调用不会自动扩展。关键词Spellburst/Frenzy权限保持；不要直接修改英雄缓存或把已接受原主体改绑到替换后的英雄。原消费前守卫、消费后回调、继承、到期与信息边界见[英雄公共契约](m5-hero-classified-triggers.md)。


## 玩家合并抉择政策

按[公共契约](m5-player-choose-both.md)使用`AddChooseBothModifier`及`RemoveChooseBothModifier`，显式声明kinds/origins。默认手牌随从/法术；自动来源和英雄技能须明确授权。不要在卡牌回调中扣用途、查询时消费、按最新局面重选已接受分支，或绕过公共完成证明。实际验证和后续只见两份最新台账。

## 实体预选与来源继承

使用`SetChooseBranch(card_ref, branch_id, origins=('hand',), combination='override')`，传入公共CardReference或HeroPowerReference；None清除。分支必须属于实际卡面，自动/物理/技能入口须明确授权，不能直接修改Entity或用回调扣用途。current复制及冻结材料保留，base/重置/变形清除，兼容回溯形态沿公共重绑；未知声明明确报错。

历史新施法用`RecastSpell(..., branch_policy='inherit')`；四物理profile用`ReplayWholeCards(..., physical_branch_policy='inherit')`，不可同时提供physical_branch_id。默认current沿旧重选，各child读取自己的原记录。不要给其他producer借用此参数，也不要将来源调用的继承永久安装为实体配方。完整用法和界限见[公共契约](m5-choose-branch-state.md)；特殊来源只按具体真实需求补充。

## 历史来源的分支继承

批量使用`RecastFromHistory(..., branch_policy='inherit')`；整牌法术使用`ReplayWholeCards(..., spell_branch_policy='inherit')`。两者默认current。四物理来源仍单独声明physical_branch_policy；混合批次分别用实际原Cast/Play occurrence，不按同名牌猜分支，不在回调中操作RNG或付款。新窗口允许当前合并政策覆盖继承；目标与主体内选择仍新执行。root/child/原窗口由内核保存，卡牌不能擦除收据、提前Finish或改待选批次。详见[公共接口与限定来源](m5-history-branch-replays.md)；特殊producer/技能替换和真实例外继续待补。上方U17A/B当时待补的批量历史及整牌法术已由本层接入，实际位置以两份台账为准。

## 生成和技能替换的预选

`AddToHand/AddToDeck/AddHeroPower/ReplaceHeroPower(..., choose_branch=ChooseBranchSelection(...))`在首个观察事件前原子设置配方。`ReplaceHeroPower(..., branch_policy='inherit', branch_map=...)`转移实际旧技能的当前保存配方；默认clear。要冻结原激活先用`capture_power_choose_branch(ctx.state, registry, ctx.power.id)`，再经`transfer_choose_branch`显式安装。两种来源不能混为“最近一次分支”，也不能同时给inherit和literal。历史发现可用`DiscoverSpellHistory(..., branch_policy='inherit')`，默认current。

映射按原全部普通分支及combined有序声明，目标可换卡面主体及ID，普通和合并角色保持。复制其他状态、费用、次数或RNG由各原模块负责，卡回调只返回效果。见[完整公共接口](m5-choose-branch-producers.md)。上方原阶段尚待补的生成/技能继承已由该接口覆盖，真实例外及特殊混合根仍须各自契约。

## 抉择声明的现有边界

使用 ChooseBranch(id, label, behavior_id, targeting=None, target_rule="any_entity", requires_board_space=False) 及 ChooseOneSpec(branches, combined)。同一根共享公共报价和付款，Game.quote_cost(entity_id) 不接收分支参数。分支效果中的真实资源消耗仍通过公共效果表达。

不要给同一抉择根追加磁力、裂变、静态奥秘/任务/持续载体或独立印刷战吼/连击声明；注册表明确拒绝。不存在分支价格、install_then_branch 或裂变分支映射接口。普通 ShatterSpec(left_card_id, right_card_id) 沿原模块。后续具体卡的秘密选择/延迟行为按真实卡文和既有公共模块判断，不能套用已撤下的静态载体实验。


## 独立祈求

从 `hs_sim.engine.invoke` 使用 `InvokeProfile(version, families)`、`GalakrondFamily(hero_class, forms, gift_behavior)` 及 `Invoke(player_id, source_id=None, count=1)`。五族必须明确声明；注册后由内核保存主物理归属、两级进度和成功历史，不在卡牌回调里修改这些字段。收益组合原公共效果，不调用当前技能来代替家族收益；未知适配明确报错。两次祈求用 count=2，各次分别接受，等待不重复计数。裸授予祈求标签拒绝。完整范围和生命周期见[祈求契约](m3-invoke.md)，不按该入口展开组合矩阵。


## 独立青玉

使用 `Registry.register_jade_family(JadeGolemFamily(id, version, forms))`声明四档真实模板，卡牌返回`SummonJadeGolem(player_id, source_id=None, family_id='jade.classic', count=1, position=None)`。共享计数和出生身材由内核负责，卡牌不能直接改写历史/base字段或用Buff伪装固有身材。普通复制、移区、沉默和复活复用原入口；未知模板明确报错。范围与待CN校准政策见[青玉基础契约](m3-jade.md)，不沿此入口展开组合矩阵。


经典克苏恩注册CthunProfile(version, card_ids)并返回GrowCthun(player_id, attack, health, source_id=None, taunt=False)；必要地卜师用+1/+1及taunt=True，不提供任意关键词字段。公共cthun_ritual_stats读取理想累计，cthun_attack_at_least读取真实阈值；卡回调不直接改写历史或永久行。普通局部buff仍用原效果，不把实体实际身材当作仪式bank，也不另造组合/任意授予。嘲讽由同一成长历史与原关键词附件表达，卡回调不改写能力戳。破碎之劫四部件规则仍未验收；限定起始卡组资格已有独立公共查询，完整身份池继续开放，见[独立成长契约](m3-cthun.md)。

## 起始卡组生成资格

GenerationContext(target_id, mode, starting_decks=None)中的starting_decks必须是两个有序字符串tuple；纯resolve_candidates调用需明确player_id，有条件候选在事实未知时明确报错。正常构筑入口自动绑定两份DeckSpec，卡牌回调不得根据当前牌库或祈求/仪式次数补写起始资格。TransformPoolTarget声明必须带原执行player_id，冻结材料使用GenerationContext.to_dict/from_dict严格编码；不要绕过公共候选查询静默删除未适配的合法卡。详见[范围与接口](m3-starting-generation.md)。


## 本回合结束的临时手牌

从hs_sim.engine.temporary_hands导入ReplaceHandWithTemporaryCopy(player_id, source_player_id, source_id)，仅声明当前行动玩家与对手的复制来源；原组保存／取回由内核负责。ReturnTemporaryHand属于真实ExpireTurn的内部工作，不能作为卡牌主体或选择项。不要直接改历史／手牌或拿整局回溯代替取回。当前清理含后来取得且仍持有的卡，精确CN政策仍开放；见[临时手牌契约](m3-temporary-hands.md)。


## 下次本人开始的原牌库临时手牌

从hs_sim.engine.temporary_deck_hands导入ReplaceHandWithTemporaryDeckCards(player_id, count, source_id)，仅声明实际当前行动玩家的原牌库来源。内核负责原组保存、物理候选／获取身份、真实下一本人开始及取回；不要用Draw或Copy伪装借牌，不要按卡名、实体ID或全局回合＋2自行清理。内部ExpireTemporaryDeckHands／ReturnTemporaryHand不作卡牌主体或选择项；当前资格／容量及CN政策见[独立契约](m3-temporary-deck-hands.md)。

## 最终起手来源

独立 E.T.C. 侧板由sideboards.py保存玩家原构筑成员与消费槽，DeckSpec显式输入侧板；主牌库大小不计成员，普通禁限/职业/符文/合计副本检查复用。DiscoverSideboard生产原RequestChoice，选中走普通AddToHand；共享选择、获取、回放与私有信息边界，不增加组合矩阵。布局schema170，规则181/效果175，观察74/命令11保持。详见[基础契约](m3-sideboard-basics.md)，完整正式禁牌/其他来源和国服校准仍开放。

从hs_sim.engine.starting_hands导入ReplaceHandWithTemporaryStartingHand(player_id, source_id)；starting_hand(state, player_id)仅供可信卡牌行为读取完成构筑开局的固定组，不把返回值给玩家。场景或未完成开局明确拒绝；不从当前实体读取历史材料，不自行安排额外结束任务。原保存／严格请求／回放及待CN政策见[最终起始手牌契约](m3-starting-hands.md)。


## 独立场上交互物

使用CardDefinition.interactable=InteractableSpec(behavior_id)声明固定的0费、投入本人一张手牌、每真实本人回合一次的物体。载体须保持不可收藏的0/1 MINION和corpse_value=0，其余普通生命周期字段为默认；不允许把普通随从能力或其他声明挂到这个载体。InstallInteractable负责独立安装，UseInteractable负责外部动作，主体回调只返回已有公共效果；原解释器处理反应、随机、等待和Finish。

玩家命令为type=use_interactable、object=公共物体句柄、card=本人手牌句柄，仍需当前revision。投入不支付该牌费用，不打出、施放、弃牌或执行其效果。身份、次数、恢复和明确待CN政策见[交互物契约](m4-interactables.md)，实际验证只登记两份项目台账。


## 固定对战面板

由宿主在Scenario或MatchSetup指定board_id正整数，None表示未指定，构筑对局中的当前事实必须与配置一致。使用register_board_card_family(BoardCardFamily(...))声明面板编号与完整印刷随从形态的有限表；所有定义和主体先注册，族的政策版本与映射进入指纹。原创建、场上变形和存储换面会先解析形态，原支付、关键词、生命周期与解释器继续执行，不写任意公式或额外结算器。

只在卡牌ID属于已注册族时解析；缺少必要面板或没有当前编号映射明确报错。玩家观察根公开board_id，没有新命令。两项必要转校生实验映射、原始证据、保存版本及待CN政策见[面板契约](m3-game-boards.md)，完整映射、正式面板池与其他模式仍开放。

原玩家目标输入已支持既有交互物最小行；不要向该行添加战斗属性、费用、主体或宿主历史。原物理事实和真实付款前完整投影仍须一致，详见[原玩家输入契约](m4-interactables.md#原玩家输入的惰性行)。

临时法力复用原resources.py账户，获取及恢复/解锁/水晶变更后的规范化不再按永久水晶成长cap裁剪；原refresh_mana、临时优先消费、付款证明、回合交接和玩家资源视图共享。永久max_mana仍受mana_cap约束，可用mana可超过；不新增账户/付款器/效果/事件。语义版本prototype-v248/core-effects-v242，schema218及观察75/命令11/replay1布局保持。详细边界与未校准项见[临时法力与水晶上限](m2-temporary-mana-over-cap.md)。

每玩家手牌容量由hand_capacity.py查询PlayerState.hand_cap可空覆盖，Ruleset.max_hand仅默认；SetHandCapacity支持set/raise，原18处交付/整组/补满检查实时读取收件方。原交付、烧牌、物理身份/时序/付款/选择/回放共享，没有新交付器；场景初始容量严格，降低上限不主动删除已持有手牌的政策待CN。玩家公开hand_cap有效值，顶层limits.max_hand保留默认；完整状态及原目标DTO共同绑定，schema219拒旧1～218、prototype-v249/core-effects-v243/观察76，命令11/replay1保持。详见[每玩家手牌容量](m3-per-player-hand-capacity.md)。


逻辑认输为独立座位动作Concede，复用原事务与终局中断管线；非主动方/换牌/待选也可提交，原付款与未完成工作保留真实中断收据，不以英雄死亡替代。玩家命令只含type=concede及原revision，不读取隐藏条件；见[独立认输契约](m3-logical-concession.md)。实际进度与下一项只在两份台账。

需唤醒原休眠实例时，使用`hs_sim.engine.dormancy.AwakenCapturedMinion(MinionReference.capture(entity), entity.dormancy.id, source_id)`，不要仅保存可被重用的实体号。原休眠变化后请求失效，等待/回放和永久载体限制仍沿公共层。个人施法资格与原事件材料的表达见[原生触发契约](m3-reactive-growth-cards.md)。

原抽牌或施法观察对象需跨反应保留复制材料时，使用`CapturedCardCopyMaterial.capture(context.state, source)`配合原`CopyCard`；HAND/DECK可current，GRAVEYARD只base，完整设费在创建通知前安装。不要从后来同名实体补材料或手动改新能力的来源；公共current复制层负责原生自身绑定。不同目标伤害用RandomDamageBatch，精确范围与待校准政策见[契约](m3-trigger-source-cards.md)。

普通生成须在公共候选层排除来源及已审核的同卡版本，版本族独立于生成权重和构筑同卡身份。真实起始卡组与当前种族条件继续组合既有查询，边界见[来源排除与条件消费者](m3-generation-source-exclusion.md)。

真实冰川急冻使用有限 DiscoverFromPool.freeze_summoned 声明，把原选中召唤请求的第0次实际交付连接到公共冻结。原队列、收据、连续驻留及待国服窗口见[发现后原召唤冻结契约](m3-discovered-summon-freeze.md)。

生命仪式用有限 summon_copy_stats 手续把原实际生成手牌连接到2/3复制召唤；原ChoiceResult、真实创建对象、材料/数量接受窗与满手政策见[发现手牌复制契约](m3-discovered-minion-copy.md)。

实际战吼需把其随机手牌武器连接到独立连击时，用GenerateBattlecryWeapon绑定context.battlecry.id和普通GenerateFromPool请求，再用combo_weapon(context, registry)取得原HAND CardReference，交给BuffStoredCard。有限请求只支持一张可收藏武器，不借用实体游标或其他族batch_id；真实物理主体、空/烧牌、原连续驻留及待CN重复政策见[武器输出契约](m3-generated-weapon-combo.md)。

发现并直接召唤后给原对象设值可用DiscoverFromPool.set_summoned_stats=SummonStats(attack,health)。该有限请求仅用于一次普通带原因的场上随从发现，默认None；不要用summon_copy_stats替代、不要搜索后来同名战场对象。实际原交付、连续驻留、属性层及待CN政策见[契约](m3-discovered-set-stats.md)。

单方揭示可用RevealRandomDeckCard(player_id, kind=CardType.SPELL, source_id=..., on_result=...)；奖励用deck_reveal_result(context.event)读取原牌/费用，不重查后来牌库。不要给玩家传原物理引用，也不要用手牌报价推断牌库费用；有限范围、空池、公开卡面及待国服政策见[契约](m3-deck-reveals.md)。

地标原生过量给英雄可用DamageExcessToHero(minion_ref, amount, source_id, kind=DamageKind.EFFECT)，来源必须是真实LOCATION；默认SPELL仍须真实法术。不创建CastSpell或cast_id，不用事后已受伤害猜分流。三形态原随机/最低剩余生命抽选及原实体升级见[契约](m3-silvermoon-locations.md)。
