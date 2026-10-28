# 点燃的原生伤害值与新洗入实体

[完整源包](../data/cards/ignite-native-growth-v1.json)保留SW_110点燃的原始记录、TAG_SCRIPT_DATA_NUM_1=2及两份完整中英文官网主面。官网仅省略动态@，共享check_face既有的显式脚本数字显示归一化处理此差异，原记录及全部规则文字不改。它是标准过去法师来源的实际依赖，不新增标准组牌根，也不认证完整过去池或最新国服版本。

GrowingDamageProfile(card_id, initial_amount, policy='shuffle_base_plus_one')只声明本卡实际需要的固定加一、新副本政策。固定policy字面量进入asdict和注册表指纹，与相同初始数字的ReturningDamageProfile区分。既有必须携带亡语、攻击或其它生成参数的profile保持严格；只有原返回余量profile与新的递增profile允许普通新牌没有额外材料时使用各自印刷默认。

GrowingSpellDamageValue沿既有AbilityInstance.spell_base_value保存card_id、amount、parent_cast_id。它不新增Entity/GameState顶层字段或第二套成长账本。每次真实CAST接受时，native_spell_values把原物理牌的材料冻结到原SpellCastRecord.native_spell_value；整次施法及后续洗入始终读取这一冻结值，不能从后来另一张同名牌或当次实际伤害反推。

DamageGrowingSpell(cast_id)核对原活跃且已开始payload的施法，从已冻结材料或印刷2取得基础伤害；原目标必须匹配接受时的完整角色分配，再交普通SPELL Damage。原分配在payload后失效时按本地政策跳过原伤害，仍续接洗入；接受前目标合法性和反制继续由原施法管线负责。精确离场、换英雄及死亡反应窗口暂不作国服校准结论。

ShuffleGrowingSpell(cast_id)在普通伤害及其反应之后读取同一原施法基础值，创建基础值加一的GrowingSpellDamageValue。全局法伤、物理牌局部法伤、来源/目标倍率、护盾、免疫或防止均不写入下一张基础值。两个印刷点燃各为2→3，不存在按名称升级整手牌/牌库的全局计数。

公共create_deck_card新增可选内部native_spell_value参数，默认None时旧AddToDeck路径保持。新点燃沿同一容量检查和随机插入分配新实体，先装入原生材料，再沿旧创建/入库事件发布；观察者和真实等待不能先看到一张无参数的新牌。满99张、未知卡、费用/普通创建附件、RNG和事务均继续由旧管线处理。原点燃留在原结算区域，不回收原物理对象，也不继承其折扣或额外法伤附件。

原值校验沿真实cast_history迭代检查父链：每个父CAST必须已开始原payload且没有失败，卡面和原来源一致，数字等于父基础值加一；父引用严格递减，首项必须由印刷2生成3。禁止环、未来父记录、外卡参数和来源冒用，不使用递归或新全局来源账本。普通状态/历史及FrameCodec共同检查现存附件和冻结材料；这些是内部一致性证明，不认证被外部整体重写的未签名存档。

当前复制沿原完整材料保留数值并重新分配物理附件；基础复制/普通新牌采用印刷2。整卡历史重放使用选中那一次原手牌出现的冻结材料，打印2、生成3及其后续4相互独立；反制的生成牌也按原冻结或原物理材料保留3。不会因原卡后来被施放或移区而取另一个同名副本的值。玩家仍只通过既有base_damage数值投影看到允许公开的信息，不获得parent_cast_id、原附件、施法账本、RNG或解释器帧。

core-effects-v790/schema614增加两个Effect及一个注册payload，拒旧1～613；公共观察/命令/回放布局保持。单卡原生适配只组合公共请求，不处理扣血、洗牌分配或死亡。完整名单、宿主资格和其它来源域仍独立验收，实际结果及下一项只在原两份台账维护。

[官方卡页](https://hearthstone.blizzard.com/en-us/cards/64434-ignite)说明伤害后洗入提高一点的新点燃；[新实体玩家报告](https://us.forums.blizzard.com/en/hearthstone/t/game-bug-or-blizzard-absurdity/124146)和[仅后继提高的讨论](https://us.forums.blizzard.com/en/hearthstone/t/ignite-greatest-and-stupidest-idea-ever/70615)仅作局部公开依据。版本/热修及精确国服反应边缘按用户授权暂缓，不等待实测，也不将这些资料提升为官方完整池证明。
