# 紫水晶的原伤害来源资格

本契约验证一个独立条件：持牌者英雄受到来自本人卡牌的合格伤害后，手中的紫水晶升级。复用原HealthResult、普通单位手牌进度和伤害/吸血效果，没有新增内核模块、事件、账户、字段或组合规则。运行身份保持`prototype-v167` / `core-effects-v167`、schema162（拒旧1～161）、观察71/命令10/replay1。实际执行与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 使用已有的原结算事实

普通声明为`HandProgressSpec('event', 1, next_form, event='health_resolved', condition_id='amethyst.eligible', upgrade_cost_policy='clear_local')`。资格读取`ctx.health_result`，使用[原健康结果](m5-health-outcomes.md)在结算点保存的源卡面、来源玩家、目标角色/玩家与实际伤害，不查询来源后来转控或变形后的当前状态。

本轮明确采用以下内部资格：实际flow为damage，damage_dealt大于0；原受伤角色是持牌者的hero；原来源玩家属于持牌者，source_card_id指向已注册可出牌定义；排除hero_power与fatigue伤害分类。普通初始英雄、英雄技能、无归因来源不作为“你的卡牌”。这些条件及所有特殊来源窗口待M6国服校准，不宣称已得到官方完整规则证明。

不额外限制本人回合。合格来源可以在对方回合伤害本人英雄；原结果保存的来源归属不会因普通反应随后转控而失效。自己的随从战斗伤害结果也可以满足条件，不错误地排除所有combat；此项只检验原伤害结果资格，没有接入误导或扩大攻击权限。

一次合格伤害包提供一个见证。1点或7点各只升一级，不误写为累计3点伤害；两个独立包可完成两级。普通damage_dealt与health_resolved来自同一伤害，进度只监听后者，不能双计。防止或零伤害没有正damage_dealt；护甲吸收在当前内核仍是实际伤害，采用明确内部政策计入。健康支付与LoseHealth没有被冒充伤害包；治疗和吸血治疗为healing流，不推进受伤资格。

## 必要真实路径

[完整七条raw/pin](../data/support/amethyst-qualification.json)保存本地来源及逐行完整摘要，PIN为`32d8bc19bdd2e4a1c99b1074b68af8d007ecfa2eebf184ac2c20eaa5ebd682a6`。

- LOOT_043/t2/t3：4费暗影、吸血，对一个随从造成3/5/7伤害，主体用原Damage及吸血结算。
- EX1_319火焰小鬼：真实战吼对本人英雄造成3伤害，提供一个必要随从来源。
- CS2_062地狱烈焰：按当前本地行3费，所有角色3伤害；多个随从及对方英雄的结果不会被当成本人英雄的多次受伤。
- LOOT_014狗头人图书管理员：先抽牌，再伤害本人英雄2点；实际抽到的新紫水晶已在手中，能够在后续伤害时升级。
- CS2_056_H3生命分流：真实抽牌及英雄技能伤害2点不触发；没有用旧记忆中的不存在CS2_056身份替代本地记录。

这些适配仅在隔离专项注册表存在；生产代表64/合成3及全部457既有Python源保持。场景不证明正式卡组合法、所有元信息/来源完整或国服补丁一致。等待、转控和异常均用明确的公共探针，真实紫水晶没有编造选择。官方[卡牌库定位](https://hearthstone.blizzard.com/en-us/cards/43272-lesser-amethyst-spellstone?class=warlock&set=kobolds-and-catacombs)此次仅返回目录布局；实际主体/门槛依据为固定完整本地行。[社区调查](https://hearthstone.wiki.gg/wiki/Template%3ALesser_Amethyst_Spellstone_notes)的搜索记录仅作线索，完整页面403，不能冒充国服校准或原来源定义的官方证明。

## 生命周期与信息

后获得的牌不补旧伤害历史，非手牌区暂停，返回保留原形态进度；current复制继承原完成次数和见证，base复制从当前印刷形态的空进度开始。升级沿原链身份，真实换面清本地费用是显式实验政策。最后一级不再监听，多个普通结果继续走原事件/解释器顺序，见[手牌进度](m5-hand-progress.md)及[数值升级](m3-spellstone-progress.md)。

普通进度完成的等待探针保存原事件和上下文，独立注册表恢复、clone及回放保持同一个伤害见证，不重伤害或双计。异常用例先真实支付并抽取随机，再错误资格返回，整动作快照恢复。未新增schema或任意授予。

HealthResult的完整原来源、区域修订及见证不进玩家观察。本人只见既有hand_progress摘要，对手隐藏手牌不见升级细节。这里只证明引擎结构与执行一致性，不提供未签名存档来源认证。

U32完整来源、红宝石/翡翠/秘银/缟玛瑙剩余资格与正式类别、M0正式池、M6国服校准、M7批量接卡及基础目标保持开放。实际结果与输入见[保存证据](../outputs/amethyst-qualification-20261010/verification.json)和[逐方法共同输入](../outputs/amethyst-qualification-20261010/accepted-evidence.json)，未执行的旧回归不写为此次通过。
