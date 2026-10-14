# 本人回合英雄生命变化次数：固有费用消费者

实际执行、验收证据与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。此处定义一项独立基础费用输入；[实际生命变化事实](m3-hero-health-changes.md)继续由原提交处理器记录，不新增生命处理器或组合机制。

## 有限声明与必要来源

普通物理随从声明CardDefinition.hero_health_change_cost=HeroHealthChangeCostSpec()，默认None。profile固定cost.hero-own-turn-health-changes-v1：实际payer的英雄在真实本人回合中，每次当前生命实际变化减一费，金额为max(0, base_cost-quantity)。获取本牌前的变化也计入；对手回合的变化有记录但不贡献该玩家的本人次数。

仅用[完整固定本地SCH_140](../data/support/hero-health-change-basics.json)血肉巨人验证：10费8/8、史诗、牧师/术士、亡灵，无额外战吼或其他印刷效果。完整canonical pin为12ac7eff1d3650d7bbf8a3f12ea44dd366069508822b950dc861ba1711e31309。实验定义在必要专项独立注册表中，生产代表包和正式池没有扩充。[官方卡库](https://hearthstone.blizzard.com/en-us/cards/59585-flesh-giant?set=wild&textFilter=fleisch)支持卡文及类型；数值来自完整本地记录。历史[21.2补丁](https://hearthstone.blizzard.com/zh-tw/news/23712592/21-2-patch-notes)包含9费改10费，不能用该旧补丁认证当前国服版本和窗口。

未知profile、非普通随从、choice-only和星舰载体拒绝。与其他数量或上一本人回合条件同时声明的公式需要真实来源审查；当前拒绝，不开放任意表达式、额外授予或组合族。既有本地和外部费用层仍按共享系统正常执行。

## 原数量、完整前缀与共享报价

hero_health_change_costs.py调用原health_change_count纯查询，不扫描宿主事件或写实体/玩家费用缓存。HeroHealthChangeCostFact冻结完整有序HeroHealthChangeRecord元组，包括对手等没有贡献数量的行；保存原payer、turn/action、实体分配上界、历史长度及游标、数量和before/after。数量是次数，不是伤害金额、缺失生命或最终净变化。

IntrinsicCostStageFact.hero_health_changes是显式叶，绑定原payer/base、原turn/action和真实本人历史边界。普通卡牌也必须保存None；不能省略。冻结记录保持严格整数、完整顺序和物理分配上界，原英雄卡面必须存在；物理报价来源不得借未来实体ID。自洽的数量或相同最终价格不允许删改原完整记录。

该输入进入[原固有阶段](m5-intrinsic-costs.md)，在原本地附件、外部modifier/aura及最终费用下限之前。物理手牌、假设生成、玩家可见价格、合法操作和真正付款共用相同报价。生成报价不创建假物理实体；调用方最低费用在原层顺序最后应用。

完整原付款/接受窗口重取原实际输入。紧凑历史绑定保留的原事实前缀，允许后续新增生命变化、英雄替换、回合推进或新获取；已经支付的根保留原数量和价格。原生命支付可能产生新的变化事实，但该新事实不能回写本次付款前的报价。

严格事实校验及原窗口一致性不认证未签名存档的外部来源。协同重写全部原输入不是经过认证的官方规则证据。

## 生命周期、恢复与玩家信息

历史属于对局中的玩家，不安装在被定价随从上。正常印刷复制和回手按新的实际payer及当前完整历史报价；沉默后回手复用原印刷卡面重置。变形或换面按新卡面的声明报价，不把该公式作为独立附魔继承；复杂材料或特殊授予按真实卡需求后置。

英雄替换不抹去此前合法次数；生命相同而只换物理身份不增加次数。伤害/治疗批次、最大生命及属性、原健康钳制、生命支付、回溯事实恢复和本人时钟沿原基础契约；本费用模块不改这些提交窗口。

选择暂停、原付款完成后的监听选择、错误回滚、clone、独立注册表保存恢复和动作回放沿原解释器、帧与付款证明。原回溯恢复before事实和游标，所以撤销尝试不会给下一次报价重复减费。玩家只看允许公开的生命值、日志及自己的正常费用；内部生命账本、冻结前缀、游标、完整付款依据和对手隐藏手牌不交给玩家。

## 协议与未覆盖范围

本增量使用prototype-v213/core-effects-v207/schema201，严格拒旧1～200。观察74、命令11、外层replay1、modular-v1/fabled-v2及生产代表64/合成3保持。CardDefinition新增默认None声明、IntrinsicCostStageFact新增显式叶及两个冻结类型，注册表指纹和严格读取随之变化；没有新GameState/Entity/Player字段、Effect、事件类型、外部动作、费用执行器或生命执行器。

准确国服生命变化、上限/属性/支付/英雄替换、批次/本人区间和费用层顺序仍待M6校准；U53/U59整族、完整基础范围、H2/M0/M6/M7及最终目标仍未完成。本公式没有自动扩展到其他卡牌类型或任意历史条件。
