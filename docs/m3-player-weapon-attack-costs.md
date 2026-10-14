# 当前装备武器攻击力的独立费用输入

实际执行、内部验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本契约定义真实卡文要求的有限输入，不表示动态费用整族、正式池或国服规则已验收。

## 声明与真实来源

普通可从手牌打出的随从用`CardDefinition.player_weapon_attack_cost=PlayerWeaponAttackCostSpec()`声明，默认None。唯一有限profile是`cost.player-equipped-weapon-attack-v1`；其他类型、非普通载体或叠加原条件/其他数量公式明确拒绝。没有任意表达式、手牌事件减费脚本或新武器执行器。

仅必要[NEW1_022恐怖海盗完整raw/pin](../data/support/player-weapon-attack-cost-basics.json)在隔离验证注册表适配：4费3/3中立普通海盗、嘲讽，无战吼或额外主体。文件包含该原行和CORE_NEW1_022完整独立原行；CORE只作证据，不新增可执行适配。canonical pin为`c590ee9c88ed67b3caff20b8ae89a7e5f82446dafc6e1f0ae8e89256e1827393`，生产代表包不扩张。

匹配[官方卡库](https://hearthstone.blizzard.com/en-us/cards/878)检索结果支持按本人武器攻击力减费及嘲讽、种族等卡文；页面实际打开只有导航。完整数值和本地适配据固定原行；当前CN装备资格、接受窗口、费用层序和正式池仍待M0/M6，不能以英文检索代替国服校准。

## 复用装备和当前攻击力

`player_weapon_attack_costs.py`纯读取实际payer的原`Player.weapon_id`、`equipped_weapon`和`Entity.attack`。原装备资格是耐久大于0且未doomed，当前实际武器攻击力来自原属性层；英雄临时攻击、英雄总攻击和印刷武器攻击力不替代该输入。非己方回合中英雄没有武器攻击贡献，也不改变武器本身的报价输入。对手武器不计。

先完整捕获原槽，再应用原存活资格。没有武器时，allocation/attack/durability/doomed均为None，数量0。零攻击的存活武器保留完整实体分配事实；原槽中耐久0或负数、doomed的武器也保留原身份和数值，仅贡献0。该纯捕获边界不表示引擎支持将任意暂态死亡局面保存为真实待选存档。槽中实体丢失、当前类型/区域/控制者错误，或未知、非武器卡面，即使数量为0也明确拒绝。

换装、强化、攻击归零、耐久消耗和销毁由原模块执行；新报价读取新局面，不写base_cost，不安装费用附魔、缓存或累计账本，不分配实体、不消费RNG。获取定价随从前已有的武器也有效。

## 共享费用、原始事实与保存

金额为`max(0, base_cost-quantity)`，进入原固有层，再经过原本地/外部费用层和最终下限。物理手牌、生成报价、玩家显示、合法操作与一次实际付款共享该入口。原普通随从入场、嘲讽和后续生命周期不变化；原印刷复制到另一方用新payer装备重新报价，随从沉默、回手和变形复用原能力安装及定义切换。

`PlayerWeaponAttackCostFact`保存有限声明、payer、turn/action、实体和顺序分配上界、完整原`SourceAllocationFact.payload()`、当时实际攻击/耐久/doomed、数量和before/after。原分配payload保留原物理ID、卡面、类型、区域、owner/controller、epoch和游标；使用规范有序的int/string原字段，避免把未注册的外部dataclass藏入帧。需要完整规范结构和精确类型，bool不能当整数；数量及金额从该完整事实重算。

`IntrinsicCostStageFact.weapon_attack`显式保存该事实或None，普通卡也必须保存None，绑定原payer/base/turn/action。严格字典读取要求新叶和全部嵌套字段，typed帧使用原模型冻结类型及严格字段策略。新默认None卡牌声明进入注册表指纹；旧存档不能静默补字段。

## 原接受窗口与后续合法推进

精确原窗口通过`validate_intrinsic_origin`从原真实状态重新捕获整份费用事实，包括完整装备分配、攻击和资格。即使攻击变化仍落在零费下限、金额相同，也不能替换原值后冒称同一接受事实。

历史前缀只核对完整声明、数值自洽、原时间/分配上界，以及原`validate_allocation`所证明的原实体、不变owner和可推进epoch。允许原武器合法强化、换装进入墓地、销毁、区域/控制权或卡面后续推进；旧已接受付款仍用原数量，不拿当前装备重价。原实体丢失或owner/分配边界不成立则拒绝。该紧凑证明不认证未签名存档的原始攻击或资格来源；一份数值自洽的伪造旧事实可能仅靠紧凑结构检查无法辨别，必须区别于精确原窗口重查。特殊回溯删实体等来源不凭本项普通手牌路径宣称完整支持。

原完成后待选、选择后的装备变化、snapshot/clone/独立注册表replay，以及延迟或整根错误回滚，使用同一原解释器、事务和收据，不增加第二个执行入口。

## 协议与玩家边界

引入时为prototype-v217/core-effects-v211、schema203，明确拒绝旧1～202、未来或错误类型版本；观察74、命令11、replay1、modular-v1/fabled-v2及生产代表64/合成3保持。新增两冻结类型、一默认None卡牌声明和一显式阶段叶；没有GameState/Entity/Player新字段、Effect、玩法事件类型、外部动作或执行器。原装备、属性、分配、费用支付、帧及生命周期模块复用。

玩家只看到允许公开的最终价格和原公开装备，完整allocation、冻结资格、游标及付款证明不投影给玩家。精确国服、完整动态费用族和特殊来源仍开放，当前不开发组合矩阵。
