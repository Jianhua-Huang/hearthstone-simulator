# 英雄当前生命事实的有限费用规则

本契约提供一个独立英雄生命事实输入：实际付款方当前物理英雄、最大与当前生命。默认profile按缺失生命减费，有限新profile按当前生命≤15固定减5费。实际执行结果及下一项在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

## 固定依据与有限声明

[两条完整原始记录](../data/support/hero-missing-health-cost-basics.json)保存熔核巨人`EX1_620`与核心熔核巨人`CORE_EX1_620`。canonical pin为`f7120afcf6d672e92dd9ee3eb36b05b34ba79bbd2863d79eb4114424525af9c2`；本地固定20费8/8及卡文是机制依据，尚未证明最新正式合法池。只隔离适配一张必要普通随从，核心记录只作证据，生产代表包保持。

`CardDefinition.hero_missing_health_cost`默认`None`；声明`HeroMissingHealthCostSpec()`采用固定`cost.hero-missing-health-v1`政策。仅支持普通可从手牌打出的随从，每缺失一点生命减一费，最低零。不接收任意表达式、对手生命或累计伤害政策；同一印刷定义多个数量公式需要真实来源审核，目前拒绝。

```python
CardDefinition(
    'EX1_620', '熔核巨人', CardType.MINION,
    cost=20, attack=8, health=8,
    hero_missing_health_cost=HeroMissingHealthCostSpec(),
    # 另需已审核的普通构筑元信息。
)
```

## 当前生命阈值的有限扩展

`HeroMissingHealthCostSpec("cost.hero-health-at-most-fifteen-v1")`仍使用原`hero_missing_health_cost`声明和原事实类型。当前本人英雄生命≤15时quantity为5，否则为0；金额为`max(0, before-quantity)`。最大生命、缺失生命、护甲、历史伤害与对手生命不代替当前生命。最大生命91而当前16仍不减费，最大/当前均15也减5费；旧默认profile保持原差值公式。只接受这一真实有限阈值，不开放任意阈值、表达式、叠加数量规则或组合矩阵。

必要[AV_141t冰雪之王洛克霍拉完整raw/pin](../data/support/hero-health-threshold-cost-basics.json)为10费8/8中立传说元素，原突袭/风怒使用既有关键词和战斗规则，无自身战吼/亡语或额外主体。pin为`2e105d39947cdeba792d70b5867bbbc84323ff91f508f4ffa6d3411a32e217c6`，仅隔离适配，生产代表包不扩张。匹配[官方卡库](https://hearthstone.blizzard.com/en-us/cards/70255-lokholar-the-ice-lord/)检索支持阈值、减5费和关键词，实际打开只提供9行导航；完整数值和元信息据固定本地记录，当前CN接受窗/层序及正式池仍待M0/M6。

## 当前英雄与纯报价

每次报价经`state.players[payer].hero_id`读取当前物理英雄，核对HERO类型、HERO区域、原归属、当前控制方及已支持英雄卡面。默认profile数量为`hero.max_health - hero.health`；阈值profile读取同一当前health并取5或0，直接复用既有Entity生命属性，不建立伤害累计表或第二套生命规则。

伤害被护甲吸收时不增加缺失生命；治疗减少当前缺口；直接失去生命按实际结果计入。提高最大生命和调整上限所采用的`preserve_missing`或`clamp_current`政策由原生命处理器执行，报价读取它们最终产生的最大/当前生命。设置生命或替换英雄后从当前英雄重新计算，旧英雄不再作为新报价来源。对手缺失生命、双方护甲、此前伤害与治疗事件次数都不替代这个数量。

物理与生成报价使用相同当前英雄，不要求在生成查询时分配实体。数量减费在原base之后、既有条件/本地附魔/外部层之前，最终最低费用由原调用方处理。查询不改基础费用、附件、实体分配、随机状态或资源用途。

## 原冻结事实与历史

`HeroMissingHealthCostFact`保存原声明、payer、实体分配上界、英雄物理ID和卡面、最大/当前生命、数量及before/after；`IntrinsicCostStageFact.hero_missing_health`必须显式保存事实或None。按原声明严格重算差值或有限阈值、数量和零下限，两个profile都保留完整max_health/health，即使金额相同也不丢原字段；拒绝bool冒作整数、未来实体、错误payer/base和缺失或多余字段。实际物理报价来源也必须早于原分配上界。

真实付款仍由共享报价及原手牌接受证明处理，原窗口重算实际英雄与生命。原承诺待选与后来card_played选择、治疗或英雄替换不改写已付金额，也不重复扣款；新报价读取变化后的当前英雄生命。原显示、合法动作、付款验证、资源处理、恢复、clone和独立注册表回放复用同一流程。

紧凑历史校验原分配和时间线前缀，绑定保留的原物理英雄类型、归属、控制方和卡面。现有英雄替换保留旧实体；随从变形/转控不能修改英雄身份。后续生命、上限、活跃英雄指针可以变化，历史仍按冻结的完整原生命事实及对应profile重算，不用今天的生命重定价。紧凑事实不能认证未签名存档的外部来源，也不证明协同重写全部历史的真实性。

## 生命周期、保存及玩家接口

印刷声明跟随普通定义，印刷复制、沉默、回手及重新获取复用既有生命周期。重新入手按当前英雄报价，不把上次见到的减费写成永久费用。特殊复制的精确国服政策待具体来源和M6核查。

首次落地为`prototype-v184`、`core-effects-v178`、schema173，拒绝旧1～172；观察74、命令11、replay1保持。所有定义新增默认`hero_missing_health_cost=None`，所有固有阶段新增显式`hero_missing_health`，因此普通注册表指纹和费用保存格式变化，不自动补旧字段。没有新Entity/Player字段、玩法事件或外部动作。

双方英雄最大/当前生命本来公开，玩家可看到自己的实际价格。内部健康事实、实体分配上界、宿主快照和完整付款证明不输出到玩家接口，对手手牌卡面及费用仍隐藏。

当前有限阈值扩展为prototype-v219/core-effects-v213；schema204布局保持，拒绝旧1～203、未来或错误类型版本，同时明确拒绝旧规则/效果语义。原两模型类型、所有字段/默认声明、严格字典/typed读取、费用/付款/恢复/回放保持，无新模块、模型类型、状态/卡牌/阶段字段、事件、动作或执行器；观察74/命令11/replay1及生产代表64/合成3保持。玩家只看到原公开英雄生命与允许公开的最终价格，原物理英雄、分配上界和冻结费用证明不投影给玩家。

## 剩余范围

数量层顺序、特殊复制与精确国服规则尚未校准。按历史施法、已支付资源或其他类型数量等真实费用输入需逐项核对，优先复用已有计数和公共模块。U53整族、完整来源、正式合法/生成池、H2/M0/M6/M7及整个基础目标仍开放；本契约不引入组合机制或任意费用公式。

历史共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。后续[本人本局施法数量费用](m3-player-spell-count-costs.md)读取既有完整cast_history；其本人原hand根口径不修改本契约的原语或其他卡文计数资格，精确CN待校准。

历史共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。后续[本人本局技能次数费用](m3-player-hero-power-count-costs.md)复用原完整hero_power_history，不改变原技能生命周期/其他卡文资格；精确CN仍待校准。

历史共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[本局实际法术法力费用](m3-player-spell-mana-costs.md)复用原物理出牌/付款，不改变本契约自身资格；精确CN仍待校准。


## 真实过去依赖的原生身份接线

AV_141t的上述有限profile原先只在隔离机制夹具中适配；现以[完整固定原行及两份双语官网主面](../data/cards/native-lokholar-v1.json)接入构筑执行注册表，作为标准实际可达过去内容的依赖，并补PoolCard生成元数据。保留真实10费8/8元素、突袭/风怒及HeroMissingHealthCostSpec('cost.hero-health-at-most-fifteen-v1')；没有重复实现阈值、数量计价、战斗或冻结付款。

原型历史描述和原完整raw/pin保留；该身份的原生接线不把旧隔离机制证据冒充完整专用池。究极边境有限验证通过原发现/生成设费和正常手牌付款，生成设费1沿原附件阶段在固有减费后应用；当前英雄高低生命都不会被新造永久折扣覆盖。生产过去域仍未绑定，34参考的模式/版本疑点和国服边界仍单独记录。实际验收及下一项只在原两份台账维护。
