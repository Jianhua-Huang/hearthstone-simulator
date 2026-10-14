# 当前英雄护甲的独立费用输入

实际执行、内部验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本契约定义真实卡文需要的有限输入，不表示动态费用整族、正式池或国服规则已验收。

## 声明与真实来源

普通可从手牌打出的法术通过`CardDefinition.player_armor_cost=PlayerArmorCostSpec()`声明，默认None。两个有限profile共享一个当前护甲事实：`cost.player-current-hero-armor-v1`按实际护甲减费，金额为`max(0, before-armor)`；`cost.player-current-hero-no-armor-zero-v1`在实际护甲为0时取0，否则保留before。后者的quantity仍保存实际Armor，不能把正护甲当作线性减费。其他类型、非普通载体、原条件或其他数量公式叠加明确拒绝，不提供任意表达式或组合矩阵。

仅必要[两张完整本地raw/pin](../data/support/player-armor-cost-basics.json)在隔离验证注册表适配：AV_108裂盾一击是10费战士稀有冰霜法术，原主体返回双方活动随从的`DamageBatch(5, SPELL)`；TOY_907安全护目镜是2费战士普通法术，无学派，原主体返回`GainArmor(6)`。不猜填战吼、学派或额外主体。支持文件canonical pin为`f69b09850d0b0a174d0921680520dfa22764ea5bf6dd1cb33542e87b1de95fd5`，生产代表包不扩张。

匹配[裂盾一击官方卡库](https://hearthstone.blizzard.com/en-us/cards/67193/)检索支持护甲减费和伤害卡文；[24.0.3公告](https://hearthstone.blizzard.com/en-us/news/23840665/24-0-3-patch-notes)只证明2022-08-16历史4改5。[安全护目镜官方卡库](https://hearthstone.blizzard.com/en-us/cards/102407/)实际打开及裂盾一击页面都只提供导航，护目镜精确文本搜索没有匹配规则结果。完整数值、类型和本地适配据固定原行；当前CN费用窗、层序、伤害政策和正式池仍待M0/M6。

## 复用当前英雄与原护甲

`player_armor_costs.py`纯读取实际payer的当前`Player.hero_id`及原`Entity.armor`，捕获完整原`SourceAllocationFact.payload()`。英雄必须存在，kind/zone为HERO，owner/controller等于payer，当前卡面是已支持HERO。即使护甲为0，也必须保留非空完整规范英雄分配；未知、丢失或错误身份不能当作空值。

输入是当前非负护甲值，不使用生命值、最大生命、累计获得护甲或历史受到伤害。对手护甲不计，非己方回合也没有额外本人回合门槛。获取定价卡之前的护甲同样有效。

原增甲、伤害吸收、护甲耗尽、生命损失/治疗和英雄替换负责改变局面；后续新报价重新读取当前英雄。换英雄后引用新hero_id，旧已接受事实保持原物理英雄。没有第二套护甲/生命或群体伤害执行器，不添加GameState/Entity/Player字段、缓存、累计账本、事件或外部动作。查询不创建实体、分配ID、消费RNG或写base_cost。

## 共享费用与完整保存

两个profile进入同一原固有费用阶段，再经过原本地/外部费用层及最终下限。物理手牌、纯生成报价、玩家显示、合法操作和一次实际付款共享入口。安全护目镜在无护甲时先按0支付，再由原主体获得6护甲；新护甲不能倒改本次费用，之后新报价用新数值。原反制保留已支付费用并跳过各自原主体。

`PlayerArmorCostFact`冻结有限声明、payer、turn/action、实体/顺序分配上界、完整规范有序hero_allocation、原Armor/quantity及before/after。原payload含物理ID、卡面、类型/区域、owner/controller、epoch和游标；保存int/string原始字段，不将未注册外部dataclass藏入帧。字段类型精确，bool不作整数；分配、数量及金额均须从完整事实重算。

`IntrinsicCostStageFact.player_armor`显式保存事实或None，普通卡也必须保存None，绑定原payer/base/turn/action并排除其他数量输入。严格字典读取要求新叶及全部嵌套字段，typed帧复用原冻结模型类型与严格字段读取。新默认None卡牌声明进入原注册表指纹；旧存档不静默补字段。

## 原窗口与后续合法推进

`validate_intrinsic_origin`从精确原真实窗口重捕获整份事实。即使改护甲后金额仍同为0，也不能替换原数值后冒称同一接受事实。

紧凑历史只检查完整声明、数值自洽、原时间/分配边界及原`validate_allocation`的实体、owner和可推进epoch。允许后续合法增甲/吸收及英雄替换；旧英雄保留在原墓地，原付款仍冻结，不用当前数值重新报价。原实体丢失、owner或分配边界不成立则拒绝。该紧凑证明不认证未签名存档的历史护甲来源；数值自洽的伪造旧事实可能通过结构检查，必须区别于精确原窗口重查。

完成后真实待选的独立注册表恢复/clone/replay、后续护甲或英雄变化，以及延迟或整根错误回滚，使用原解释器、帧和事务。普通手牌路径及纯生成报价覆盖不表示automatic CAST、特殊producer或完整Retry来源已验收。

## 协议与玩家边界

引入时为prototype-v218/core-effects-v212、schema204，明确拒绝旧1～203、未来或错误类型版本；观察74、命令11、replay1、modular-v1/fabled-v2及生产代表64/合成3保持。新增两冻结类型、一默认None卡牌声明和一显式阶段叶，没有新Effect、玩法事件类型、状态字段或执行器。

玩家只看到允许公开的最终价格和原公开护甲；完整allocation、冻结原数值、分配游标及付款证明不投影给玩家。准确国服、完整动态费用族和特殊来源仍开放。
