# 有限伤害序列与原抽牌续接

原健康结果的直接死亡奖励和伤害量召唤继续复用InvokeHealthResult；需要整组匹配抽牌后奖励时，独立draw_beneficiaries保存原物理引用而不修改本页普通抽牌/减费执行器。两个真实消费者及完整边界见[健康与抽牌受益](m3-health-draw-beneficiaries.md)。

先行打击的伤害后手牌条件交原未选择报价，成立时普通DrawMatching抽实际物理随从；没有匹配项时明确skip，不额外疲劳或抽错法术。其接受窗口、费用修正纯查询及其他资源配方见[契约](m3-health-resource-spells.md)。

随机敌方随从伤害后的抽牌复用本页`DrawSpellBatchDeaths`，只有原健康批直接damage/poison归因的尸体计数，不按后续死亡增量推断。吞噬及混合目标、冻结的有限请求见[法术目标契约](m3-spell-target-sequences.md)。

普通伤害、原结果回调、延系Draw和具名水蛭可直接组合现有原语，见[真实伤害续接配方](m3-health-sequence-spells.md)。这些卡牌没有新增本页公共请求或修改数值、死亡执行器。

此页记录扩展契约。实际执行、结果与下一项仅见[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。卡面配方见[内容包](../data/cards/spell-sequence-effects-v1.json)。

`hs_sim.engine.spell_sequences`提供以下有限入口：

- `DecreasingMinionDamage(player_id, cast_id, source_id, amount)`：必须绑定实际正在执行主体的SPELL。开始时按原cast和学派查询一次法伤，形成正整数初值；逐波递减到1。每波重新读取双方存活、非休眠、非交互载体的普通随从，调用原健康批次，再由原解释器处理死亡与反应。提供者死亡不重新改写本次初值。后续波是可序列化`MinionDamageWave`，没有闭包或第二份状态账本。
- `DamageMinionsDrawDeaths(player_id, cast_id, source_id, amount)`：一次同时伤害当前双方普通随从；`DrawSpellBatchDeaths`在死亡/反应后核对实际原`health_resolved`批次，只按与其中完整原结果相等的damage/poison死亡归因计数，交原`Draw`执行抽牌。其他来源消灭、亡语抽牌及衍生新体不增加本批奖励数。此处是直接因果内部政策，光环间接致死等精确服务器口径尚未校准。
- `DrawWithCostReduction(player_id, reduction, source_id)`：调用原`draw_one`，捕获该次原记录的实际hand交付及`CardReference`，等待原抽牌续接后执行`ModifyStoredCost`。额外抽牌不改绑目标，原牌离开再返回也不视为同一次到手。burn/fatigue/cast无手牌减费；“抽到时施放”的替补抽牌不继承本次减费。
- `DrawMatchingWithCostReduction(player_id, reduction, source_id, query)`：在实际执行时用既有`zone_candidates`匹配完整物理牌库，每张同名实体分别一个权重；非空随机抽取一个原引用，再复用上述`draw_one`与实际hand交付续接。空匹配直接跳过，不产生疲劳或RNG消费；非空沿原随机匹配抽牌入口使用一次采样（含单候选）。查询只接受原`PoolQuery`，不建立第二份抽牌或费用历史。需要两次时提交两个请求，第二次在第一轮抽牌、反应和减费完成后重查，不先冻结两张候选。
- `DrawIfCheap(player_id, maximum, source_id)`：按原物理抽牌实际落点报价，在原抽牌链后有条件追加一次Draw，费用条件在反应前接受，不递归。burn/cast与时间政策见[属性与条件抽牌契约](m3-stat-draw-spells.md)，core321新增该效果。

递减波的法伤已包含在波金额中，`settle_health_batch`及`prepare_health`仅增加默认true的临时`apply_spell_bonus`参数供该内部波置false，避免重复加法伤。没有改变普通Damage保存字段，也没有绕过路由、数值修正、防护、吸血、健康历史和死亡协调器。默认所有旧调用继续使用true。新效果类型及执行语义由core320和内容包v20标识；原状态布局/schema268保持，新增类型由原FrameCodec登记。

过滤抽牌减费新增类型由core338登记，复用原FrameCodec允许列表；原状态/原效果字段布局和schema271保持，旧机制签名不被当作当前签名接受。该入口可由真实随从亡语调用，不要求虚构SPELL cast。查询/采样、抽牌后减费及多次请求先后仍属内部政策，精确国服窗口另由M6校准。

涣漫洪流在首主体冻结是否流放，使用两个命名主体请求逐轮重读敌方物理左右随从。单个随从同时占两端时形成两包；休眠端保留物理位置，不能被击中，也不会把内侧对象变为边缘。地标和交互载体不作为普通随从端。每轮复用DamageBatch，轮间处理原死亡/反应。

守护巨龙之拥顺序为Heal、Draw、Imbue；兆示法术先Herald再处理后段。暮光祭礼仅原连击条件成立时要求角色目标并追加伤害，试验演示在兆示后查询当前敌方随从。均使用既有职业映射及条件、支付/恢复机制，没有新关键词枚举或人工计数。盗贼、死亡骑士士兵沿既有生成入口，实验场景必须显式提供GenerationContext；已有representative池不是完整正式合法池。未登记职业映射、完整生成内容与借用跨职业政策不能据本批自动宣称完成。

证据边界：固定37.0完整卡面证明文字、费用、职业、关键词和学派，不证明隐藏结算细节。社区[触手讨论](https://www.reddit.com/r/hearthstone/comments/1ssekya/ideas_to_what_this_card_needs_to_be_viable/)支持法伤增加初值从而增加波数的解释；[洪流预览讨论](https://www.reddit.com/r/hearthstone/comments/1r7lcz3/new_card_flash_flood/)按旧牌类比认为单体承受两端伤害，属于预览推断；[历史视界术实用报告](https://us.forums.blizzard.com/en/hearthstone/t/soul-shard-draws-next-card-instead-of-skull-of-guldan/40734)支持替补抽牌不减费。都不是固定补丁国服官方实测。精确初值捕获、倍率/转换、每波时序、休眠端、两端同体、死亡计数及减费先后继续登记为待M6校准。
