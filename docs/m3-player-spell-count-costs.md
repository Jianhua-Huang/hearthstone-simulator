# 本局本人施法次数的独立费用输入

实际执行、内部验证和下一项以[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)为准。本契约仅定义一个有限费用输入，不代表U53整族、最新正式卡池或国服规则已验收。

## 声明与已有历史

普通可从手牌打出的随从声明`CardDefinition.player_spell_count_cost=PlayerSpellCountCostSpec()`；默认None。默认profile为`cost.player-spell-count-v1`，固定用于普通随从；新增有限`cost.player-distinct-spell-school-count-v1`仅用于普通法术，详见[不同派系费用契约](m3-player-spell-school-costs.md)。未知profile、各profile的错误类型与非普通形态、同时声明其他数量公式均明确拒绝。

必要代表仅为[完整本地KAR_711奥术巨人记录](../data/support/player-spell-count-cost-basics.json)，canonical pin=`d567a39f443c09b70c2cb7a2ef065440389405e38e359a724edac69a6a0b1964`。印刷费用12、身材8/8，按本局施法减少费用。测试注册表作隔离适配，生产代表包不扩大。

`player_spell_count_costs.py`复用已有`cast_history`及其完整校验，不增加第二份事件历史、玩家计数缓存或手牌进度。获取该随从前的历史同样进入报价，不能用“在手牌期间发生的事件”代替本局计数。

## 有限计数政策

每次查询读取实际payer的全部原施法前缀，每个符合以下条件的原物理根贡献1：施法玩家为payer、origin为hand、主体已经接受、没有失败。接受后即计入，主体尚在等待选择或被终局打断不撤回已接受事实；这和仅查询completed的口径不同。

反制尝试不计入。repeat/effect/draw/history来源不再增加本人原手牌根的数量；效果消费一张真实手牌也保持其自动来源，不据原区域改成手动出牌。对手施法、随从出牌和英雄技能使用不计入。完整前缀仍保存这些未计入行，不能把它们删掉后声称原历史完整。

这是明确的本地执行政策。历史线索包括[2020年官方论坛中的玩家报告](https://us.forums.blizzard.com/en/hearthstone/t/arcane-gaint-and-cast-when-drawn/44147)及[次级规则资料](https://hearthstone.wiki.gg/wiki/Arcane_Giant)的检索摘要；前者不是开发者裁定，后者直接访问返回403。它们不能证明当前国服规则。尤其未结根的精确窗口、重复施法归属及各自动来源须在M6校准，不能将这一profile宣称为所有“施放”卡文的通用口径。

## 纯报价与冻结依据

数量减费在base后、既有条件/本地/外部层之前，每个原根减1、最低零。普通物理及生成报价共享实际payer的同一历史。查询不创建实体、不分配ID、不消耗RNG、不写永久减费；费用显示、合法动作、验证与实际付款使用同一公共管线。

`PlayerSpellCountCostFact`保存原声明、payer、分配上界、原cast_history_length、完整有序`PlayerSpellCountCostRow`元组、quantity及before/after。行保存真实cast/source/player/card/turn/action/origin/play/iteration、payload_started和failure，另保存原注册卡面`spell_school: SpellSchool | None`；None明确表示无派系。每行包括未计入行都核对原法术及原派系，不使用当前实体卡面。游标必须等于完整行数，ID必须连续有序，时间线和物理来源不能超出原窗口；每个原卡面都必须为已支持法术，零数量不短路未知定义。

`IntrinsicCostStageFact.player_spells`必须显式为原事实或None，绑定payer/base及原时间窗。原付款窗口从真实状态重新捕获完整前缀；真实提交仍使用原手牌接受证明。付款后card_played选择或后来施法不重写已付金额，也不再次扣款。

紧凑历史绑定同一完整原施法前缀，按冻结行重算原价格，不用今天的增加数量重新定价。原自动施法可以从payload未接受合法推进为已接受，但身份、来源与失败结果不得变化，已经接受的主体不能退回未接受。完成和终局中断不是此profile的计数操作数。完整当前历史仍由原模块验证，不能借用另一物理施法或删除未计入尾行。紧凑事实不认证未签名存档的外部来源，也不证明协同重写全部历史的真实性。

## 生命周期、保存与信息边界

普通印刷复制、沉默、回手及重新获取复用原生命周期；重新报价按当前本局历史计算，印刷费用12保持。场上/牌库的纯费用查询只是出牌假设，不把实体base_cost或印刷字段改成历史减费后的值。特殊复制的精确政策按真实来源和M6核对。

首次落地为`prototype-v185`、`core-effects-v179`、schema174，拒绝旧1～173；观察74/命令11/replay1、modular-v1/fabled-v2保持。所有定义新增默认`player_spell_count_cost=None`，所有固有阶段新增显式`player_spells`，注册表指纹和严格保存格式改变，不自动补旧字段。没有新Entity/Player字段、玩法事件或外部动作。

玩家可看到本人卡牌的实际价格；完整前缀、原物理身份、分配上界及付款证明只供内核验证，不输出给玩家。对手手牌及其价格继续隐藏。

## 剩余范围

费用层顺序、特殊复制、精确计数窗口及当前国服归属政策尚未校准。已支付资源、其他类型数量和其他真实历史公式须逐项核对并优先复用已有能力；本次不提供任意表达式或新组合矩阵。U53整族、H2/M0/M6/M7及整个基础目标保持开放。

当时共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。后续[本人本局技能次数费用](m3-player-hero-power-count-costs.md)复用原完整hero_power_history，不改变原技能生命周期/其他卡文资格；精确CN仍待校准。

当时共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[本局实际法术法力费用](m3-player-spell-mana-costs.md)复用原物理出牌/付款，不改变本契约自身资格；精确CN仍待校准。

现行共享费用API为prototype-v224/core-effects-v218/schema208，拒旧1～207。原冻结价格行新增派系，严格字典恢复解码枚举及None，typed帧沿既有模型集合；旧次数语义和本人的hand接受资格保持。不同派系profile对所选非空原派系去重，不另造状态或施法执行器；本牌自身后来接受的派系不改写自身提交前付款。“你施放”不能仅凭卡文扩大到所有卡牌自动施法，准确国服来源与窗口仍待M6校准。
