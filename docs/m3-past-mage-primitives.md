# 过去法师法术：基础效果与实际手动施放条件

完整原资料见 [十五张法术](../data/cards/past-mage-primitive-spells-v1.json)，其原始身份来自 [完整179项参考](../data/cards/past-mage-spells-local-reference-v1.json)。这批属于标准来源实际能生成的历史依赖；不会增加标准构筑根、裁减原名单或提前开放尚未闭合的过去法术来源。执行进展、验证与下一项仅在原两份台账维护。

## 数据与公共效果

| 实际卡牌 | 表达方式与关键边界 |
| --- | --- |
| AT_001、WON_341 炎枪术 | 各自保留真实身份，印刷5费、25点随从伤害；目标与法强沿普通管线。 |
| CFM_065 火山药水 | 一次接受双方当前存活随从的 DamageBatch，统一捕获法强，不在逐包死亡后重新报价。 |
| CS2_026 冰霜新星 | 捕获当前敌方活体，沿普通 Freeze；不把非指向效果套成手动目标检查。 |
| CS2_031 冰枪术 | 原执行时已冻结则造成4点伤害，否则冻结；不在伤害后再补一次冻结。 |
| EX1_179 冰刺 | 先保存原目标冻结条件，造成2点伤害；原条件成立即按普通 Draw 抽一张，致死目标不取消原抽牌。 |
| GVG_001 烈焰轰击 | 手动接受前须有敌方随从；正文 RandomDamage 只取当前敌方活体，不生成手动目标箭头。 |
| GIL_147 燃烬风暴、DMF_103 克苏恩面具 | 复用 RandomSplitDamage，一次捕获总预算5/10加法强，每包1点、当前敌方角色重新选取；等待中失去法强来源不回改原剩余预算。 |
| BOT_600 研发计划 | 普通 Draw：施法者两次原抽牌，再对方两次。抽到施放、满手与疲劳继续交原执行器。 |
| OG_081 冰爆 | 普通随从目标加 player 可见的当前 frozen 条件，正文普通 Destroy。 |
| WC_041 冰爆冲击 | 捕获双方当前已冻结活体，用一个 DestroyBatch 标记后统一死亡检查。 |
| ULD_216 尤格-萨隆的谜之匣 | 现有完整普通可收集法术池、跨职业、十次 CastFromPool；不替换成过去法师池。 |
| TOY_372 匣中古神 | 五次普通池施法；正文接受时牌库无随从则冻结 min_cost=5 查询，后续反应改牌库不回改该分支。 |
| UNG_948 熔岩镜像 | 友方随从必选，BoardPresenceReference 与 SummonCause 交普通 current CopyMinion；费用、局部属性、身份分配和召唤容量沿原管线。 |

全批先验证完整原行、原费用/职业/法术类型和既有池元数据，再安装规则、正文及定义，末项错误不能留下半注册。原始重印身份保持独立；没有据相同卡名推断生成权重或全局去重族。

## 真实缺口：无手动目标的法术施放条件

CardDefinition 原有 `use_rule` 现允许普通 SPELL 声明；法术仍不能声明 `on_use`、非默认 `uses_per_turn` 或 `requires_board_space`，英雄技能和地标的原激活行为保持。注册表完整校验会验证法术引用的规则存在。没有新增 CardDefinition 字段、状态字段、动作、Effect、payload 或保存格式。

`play_requirements.manual_use_error` 与原结构门禁分开：Game 验证、手牌动作枚举及内部 PlayFromHand 在原接受前共享该动态规则；与目标条件一样，只在实际接受前查询。`player_api.require_supported_source` 在调用规则前验证可见性，玩家入口拒绝 omniscient 回调。player 回调只拿独立复制的 PlayerRuleContext，不获得原实体ID、对手隐藏牌面或引擎状态；内部调用使用原安全效果投影。回调异常、非 bool 返回均明确失败并沿原事务回滚。

普通费用证明保留原结构/支付约束，不执行动态资格回调，也不在付款后、恢复或回放中按新局面重新判定原接受。`card_committed` 反应中失去最后敌方随从，不撤销已接受施放、不重复收费；正文照常使用共享当前候选，空集按原效果处理。自动 CAST 使用自身原管线，不把手动入口条件扩成所有自动施法的门禁。

烈焰轰击最小敌方随从条件参考 [Fireplace 的原始维护者实现](https://github.com/jleclanche/fireplace/blob/master/fireplace/cards/gvg/mage.py)，只作为社区行为资料，不复制其实现，也不冒充现行国服证明。熔岩镜像的友方目标和未声明空位门禁同样有 [原始实现资料](https://github.com/jleclanche/fireplace/blob/master/fireplace/cards/ungoro/mage.py)。其余卡文逐条核完整官方中英主面；冰爆冲击另有 [官方迷你系列说明](https://hearthstone.blizzard.com/en-us/news/23676206/prepare-yourself-adventurer-the-wailing-caverns-mini-set-is-here)。

## 明确保留的本地政策

- 研发计划采用施法者先抽两张再对方两张；精确同时致死/通知顺序待验证。
- 烈焰轰击手动条件按公开战场上仍有正生命的敌方随从计数，正文按当前 active 活体选取；休眠计数及自动空池具体失败标签未作国服认证。
- 熔岩镜像使用共享当前复制和容量；满场施放、附魔具体复制边界和通知窗口继续按现有本地政策记录。
- 两张匣子使用完整普通池原库存、排除和施法器；不声称池资料或局部测试已经完成正式版本对齐。
- 冻结/死亡/法强的精确国服窗口、重印生成权重及旧版规则差异仍待校准。版本与规则边界按用户要求暂缓，不作为当前补依赖的等待项。
