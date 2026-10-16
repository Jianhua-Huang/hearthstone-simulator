# 一次法术预算与过量分流

本契约用于真实爆炸符文CORE_LOOT_101，不另造奥秘或伤害解释器。固定完整卡面和审核配方见[数据](../data/cards/excess-secret-effects-v1.json)，原数值层见[伤害与治疗](m2-health-rules.md)。实际进度、验证证据与下一项只在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护。

## 请求与原目标

`hs_sim.engine.excess_damage.DamageExcessToHero(minion, amount, source_id, on_result=None)`携带原MinionReference、非负整数基础量、实际已分配SPELL来源和可选已注册结果回调。它不要求仍在执行CAST，因奥秘可在部署施法完成后触发；不能拿随从来源伪造SPELL。

原目标必须仍为原物理生命周期、控制者及卡面一致的active/live普通随从；变形、回手再入场、转控或移区使原引用失效，沿原解释器记跳过，不重新选取后来同名或相同场位的随从。未知来源、定义和回调即使遇到失效目标也明确拒绝。

奥秘仍由原SecretSpec/CheckSecret负责条件、隐藏、揭示及消费，唯一性key为LOOT_101。原`r.call`在接受行为时冻结上下文，卡牌回调从该上下文捕获原打出随从；揭示反应之后才执行请求，不重新绑定另一形态。正常战吼中已发生的变形与接受之后的变形不是同一窗口。

## 同批报价与结算

1. 在同一批次开始状态采集原规则和来源；先对原随从报价一次SPELL基础预算，加入当时匹配派系的法伤并应用SOURCE数值/流转换。
2. 原随从分到`min(预算, 当前正生命)`，余量分到该随从原控制者的当前英雄。英雄余量为0时不创建第二包，随从0包仍保留普通结果语义。
3. 两份已分配量分别经过TARGET规则、重定向、免疫、圣盾、护甲和生命下限，不因第一份最终造成0伤害或额外伤害而重分英雄余量。SOURCE和法伤不重复执行；原SPELL身份、学派、来源控制者与关键词保留。
4. 两份交原`settle_health_batch`一次结算，固有吸血、实际伤害/治疗历史和回调复用原管线；整批实际结果提交后才进入公共死亡、事件反应和等待。不会在两份之间暂停或重新报价。

例如原6点对3生命随从分3/3；随从有圣盾时实际0/3，承受端翻倍时实际6/3。原伤害单位历史记录实际结果，不先记完整6再额外记3。法伤+1对5生命雪人分5/2，只加入一次。

`prepare_health(..., partition_source=...)`仅是内核同批临时入口：接受原PreparedHealth和TARGET规则，不接受其他split/lifesteal控制混用。PreparedHealth、预算及临时分配不是新的持久状态，队列只保存typed公共请求。每份事件的base_amount为已分配预算、spell_bonus为0；来源修正规则ID沿原结果保留，不能把这个0误读为没有在整笔预算计入法伤。

本变化由core-effects-v315及机制签名保护。原schema268和已有状态字段布局、观察85/命令12/replay1保持，历史机制签名不能冒作当前执行器；未知旧存档继续按原规则拒绝。恢复、回滚、克隆、回放及玩家投影使用原公共边界，全知请求操作数不发给玩家。

## 证据边界

[2025年圣盾一手报告](https://us.forums.blizzard.com/en/hearthstone/t/explosive-runes-vs-divine-shield/143361)描述随从圣盾保留其生命而英雄承受余量。[2023年法伤报告及回应](https://us.forums.blizzard.com/en/hearthstone/t/prestors-pyromancer-explosive-runes-bugged-interaction/102323)区分触发时仍存在的场上法伤和部署施法已经消费的临时下一火焰法伤。[2022年承受倍率讨论](https://us.forums.blizzard.com/en/hearthstone/t/enchanter-and-arcane-overflow/99878)支持先分配、后承受倍率。这些是社区亲历或解释，不是Blizzard当前国服规则声明。

完整raw保留未映射349/ImmuneToSpellpower标签，不据客户端标签名称把真实触发伤害静默改成免法伤，也不据卡面文字自动执行。当前明确按触发时法伤与上述内部契约实现；准确国服数值、SOURCE复杂筛选/转换、路由和整批死亡/反应窗口仍需M6校准。这个有限入口只表示过量给英雄，不能冒充过量召唤、相邻继续分配或所有同名机制已完整支持。
