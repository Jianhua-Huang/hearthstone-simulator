# 真实卡牌内容包

[龙卵/栉龙完整源及雏龙](../data/cards/native-deathrattle-memory-v1.json)和[适配](../hs_sim/cards/native_deathrattle_memory_cards.py)以原附件保存成长/原抽牌关联；动态网页漏值不覆盖固定2/1依赖。公开数值、私有手牌驻留与准确窗口见[契约](m3-native-deathrattle-memory.md)。

[灰烬虫完整源](../data/cards/full-board-dormancy-v1.json)及[适配](../hs_sim/cards/full_board_dormancy_cards.py)仅声明真实无限休眠/满面板条件。地标占位、当前控制者、原实例唤醒与复制/沉默边界见[契约](m3-full-board-dormancy.md)。

[原生出牌奖励完整源](../data/cards/played-minion-keywords-v1.json)及[适配](../hs_sim/cards/played_minion_keyword_cards.py)表达黑市监管者与梦缚迅猛龙；原出牌/驻留边界及明确未支持接收形态见[契约](m3-played-minion-keywords.md)。

[基础角色完整源](../data/cards/basic-hero-roles-v1.json)和[适配](../hs_sim/cards/basic_hero_roles.py)接通规范默认英雄/技能及指定衍生物；图腾须保留完整基本身份，食尸鬼复用原印刷主体。默认、强化/皮肤和正式池的范围见[契约](m3-basic-hero-roles.md)。

[三张连续来源与生命分流](../data/cards/native-conditional-sources-v1.json)及[适配](../hs_sim/cards/native_conditional_cards.py)保留完整原行；持续条件交原法强/费用/英雄光环，真实技能先抽牌再原HP伤害，不替换成测试白板。角色默认绑定与精确CN边界见[契约](m3-native-conditional-sources.md)。

[四张1费根卡及神圣衍生法术](../data/cards/one-cost-basic-effects-v1.json)由[薄适配](../hs_sim/cards/one_cost_basic_cards.py)共用原支付、目标、区域和属性效果；卡池仍完整保留未知候选，未将部分1费池注册为生成源。配方边界见[契约](m3-one-cost-basic-cards.md)。

[米尔雷斯材料](../data/cards/mirrex-native-hand-mirror-v1.json)与[适配](../hs_sim/cards/mirrex_native_cards.py)只声明原生连续HAND镜像，保留独立来源与3/4附魔；费用/固有能力沿原冻结印刷卡面，公共生命周期及待CN政策见[契约](m3-native-hand-mirrors.md)。

[雷弗拉尔配方](../data/cards/renferal-native-traps-v1.json)及[适配](../hs_sim/cards/renferal_native_cards.py)以原完成出牌历史计划成长数，共用私有困住生产者和旧手牌门禁/时钟；重复战吼不造出牌。来源和信息边界见[契约](m3-renferal-hand-traps.md)。

[原生复生/FIRE抽牌配方](../data/cards/native-reborn-fire-draw-v1.json)和[适配](../hs_sim/cards/native_reborn_fire_draw_cards.py)只描述真实原生政策与延系奖励；旧定义新空字段有明确稳定PIN视图，非空声明仍签名。抽到时自动施放的官方历史要求与待校准边界见[契约](m3-native-reborn-fire-draw.md)。

[原攻击者与存储成长配方](../data/cards/stored-growth-native-effects-v1.json)及[stored_growth_native_cards.py](../hs_sim/cards/stored_growth_native_cards.py)显式适配真实原攻击者设生命与同一物理载体的三区域结束成长；零攻击数据依据明确，公共属性、存储增益和生命周期继续共享，见[契约](m3-stored-growth-cards.md)。

[野兽原生触发配方](../data/cards/beast-trigger-native-effects-v1.json)及[beast_trigger_native_cards.py](../hs_sim/cards/beast_trigger_native_cards.py)接入护甲增长/随机攻击、个人施法圣盾、潜行攻击后伤害及三次本人开始休眠；四根没有新衍生物，公共战斗/关键词继续共享。原通知与待国服政策见[契约](m3-beast-trigger-cards.md)。

[原生入场配方](../data/cards/entry-native-effects-v1.json)及[entry_native_cards.py](../hs_sim/cards/entry_native_cards.py)组合斥候原手牌变形、特莱斯塔斯真实预备/恶魔召唤成长及死烂巨口完整邪能野兽家族。三只衍生物保留野兽＋恶魔和全部印刷关键词；主体、取值窗及保存边界见[契约](m3-entry-native-cards.md)。

[真实召唤受益配方](../data/cards/summon-beneficiary-native-effects-v1.json)及[summon_beneficiary_cards.py](../hs_sim/cards/summon_beneficiary_cards.py)接入残躯、暴龙和纯2/1恐龙鱼人，复用原水蛭、生命转移与有序召唤。整组实际交付后的额外效果及当前提供者政策见[契约](m3-summon-group-bonus.md)；精确国服窗口和完整池仍待校准。

[整局洗牌配方](../data/cards/shuffle-native-effects-v1.json)及[shuffle_native_cards.py](../hs_sim/cards/shuffle_native_cards.py)接入灌林追踪者的原生费用；全部既有历史在获取前也有效，注册不代替完整来源和国服校准。未分类插入/临时返回使相关报价明确报错，边界见[契约](m3-semantic-deck-shuffles.md)。

[固定牌库与历史配方](../data/cards/deck-history-native-effects-v1.json)及[deck_history_native_cards.py](../hs_sim/cards/deck_history_native_cards.py)组合原抉择、实际抽牌、原成功入场、当前种族和跨区增益。克罗米不同身份预算/顺序尚未国服实证，灌林追踪者完整源保留但不注册；边界见[契约](m3-deck-history-native-cards.md)，实际进度仅在两台账。

真实6费召唤依赖的[完整固定源配方](../data/cards/six-cost-native-effects-v1.json)与[six_cost_native_cards.py](../hs_sim/cards/six_cost_native_cards.py)接通原生资源、伤害、复活、费用、战斗、属性、复制、延系及奥普所需刀扇。复用原执行器，边界见[契约](m3-six-cost-native-cards.md)；实际进度仅在两台账。

森林再生、焚火林地和寒霜冰爆连同真实分支/形态使用原HAND进度、匹配抽牌、弃牌与战吼；仅寒霜冰爆补有限施法进度SPELL转MINION配对。完整原行、choice-only描述与待CN时钟政策见[持牌抽牌契约](m3-held-draw-forms.md)。魔网枢纽属于真实整局升级族，尚未作为基础抽1注册。

古神降临、泰坦降临、翡翠厚赠、拟态、拉法姆人梯和巫卜复用原抽牌、费用、类型门禁、当前复制与原驻留消灭。有限手牌禁用和不同费用抽取的完整配方/边界见[抽牌保留契约](m3-draw-retention-limits.md)；活动提前发放与正式合法池仍分开核实。

原物理抽牌组的六个真实消费者共用原draw_one、费用、区域和选择解释器；原始牌库使用真实开局事实，不以同名牌猜身份。完整配方、实验边界及特殊手牌转交缺口见[抽牌组契约](m3-physical-draw-groups.md)。实际进度及验收仍只在两台账维护。

`original_material_cards.py`接入烧灼映像、辛达苟萨的胜利、劫持、永时火焰箭、灼烧之风和潮起潮落的已声明本地路径；入场前复制授予、原死亡基础复制、成功弃牌及原墓地法术归还见[契约](m3-original-material-spells.md)。`examples.card_original_materials`用真实玩家命令验证；烧牌复制/附魔/重置等未校准边界继续登记，不以接入数宣布完整支持。

`health_beneficiary_cards.py`接入灵魂联结、协作火花、引雷针、炽火缠身、班纳布斯的故事和致命配方，补完整EDR_850pe狼并复用已有TLC_249炽烈烬火。原健康击杀/伤害数量及整组物理抽牌受益见[契约](m3-health-draw-beneficiaries.md)，`examples.card_health_beneficiaries`只使用实际卡牌定义。

`health_resource_cards.py`接入炎魔之火、先行打击、强固、烧蚀毒雾、饮血术和灵界打击，直接复用手牌未选择报价、具名续接、原抽牌/延系/吸血与技能复原；没有新公共请求或状态。完整窗口见[条件与资源法术](m3-health-resource-spells.md)，实际玩家命令示例为`examples.card_health_resources`。

`spell_target_cards.py`接入熔岩涌流、时间停滞、奥术弹幕、精确射击和吞噬五张完整真实法术。最低生命逐波、原手牌中点、不同目标冻结及原健康批击杀抽牌见[有限法术目标契约](m3-spell-target-sequences.md)；`python -B -X utf8 -m examples.card_spell_targets`只使用实际卡牌定义。

`health_sequence_cards.py`按完整原行/PIN接入爆裂射击、焚烧、封冻沉眠、烟雾熏蒸、新生闪电和感染吐息，复用原健康、抽牌、延系、种族与归因召唤。已有水蛭不重复定义。请求窗口和待CN政策见[真实伤害续接契约](m3-health-sequence-spells.md)，`python -B -X utf8 -m examples.card_health_sequences`经真实玩家命令演示。

`hand_mirror_cards.py`依完整原行/PIN接入影蔽袭击者和血蓟幻术师，复用原区域移动和真正的复制交付。`CopyMinion.on_summon`仅绑定实际成功复制体，隐藏标记沿普通能力生命周期；完整窗口及待CN政策见[复制续接与隐藏分身契约](m3-copy-followups-hidden-pairs.md)。`python -B -X utf8 -m examples.card_hand_mirrors`经玩家DTO演示，无实验卡。

`demon_zone_cards.py`用完整原行/PIN表达小鬼地狱火、小鬼马仔及其具名底牌、雷兹迪尔和魔神暴龙。原生存储亡语明确声明许可，延系共用上一自身回合历史；入口、原事实和待CN边界见[存储亡语契约](m3-stored-deathrattles.md)。`python -B -X utf8 -m examples.card_demon_zones`通过真实命令展示。

`native_end_cards.py`及`death_followup_cards.py`按[结束主体](m3-native-end-cards.md)/[原生资格与复活复制](m3-death-followup-cards.md)表达神秘恐魔、绝息剑龙、贪婪的地狱猎犬、残暴的魔蝠；原生亡语资格的官方历史修复和有限公共查询见[契约](m5-resurrection-followups.md)。`python -B -X utf8 -m examples.card_demon_dependencies`展示真实迫攻吸血、随机伤害、原始卡面复活与同体复制。

`death_followup_cards.py`复用[过滤抽牌减费](m3-spell-sequences.md)和原物理区域效果，表达受难的恐翼巨龙、固执的守护者、好奇的探险者；[契约](m3-death-followup-cards.md)明确实际抽取引用、牌库顶批次及对手私有手牌边界。`python -B -X utf8 -m examples.card_zone_death_followups`展示原实体减费后的真实付款与销毁后的实际剩余牌序。

`death_followup_cards.py`按[原生亡语契约](m3-death-followup-cards.md)接入伪装的特工、孢子尖牙怪、扭曲的树人和邪恶荒裔怪，依赖复用原邪恶短刀并注册官网关联的另一张完整匕首卡面。`python -B -X utf8 -m examples.card_native_deathrattles`以玩家合法命令展示落位归属、死亡来源剧毒、双手牌减攻与复生后的装备/加攻；精确CN政策仍另行校准。

`granted_deathrattle_cards.py`及`death_followup_cards.py`复用既有配方扩展绵羊面具、洛戈什的奋战和邪魔仆从；同批[真实命令示例](../examples/card_deathrattle_effects.py)展示设值后死亡伤害、自动随机加攻及原手牌实体招募。接口分别见[授予亡语](m3-granted-deathrattle-cards.md)与[冻结死亡事实](m3-death-followup-cards.md)，实际验收仍只在两台账。

`granted_deathrattle_cards.py`按[法术授予亡语契约](m3-granted-deathrattle-cards.md)接入剑龙骑术与完整可收藏剑龙，原行/pin在`granted-deathrattle-effects-v1.json`；`python -B -X utf8 -m examples.card_granted_deathrattles`经真实玩家命令展示增益、嘲讽、死亡和原位置召唤。已知内部窗口与国服校准限制见契约。

`fixed_companion_cards.py`按[契约](m3-fixed-companion-cards.md)接入动物伙伴、兽群、哈尔拉兹和四个完整衍生物，原行/pin在`fixed-companion-effects-v1.json`；`python -B -X utf8 -m examples.card_fixed_companions`展示真实伙伴、光环/冲锋及填手/突袭。

`native_weapon_turn_draw_cards.py`按[契约](m3-native-weapon-turn-draw-cards.md)接入两把吸血武器、焦油与泰兰，完整原行/pin在`native-weapon-turn-draw-effects-v1.json`；`python -B -X utf8 -m examples.card_weapon_turn_draw`展示真实攻击、原死亡属性与物理抽牌。

`native_random_damage_cards.py`按[原生随机伤害契约](m3-native-random-damage-cards.md)接入投弹者、女祭司、黑翼龙与萨萨里安，完整原行/pin在`native-random-damage-effects-v1.json`；`python -B -X utf8 -m examples.card_native_random_damage`展示单位分配、单次打击及真实亡语/复生。

`history_recovery_cards.py`按[历史返还契约](m3-history-recovery-cards.md)接入佳莉娅与卡格瓦，完整原行/pin在`history-recovery-effects-v1.json`；无需新增内核效果。`python -B -X utf8 -m examples.card_history_recovery`展示真实雪人复活及硬币/火球按次返还。

`physical_zone_cards.py`按[物理区域契约](m3-physical-zone-cards.md)接入末日守卫、蒸汽清洁器与作战动员，完整原行/pin位于`physical-zone-effects-v1.json`；官方childIds明确绑定普通新兵和圣光的正义。`python -B -X utf8 -m examples.card_physical_zones`展示实际弃牌、召唤装备及真实传送门生成后的牌库清理。

`attack_followup_cards.py`按[原生攻击续接契约](m3-attack-followup-cards.md)接入雷加尔、芬杰和审判官；完整原行/pin在`attack-followup-effects-v1.json`，复用具名核心闪电箭。`python -B -X utf8 -m examples.card_attack_followups`使用玩家命令展示相邻奖励、原物理招募及普通/跟随攻击，具体窗口与待CN边界见契约。

`trigger_source_cards.py`依照[原事件与复制契约](m3-trigger-source-cards.md)接入个人施法、物理抽牌、失盾与原费用触发，完整原行/pin位于`trigger-source-effects-v1.json`。普通current复制/变形的原生自身来源统一绑定接收实体，外部授予归因保持；`python -B -X utf8 -m examples.card_trigger_sources`通过真实玩家命令展示新旧路径。

`reactive_growth_cards.py`按[原生触发契约](m3-reactive-growth-cards.md)区分当前召唤、原出牌、个人施法、健康结果、冻结死亡与技能完成。完整原行/pin在`reactive-growth-effects-v1.json`；`python -B -X utf8 -m examples.card_reactive_growth`通过玩家命令展示普通触发和原休眠唤醒。逐次施法事实不自动等同个人出牌，实际范围与证据只在两台账维护。

`python -B -X utf8 -m examples.card_khadgar_portals`通过真实金萼幼龙、灌注技能、洗入、抽牌和传送门自动施法展示卡德加的来源归属。示例明确使用实验龙池，完整正式池和可达来源不能由一次演示推定；原始来源及回溯收据的表达见[契约](m3-standard-portal-summon-source.md)。

`static_provider_cards.py`使用`static-provider-effects-v1.json`的完整原行/pin声明原生持续来源；参数包括显式法强、受伤/装备条件、当前种族属性、顺劈、卡牌召唤倍增和本体入伤增加。`python -B -X utf8 -m examples.card_static_providers`通过普通玩家命令展示；卡德加的旧生产者覆盖仍须按[来源契约](m3-static-provider-cards.md)核对，不能以声明存在代替完整路径支持。

`qualified_next_cards.py`接入狐人老千、洞穴专家、提克迪奥斯、速逝鱼人和环形山鳄鱼，完整原行/pin在`qualified-next-effects-v1.json`。`python -B -X utf8 -m examples.card_qualified_next`经玩家命令展示费用资格、生命支付、持续英雄免疫和真实开始禁疗；临时牌生产夹具明确为非正式卡牌且不进入生产注册表。材料、期限和待国服校准政策见[契约](m3-qualified-next-card-costs.md)。

显式玩家健康来源保存原物理事实与受益方，普通玩家效果默认保持原语义；逻辑伤害委托原健康层，下一真实对手期间复用原实例/费用/时钟。严格捕获、解码、玩家隔离和统一格式常量见[玩家健康来源契约](m3-player-effect-health-source.md)，实际进度与验收仅在两台账。

实际下一次技能费用、整局随从设费、开局双方上限/充能水晶和本方治疗增加沿现有公共层组合，扩展约定见[持续费用与真实开局契约](m3-persistent-economy-cards.md)。实际进度、验证与下一项仍只在两台账维护。

`targeted_battlecry_cards.py`接十二个完整定向战吼及既有开局硬币映射，完整原行/pin在`targeted-battlecry-effects-v1.json`。`python -B -X utf8 -m examples.card_targeted_battlecries`通过玩家命令展示手牌增益/换面/复制、两项选择、原目标转控、消灭及击杀奖励，逐位置独立恢复/clone/回放。规则与硬币映射边界见[契约](m3-targeted-battlecry-cards.md)，不认证正式卡池或CN校准。

`conditional_battlecry_cards.py`接入十六个完整原生战吼，原行/pin在`conditional-battlecry-effects-v1.json`。`python -B -X utf8 -m examples.card_conditional_battlecries`通过玩家命令运行条件伤害/吸血、物理抽牌、技能历史、属性、原owner到期及牌库底费用，逐稳定位置独立恢复/clone/回放。目标与当前材料见[契约](m3-conditional-battlecry-cards.md)，不认证正式卡池或国服校准。

`simple_battlecry_cards.py`接入八个原生战吼根，完整原行/pin在`simple-battlecry-effects-v1.json`。`python -B -X utf8 -m examples.card_simple_battlecries`通过玩家命令展示武器/英雄攻击、敌方冻结、同时伤害、生命损失、物理野兽抽牌、灌注与真实吸血，逐稳定位置独立恢复/clone/回放。实际边界见[战吼契约](m3-simple-battlecry-cards.md)，不认证正式卡池或国服校准。

`death_followup_cards.py`接入八个原生亡语根，完整数据及DBF564/1730依赖证据在`death-followup-effects-v1.json`。复用完整奥术飞弹并接入5/3灰烬使者；`python -B -X utf8 -m examples.card_death_followups`经玩家命令展示伤害、突袭死亡、装备攻击、灌注与牌库费用。材料/区域契约见[亡语续接](m3-death-followup-cards.md)，不认证正式卡池或国服校准。

`basic_trigger_cards.py`接入八根当前核心基础卡及DBF63321明确关联的完整医生token，原行/pin在`basic-trigger-effects-v1.json`。`python -B -X utf8 -m examples.card_basic_triggers`展示过载/治疗条件、神圣逐次完成、英雄攻击/被攻击、对手实际手牌招募与邻接光环；具体边界见[契约](m3-basic-trigger-cards.md)。

`native_end_cards.py`接入[原生结束效果卡](m3-native-end-cards.md)，数据`native-end-effects-v1.json`包含十二根、两新token及已存在CAP_107t完整证据。`python -B -X utf8 -m examples.card_native_ends`通过玩家命令展示结束增益/伤害/治疗、原数量召唤、双方时钟/硬币和复生；不认证正式卡池或国服校准。

`stat_draw_cards.py`的[七根属性与抽牌法术](m3-stat-draw-spells.md)保存完整raw/pin于`data/cards/stat-draw-effects-v1.json`；`python -B -X utf8 -m examples.card_stat_draw`以玩家命令展示生命设置、极值目标、手牌增益、原抽牌与灌注，不认证正式标准卡池或国服时序。

`spell_sequence_cards.py`接入七根[伤害序列与抽牌法术](m3-spell-sequences.md)，完整raw/pin在`data/cards/spell-sequence-effects-v1.json`。`python -B -X utf8 -m examples.card_spell_sequences`展示七根的玩家命令；兆示士兵使用原实验生成池，不能据此认证完整标准可达池。精确国服时序仍待校准。

`conditional_health_cards.py`接入[条件法术](m3-conditional-health-spells.md)：背刺未受伤目标、眼棱原手牌边缘费用与吸血、噬灵瘟疫敌方随从限定分摊、迦罗娜的奋战传说目标/交易、净化吐息原伤害死亡续接，以及麦迪文的胜利传说载体费用。当前无稀有度证据与完整原行在`data/cards/conditional-health-effects-v1.json`；未知仍明确报错。`python -B -X utf8 -m examples.card_conditional_health`经玩家命令展示真实价格、移除和治疗，实验不认证正式标准套牌或国服校准。

`native_followup_cards.py`安装固定当前Core原生声明，并将月亮井的伤害与后续治疗、眺望陆地/血虫感染的抽牌与两次归因召唤分段组合。完整CAP_107t火炮手复用随机随从能力伤害；EDR_810t饱胀水蛭使用[角色生命上限转移](m2-character-health-theft.md)，不能当作普通0/2或伤害吸血。每个实际结束主体在执行时取当前场面，仍用原EndTurnSpec。原行/依赖DBF关系与审核配方保存在`data/cards/native-followup-effects-v1.json`；`python -B -X utf8 -m examples.card_native_followups`经玩家命令展示声明、唤醒、实际衍生主体与便携检查点，混合职业实验不认证正式标准套牌。

`health_followup_cards.py`安装固定当前Core卡面并复用原完整主体/目标/连击声明，元数据和套牌身份单独校验。六个新法术只组合原Damage/Batch、Heal、Draw、固有吸血、RandomDamage、Buff和命名InvokeBehavior；愈合按原目标当前max_health请求完整治疗，急流及裂隙在前段反应完成后读取续接对象。原公共内核负责支付、死亡、等待、随机和临时到期。`data/cards/health-followup-effects-v1.json`保存完整源行和审核配方；`python -B -X utf8 -m examples.card_health_followups`用真实卡经玩家命令与稳定位置恢复/克隆/回放展示，实验场景与当前候选存在不认证正式标准套牌或国服校准。

`infinite_secret_cards.py`将END_024无穷烈焰接入原自然结束奥秘窗口，以当前剩余生命最高原随从组请求[显式无限伤害](m2-infinite-health.md)。完整raw与审核数值政策保存在`data/cards/infinite-secret-effects-v1.json`；政策尚未国服校准，不把本地显示阈值当伤害。`python -B -X utf8 -m examples.card_infinite_secret`展示真实雪人承伤和银色侍从圣盾防止，全部稳定位置独立恢复/clone/回放；没有专属最先触发排序。

`reactive_secret_cards.py`将JAIL_315秘法误导及TIME_620失时往生接入原奥秘、捕获变形和归因复活；完整数据含真实DBF796绵羊，见[契约](m4-reactive-secrets.md)。TIME资格读取原实际出牌/入场/死亡，不另存部署回合或同名实体缓存。`python -B -X utf8 -m examples.card_reactive_secrets`通过双方玩家命令展示绵羊继续攻击及次回合雪人重召唤，逐稳定位置恢复/clone/回放；当前正式池与国服校准仍开放。

`excess_secret_cards.py`为真实CORE_LOOT_101声明原SecretSpec及[一次SPELL预算分流](m2-excess-damage.md)，完整审核卡面为`data/cards/excess-secret-effects-v1.json`。来源法伤一次、两份承受规则分别处理，全部实际结果交公共内核。`python -B -X utf8 -m examples.card_excess_secret`用真实血法师/雪人及银色侍从验证预算、圣盾和英雄余量，全部稳定位置独立恢复/克隆/回放；实验不代表正式卡池或国服时序认证。

`core_secret_cards.py`按[当前核心奥秘契约](m4-core-secrets.md)接完整身份/条件/主体及真实老鼠，复用已有完整水元素。四个核心别名与旧版共用唯一性key，其他来源元数据取固定37.0原行；不会根据文案自动生成脚本。`python -B -X utf8 -m examples.card_core_secrets`以两个真实卡牌实验场景运行七个根及全部稳定位置恢复/克隆/回放；爆炸符文数值分流由上述独立内容模块补充，K13a历史证据保持。

`return_hand_cards.py`组合[原回手续接](m3-return-followups.md)，完整数据为`data/cards/return-hand-effects-v1.json`。暮光主母按owner、摇摆矿锄按controller回手；欺诈之网在实际成功后接EDR_523t，次元武器匠/沙漏侍者捕获原手牌数值受益对象。`python -B -X utf8 -m examples.card_return_hand`通过双方玩家命令运行全部根卡、真实武器攻击/亡语及自然结束，逐位置恢复/克隆/回放；混合职业50法力场景不认证正式套牌。

`quantity_cost_cards.py`组合[伤害次数与区域费用](m3-damage-packets-zone-costs.md)，原固定配方为`data/cards/quantity-cost-effects-v1.json`。TIME_047、JAIL_204、TIME_715、JAIL_514沿原接受操作数计算价格；CATA_452及真实CATA_452t、CATA_568分别接完整召唤/抽牌主体。`python -B -X utf8 -m examples.card_quantity_costs`经双方玩家命令执行回合切换、真实攻击与全部根卡，各位置恢复/克隆/回放；混合职业50法力实验场景不代表合法标准套牌。

接卡流程见[补卡计划](card-integration-plan.md)，本轮范围为国服固定正式补丁的标准根卡及实际可达内容，狂野后置。历史`hs_sim.engine.representative.build_registry()`保留固定代表包身份；新增卡牌由独立入口构建：

```python
from hs_sim.cards import build_registry
registry = build_registry()
# 交给已有 Game.from_scenario / Game.from_decks 与 PlayerPort。
```

卡牌仍使用原CardDefinition、公共效果和唯一结算器。当前内容包名称含preview，不是正式标准/狂野合法池声明；不能把内容包里存在某定义作为可构筑或已国服校准的证明。

`python -B -X utf8 -m examples.card_batch`通过固定座位玩家JSON执行新接入随从及攻击，并在稳定边界检查独立注册表恢复、克隆和回放。

`data/cards/keyword-minions-v1.json`保存有限审核的完整源记录、指纹和显式数值/关键词配方；加载器核对总指纹和逐卡数据，文本不自动成为行为。核心版和原版的套牌身份按逐卡审核声明共享。生成候选元数据可登记，但现有受限发现池不自动扩大。

`data/cards/health-effects-v1.json`保存完整审核的伤害/治疗卡文配方。`health_cards.py`把有限不可变参数转换为原Damage、DamageBatch、Heal、HealBatch、Draw与SplitDamage，公共内核仍负责死亡、资源、触发、随机和等待。主体入口显式区分法术、战吼及亡语；法术伤害/治疗种类和派系单独声明，战吼不继承法术伤害加成。目标域、当前随从生命/英雄护甲及亡语执行方的回合条件也由逐卡配方声明；不读取印刷文本生成脚本。

群体伤害使用原同时批次，正常休眠及非随从场位被排除。有限配方里有后续抽牌时仍由公共队列顺序执行，伤害触发真实选择会保留后续动作；重复战吼与复制/沉默使用原能力实例和生命周期。单个卡牌必须声明其全部主体及必要依赖，部分熟悉文字不能替代未实现效果。行为ID包含配方摘要，内容版本随实际执行语义升级，恢复/回放要求匹配完整注册表。

`python -B -X utf8 -m examples.card_health`通过玩家JSON执行新接入战吼、法术和真实战吼/亡语来源，各稳定位置检查独立恢复、克隆与回放。

`data/cards/economy-effects-v1.json`保存固定37.0源记录及显式抽牌/资源配方。`economy_cards.py`复用Draw、DrawMatching、GainArmor、GainTemporaryMana、Overload、GainResource、Buff及健康效果；行为不得直接修改状态。印刷法强与零费缺标签单独核对，流放沿原接受的手牌位置条件，受伤与英雄攻击监听明确筛选执行者及事件目标。普通支付、死亡、触发和来源生命周期继续由内核负责。

指定牌库底抽取通过原MoveCard(draw=True)/DrawRecord执行；有限InvokeBehavior续接在前一次抽取及其反应完成后重新读取当前牌库底，原抽到时施放、替补抽取、满手烧牌、疲劳、待选和回放共用原路径。不重排整个牌库来伪造抽牌，也不提前捕获下一张底牌。定量补手遵循原DrawToHandLimit的执行窗计数约定；定向抽取依据原印刷类型/费用/派系/种族查询，缺匹配跳过，不用普通抽牌替代。精确国服时序仍须校准。

`python -B -X utf8 -m examples.card_economy`通过玩家JSON执行护甲/抽牌、牌库底抽取、装备和英雄攻击；稳定边界检查独立恢复、克隆与回放。示例场景不等于正式标准牌组。

`data/cards/utility-effects-v1.json`保存完整的增益、召唤、移除卡效与必要衍生定义。`utility_cards.py`将逐张审核的有限配方转为原公共效果；每段使用有固定身份的InvokeBehavior在执行时重新读取对应范围。例如先召唤再增益时包含刚生成的随从，伤害触发的等待恢复后也使用新的局面。指定场上目标离场后沿原效果资格跳过，不能自动改为手牌增益；手牌范围明确使用BuffStoredCard及捕获物理引用。

目标条件使用原TargetPredicateSpec，保持当前属性/种族、可选目标、支付前校验与原输入证明一致；战吼无目标可出牌，法术按必要目标拒绝。可交易与预备复用原HandActionSpec，预备的1表示最低投入，不是固定支付一费，实际支付、减费和当回合锁定仍由原机制负责。衍生物的普通关键词及自身主体必须一起接通，生成时不额外执行战吼。

公共DestroyBatch接收唯一有序的场上对象ID，先通过原Destroy/DestroyLocation标记全部随从和地标，再交原解释器的一次死亡检查；休眠与失效对象仍跳过，不杀后续亡语新生成的实体。RandomReturnToHand沿原随机候选/空池/RNG记录选择，再用ReturnToHand(to_owner=True)交回原拥有者；满手失败仍为原当前控制者的普通死亡。两者使用原事务、帧、死亡协调器和玩家投影，没有另一套结算器或新账户。保存字段/布局保持schema266，新指令集合与语义由core-effects-v307的mechanics签名保护，旧签名存档拒绝。

metadata.py依据固定客户端CARD_RACE表的m_isRaceTagId解释副种族布尔标记，与CARDRACE取去重并集；例如亡灵/野兽、亡灵/龙和恶魔/机械。完整来源在data/cards/race-metadata-v1.json，未知主种族或非0/1值明确报错，不从卡名猜类型。历史代表工厂的定义不改写，内容包的费用/构筑身份/职业等仍复用原元数据解码；版本差异与校准另行登记。

python -B -X utf8 -m examples.card_utility通过玩家JSON验证先召唤再增益、消灭后亡语及同批群体消灭，每个稳定位置独立恢复、克隆与回放；仍为实验场景，不是正式标准牌组。

`data/cards/integration-target-cn37.json`记录本轮官方目标与本地来源的差异；它不是现有M0完整支持认证。实际完成、验证结果与下一项仍只在原两份台账维护。

`next_cost_cards.py`组合[原邻居、种族修正和条件账户](m3-submitted-neighbors-next-costs.md)，完整固定配方见`data/cards/next-cost-effects-v1.json`。灵敏的厨师只改原邻居的仍有效HAND生命周期；暴怒邪吼者的下一恶魔修正没有伪造到期；恐惧畏缩先执行真实3点法术伤害，再建立本回合下一野兽修正。伺机待发的缺失COST主标签通过明确审核的0费配方处理，不给所有缺失费用行默认0。`python -B -X utf8 -m examples.card_next_costs`经玩家命令展示实际完整路径及各稳定位置的恢复/克隆/回放，仍为混合职业实验场景。

`presence_cost_cards.py`将[完整当前条件/被动费用配方](../data/cards/presence-cost-effects-v1.json)接入公共费用机制。三种真实当前条件见[契约](m3-current-presence-costs.md)；戈隆巨人、恐怖海盗复用原最近本人出牌费用和当前装备武器攻击力，重生的翼手龙使用原CORPSES账户，被俘的纳斯雷兹姆使用原双方随从费用光环及预备。纳斯雷兹姆的完整raw有预备文本与DECK_ACTION_COST=1而没有PREPARE主标签，审核配方显式声明，运行时不从文案推导规则。`python -B -X utf8 -m examples.card_presence_costs`通过玩家命令展示两张同名龙的费用、实际神圣/暗影施法和外部光环顺序，各稳定位置独立恢复/克隆/回放；它仍是混合职业实验场景。

`recruit_followup_cards.py`使用[原招募成功续接](m3-recruit-followups.md)，将真实JAIL_516、DINO_131、JAIL_906的授予主体绑定到成功招募的原实体；摩拉格召回的是新印刷实体，具有原预备及亡语定义。角斗开战先招募本人随从，再为对手创建完整5/5潜行老虎，空本人牌库不取消对手召唤。TLC_366/TLC_600/TLC_816通过原IntrinsicCostSpec(delta=-2)消费最近已关闭自身回合的种族/学派事实；当前回合使用和普通召唤不冒作已关闭历史。完整固定卡面见`data/cards/recruit-followup-effects-v1.json`，所有主体仍交公共内核执行。

`data/cards/recruit-effects-v1.json`保存完整招募、抽到时主体、衍生物和历史计费配方。`recruit_cards.py`只使用已有公共能力：SummonFromZone按印刷费用/种族筛选，逐次移动原物理实体并完成反应；高阶女巫维洛先手牌后牌库各招募一个恶魔，召唤不执行战吼。此数量解释与[官方卡页](https://hearthstone.blizzard.com/en-us/cards/129850-archwitch-willow/)的卡文和两个恶魔的描述一致，具体国服接受窗口仍须校准。

抽到时召唤的随从以原`DrawRecord`和重复手牌进度验证本物理牌真实进入手牌，再揭示、`SummonStoredCard`移动原牌并为原抽牌者补抽。卧底小鬼的接收者是抽牌者的对手，owner保持；不伪造出牌、法术CAST或战吼。满手烧牌不召唤/补抽，接收方满场则留手揭示并补抽，复用[现有内部政策](m3-draw-summon-basics.md)，不能据内部结果认证国服边界。

橡果、夺得装备、疾疫和奥术绊索衍生法术声明原`CastWhenDrawnSpec`，手动主体和真实抽到时主体共用；奥术绊索使用原CAST的RandomSplitDamage，整次法强只加到总预算。疾疫伤害原抽牌者的当前英雄；伪装的医生亡语洗入死亡时控制者的牌库。洗入次数仅属于根牌，衍生法术没有复制根牌的洗入主体。

过载、本局英雄技能、本人邪能施法、本回合双方死亡、套牌之外使用和当前牌库数量复用既有有限计费声明及原历史。科技恐龙需要真实构筑开局的物理起始集合，只有卡名场景的非起始费用明确拒绝；不猜为零。控制局面的两波伤害分别读取当时场面，中间亡语新随从参与第二波。`python -B -X utf8 -m examples.card_recruits`通过原玩家命令展示抽取、召唤和计费；实验场景不等于正式标准套牌。

`data/cards/conditional-effects-v1.json`和`conditional_cards.py`接入明确审核的条件、普通抉择、关键词选择、当前复制与完整命名卡牌生成。固定脚本映射只返回公共效果，不读取文本执行或修改状态；未知脚本及pin不匹配明确拒绝。普通抉择声明原ChooseOneSpec的两分支和显式combined主体，目标属于具体分支，支付和分支捕获使用原内核。普通关键词选择使用RequestChoice，不能冒充发现；真正牌库发现沿原物理引用选择，保持其余卡、私有选项、当前容量及等待恢复。

原真实条件分别读取当前手牌派系/种族、剩余手牌、场上存活种族、有效装备或原结束窗口，不用印刷卡名猜状态。伤害后条件通过命名InvokeBehavior续接重新读局面；自动施法仍复用原cast上下文。奥术飞弹使用RandomSplitDamage及真实SpellCastRecord，对完整法术预算加一次法强后执行单位随机包，不使用非spell的SplitDamage替代。

致命药膏使用[requires_weapon资格](m3-manual-play-eligibility.md)，主体用原ModifyWeapon处理执行时当前武器，不要求玩家选中武器。蝙蝠面具用SetStats后接`hs_sim.engine.effects.FillBoardWithCopies(target_id, player_id)`；该指令在执行时按原rules.max_board和当前场位计算请求数，交原CopyMinion处理每份当前复制，保留原满场/目标离场/生命周期和事务政策。没有卡牌代码硬编码场位上限或另一套召唤器。

`python -B -X utf8 -m examples.card_conditions`通过玩家JSON演示隐式装备条件、原牌库取牌、关键词选择、普通抉择和授予亡语；各稳定位置独立恢复、克隆及回放。场景不宣称正式套牌合法，取牌的抽牌事件政策和精确双选窗口仍需国服校准。

`data/cards/zone-effects-v1.json`及`zone_cards.py`是手牌/牌库复制、移动、弃牌、增益和当前条件的有限真实消费者。自动复制用[CopyMatching](m3-zones.md)，主动手牌目标只读本人DTO并排除来源自身；所选手牌已离开则不重新操作其新区域。洗入保持原实体，随后抽牌复用Draw；当前卡牌材料与费用、隐藏信息、未知内容拒绝和随机继续由公共内核维护。

普通区域增益捕获CardReference，保持原牌库顺序并只处理明确的随从子集。延系直接使用[原前一自身回合查询](m3-kindred-basics.md)，不增加Keyword枚举或成立标记；内容元数据的ALL=26来自原固定CARD_RACE/种族枚举。原伤害结果通过命名on_result续接表达死亡缠绕、猛击及通窍，区分原目标和健康结果；新的印刷随从用Summon，不用对墓地实体调用CopyMinion。精确反应/重定向和复制保留政策继续由M6校准。

`python -B -X utf8 -m examples.card_zones`通过玩家JSON演示隐藏自动复制、地标手牌增益、邪能牌复制及原手牌洗入/抽取。各稳定位置检查独立恢复、clone和回放；本例本身没有挂起选择，选择恢复由专项验证，不将内部随机当作玩家选择。

`tools/import_card_xml.py`将固定提交的主CardDefs导出规范为调查目录。读取前后核对源SHA与显式build，异常也关闭文件；未知数值标签按enumID保留，未知类型明确标识，COST空标签不自动设0。CARD_SET取源中的实际数值，CORE前缀不替代现行/退池归属。原XML保留，规范化器不解析或执行规则主体，也不宣称动态依赖/正式合法池完整。

全目录调查命令：

```powershell
python -B -X utf8 tools/inventory_card_effects.py --data <完整cards.json> --output outputs/<新批次>/inventory.json
```

输出保留每个原记录、其他模式、关系和未知依赖。分类只提供人工接卡提示：战吼/亡语等入口与主体效果分开；系列前缀仅为提示；所有候选仍需审核。目录中的注册标记也不等于效果完整、正式合法或官方验证。动态生成关系另行追踪，不能据RELATED_CARDS宣称可达内容已穷尽。

标准候选目录命令：

```powershell
python -B -X utf8 tools/inventory_standard_cards.py --data <完整cards.json> --policy data/cards/standard-candidate-policy-cn37.json --output outputs/<新批次>/standard-inventory.json
```

候选按明确CARD_SET与逐张提前可用例外筛选，保留源中全部记录、未实现候选、未核实活动资格及跨系列静态依赖提示；不以CORE前缀或当前已注册集合替代标准卡池。XML Card标签、收藏/显示关系只作为可追踪线索，循环有界、未解引用保留；动态生成及真实依赖另审。该目录始终不是正式合法池或完整效果覆盖证书，不用于构建仅含已实现卡的正式DeckPolicy/发现池。
