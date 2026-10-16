# 当前属性选择、手牌增益与原抽牌费用

本页定义扩展契约。实际结果和下一项仅在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。完整卡面及配方见[stat-draw数据](../data/cards/stat-draw-effects-v1.json)。

`hs_sim.engine.spell_targets.RandomSpellTarget(candidates, source_id, operation, amount=0)`接受原普通随从`MinionReference`，伤害分支也可接受物理英雄ID。operation只允许damage/destroy，destroy不接受英雄或伤害数值，同一实体只有一个权重。来源必须是真实已分配SPELL。空池无抽样，单项直接选中，多项按原实体ID排序均匀抽取并发原random_choice事件；后续`ApplySpellTarget`再次核对选中引用，随从离场再回、换控制/卡面等失效不重绑、不重抽。英雄仍须是其控制者当前HERO槽的实际存活对象。选中后的攻击/生命变化不重算已经接受的选择；下一次独立选择才查询新局面。

这两个请求不自己执行死亡或伤害：destroy调用原消灭处理，damage直接调用原settle_health_batch，保留防护、法伤、路由、数值修正、吸血、健康历史及死亡检查。没有新GameState字段，旧RandomDamage/RandomDestroy声明和处理保持。新注册效果和执行语义由core321、内容包v21标识，schema268不变；不是认证旧核心存档兼容。

- 生而平等对当前双方存活、非休眠、普通随从声明SetStats(health=1)，由原有序本地附魔/光环层处理，清除原受伤量；英雄、手牌、休眠与交互载体不计，不产生伤害或消耗圣盾。
- 窒息在本主体查询当前敌方最高可见攻击的合格随从，完整并列组交RandomSpellTarget；隐身不阻挡非指定目标的选择，休眠不参与。
- 复苏烈焰用两个命名InvokeBehavior依次查询当前剩余生命最低敌角色，包含英雄；各次独立接受/抽选，原生命/法伤/死亡/反应改变下一次查询。固有吸血交健康批次。
- 真言术：障先对指定角色GrantKeyword(DIVINE_SHIELD)，再调用现有BuffMinionsInZones，仅当前本人HAND随从+2生命。绵延传承先给予英雄本回合攻击，再查当前实际牌库有无MINION；无则给当前HAND随从永久+4攻击。空牌库满足无随从，牌库未知定义仍报错。手牌增益用原CardReference，后续召唤/沉默/离场按既有区域与附魔生命周期执行。
- 最终定局用DrawMatching对实际牌库印刷undead随从过滤、原random选择和skip空匹配政策，然后Imbue(count=2)。没有匹配不导致疲劳，也不阻止灌注。当前英雄职业决定原映射，不自行实现第二份技能或灌注计数。

神圣石索使用`hs_sim.engine.spell_sequences.DrawIfCheap(player_id, maximum, source_id)`。调用原draw_one后立刻读取该次DrawRecord的原实体，并用quote_unselected_cost对实际落点报价；只报价，不消费减费次数或支付。金额不超过门槛时，在原抽牌链完成后追加一次普通Draw。条件在抽牌反应前固定，额外/替补抽牌不能替代原对象，也不递归增加本卡次数。fatigue无卡，不能满足；burn/cast仍有原物理卡，本地政策保留其费用判断。hand到达计入当时实际适用费用，局部减费也有效；后续反应不改已经接受的金额。没有另造抽牌或费用账本。

证据边界：完整37.0源证明文字、费用、职业、关键词和学派。上述生命设置/光环层、目标捕获/并列RNG、两次伤害间窗口、神圣石索费用读取时机及burn/cast处理均是明确内部执行契约，尚未固定补丁国服官方校准。不能用自建测试证明服务器时序；正式池/热修、实际可达来源和阶段验收保持独立。
