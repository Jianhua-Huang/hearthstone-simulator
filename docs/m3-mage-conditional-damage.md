# 法师的原法力消费、条件目标和死亡门控伤害

[完整来源包](../data/cards/mage-conditional-damage-v1.json)保留OG_086禁忌烈焰、GDB_456自燃、VAC_953浪潮涌起的三条完整原行和六份中英文官网主面；它们是标准过去来源的实际依赖，不增加标准组牌根。禁忌烈焰原行缺少COST且cost为null，原行不改写；两份完整官网主面均明确manaCost=0，沿共享numeric_normalizations单独声明印刷零费。

| 原牌 | 实际公共表达 |
| --- | --- |
| 禁忌烈焰 | 原SpendMana消费全部可用法力，用原完整ManaConsumptionRecord.actual及原CAST目标分配事实交付DamageCapturedMinionGroup |
| 自燃 | PreviousElementalTargetProfile决定统一目标接口是否要求目标；主体用同一原上回合元素关系，交付普通Damage或RandomDamage |
| 浪潮涌起 | DamageMinionsRepeatIfNoDeaths完成一个普通同时伤害批，RepeatSpellBatchIfNoDeaths按该批真实死亡决定至多一次第二批 |

## 禁忌烈焰

手动零费出牌和自动CAST均进入原施法管线。原SpendMana记录请求、实际支出、法力账户前后值、来源原卡面、原玩家和原cast_id；续接核对该完整结果和仍在执行的原CAST。后来的恢复法力不改原实际消费量，零消费仍有完整resolved结果。

资源续接不依赖一个后来可能已变化的target_id参数：它从原cast.target_origin恢复原BOARD随从的完整MinionReference，再交给既有DamageCapturedMinionGroup。离场、换面、控制/驻留变化按既有物理引用政策跳过，不把同一数字id的新驻留当作原对象；支付和原消费不退款。伤害仍为普通SPELL，真实零消费配合法伤也沿原报价执行，没有手写扣血或读取后来的剩余法力。

## 自燃

新增有限PreviousElementalTargetProfile(card_id, condition='previous_owner_turn_elemental')，该固定条件进入注册表指纹，与原UnplayedCopyTargetProfile分开。注册约束仍要求普通物理法术和原REQUIRED目标域；不存在任意字符串条件或新的卡牌状态字段。

统一effective_target_spec使用query_previous_owner_turn及原PlayedTypeQuery(MINION, elemental)关系。条件未满足时返回无目标规格，合法动作和提交都只接受无箭头出牌；主体选择一个随机敌方角色。满足时保留原目标规格，必须提交一个合法目标；主体交付原4点SPELL伤害。使用原最近一次已关闭本人回合的冻结提交种族，不从当前随从换面或对方回合猜测。

本地按卡文最初的enemy域把条件分支限制为敌方角色；是否允许友方目标尚无独立证据，明确列入国服边缘待确认。随机分支与有条件自动CAST继续使用原随机伤害/自动目标管线，重放不是另一个无目标白板。[暴雪31.4公告](https://news.blizzard.com/en-us/article/24166286/31-4-patch-notes)曾修复苔丝无法重放此牌的问题；[社区卡页](https://hearthstone.wiki.gg/wiki/Spontaneous_Combustion)提供卡文和原敌方域，均不认证这里全部条件/目标窗口。

## 浪潮涌起

两个有限指令扩展既有spell_sequences，复用SpellSequence、minions、require_cast、settle_health_batch和原按批次死亡查询。初始指令捕获原活跃CAST，在当前双方活跃、存活、非待死亡的普通随从上创建一个同时SPELL伤害批；空场直接结束，不制造目标或消耗随机。

第一批的原batch_id与基础伤害进入待续指令。恢复和执行均要求原CAST仍在执行、批次在原CAST开始之后，完整原damage_history中存在该来源/卡面/玩家/基础量/伤害类型一致的首批结果。不存在的批次、修改的数量、错误CAST及缺失结果拒绝。没有重新扫描当前生命值来猜首批是否杀过随从。

原死亡检查点后，门控将第一批直接伤害/毒性死亡的DeathCause.result与原完整HealthResult逐项对应。首批真实死过随从即停止，复生后的新随从不取消原死亡；无关反应独立消灭的对象不冒充首批所杀。没有该批死亡时，重新读取当前场面并交付一个普通DamageBatch，然后结束；新反应召唤的对象可以进入第二批，第二批杀人也不会产生第三批。

两批仍属于同一个CAST、一次原支付。每批的法伤、路由、圣盾、免疫、转换、死亡和反应都由原健康结算器处理。精确反应边界和死亡归属为本地政策，尚未国服校准；这里不新增组合机制、死亡执行器或任意循环。

本层core787→788、schema611→612（旧1～611拒绝），Effect721→723、payload280不变；玩家观察121/命令13/replay1保持，构筑内容689。默认空局允许的差异只包括schema、core版本、完整Effect声明中这两个新增类型，以及独立重算的派生哈希；旧声明和其余局面必须保持。专项见[测试](../tests/test_mage_conditional_damage.py)，实际结果与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。
