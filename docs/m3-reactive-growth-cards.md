# 原生触发、个人施法与原休眠唤醒

本页维护接入和扩展契约；实际进度、验证与下一项仅在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)。完整原行及显式配方见[固定数据](../data/cards/reactive-growth-effects-v1.json)，执行适配见[原生触发模块](../hs_sim/cards/reactive_growth_cards.py)。文字和未知数字标签不自动生成行为。

## 事件事实与卡牌资格分开

鱼人招潮者匹配己方实际召唤，排除自己的入场，按当前鱼人身份增攻。哀嚎蒸汽匹配己方实际手牌出牌，排除自身及非随从，读取原提交卡面与手牌附魔形成的元素身份。召唤不冒充打出，未知原种族明确报错并回滚。

安东尼达斯在本人手动施法开始时生成火球，原手动根即使反制仍有开始事实；自动、抽取、历史与额外重复不是第二次本人出牌。命名的COLLECTION_RELATED_CARD_DATABASE_ID=315锁定既有完整CS2_029，不按同名或Core前缀猜别名；三个旧版身份原行仅作身份依据，不增加可执行定义。

狂野炎术师使用原card_played/PlayRecord，匹配整次完成、本人、SPELL及未反制，全部重复主体完成后执行一次。若原来源已死亡则没有新的完成监听。续接时查询双方当前可交互随从，发一个MINION_ABILITY DamageBatch，法强不增加此伤害。既有战地医师老兵的同类问题一并修正：本人神圣法术整次完成后召唤一个医生，代施法不触发，额外重复不增加个人出牌次数。

历史[前后窗口报告](https://us.forums.blizzard.com/en/hearthstone/t/mana-bind-vs-flare/1931)和[反制讨论](https://us.forums.blizzard.com/en/hearthstone/t/in-which-order-do-secrets-trigger/14852)支持区分“每当”和“之后”；[个人与代施法讨论](https://us.forums.blizzard.com/en/hearthstone/t/how-does-the-coin-work-exactly/106242)及[自动施法报告](https://us.forums.blizzard.com/en/hearthstone/t/whenever-you-cast-a-spell/2528)支持个人资格限制。这些是社区历史资料，不是当前国服官方确认；重复根关闭、反制和来源窗口仍待M6校准。

公共spell_cast_started补齐手动及重复记录，每个实际记录仍有自己的开始通知；原自动记录、独立payload接受与逐次完成事实保持。通用事件不能直接等同所有“你施放”的触发资格。手动外层与自动内层可各自暂停，恢复须处理两个真实等待，不重复付款。

## 健康、死亡、回合和技能

暴乱狂战士与托尔托拉读取health_resolved完整结果，只接受正数实际伤害；英雄受伤不触发狂战士，圣盾或防止不伪造伤害。托尔托拉只监听本体，给当前控制者一点护甲后增原随从攻击。伤害、死亡及来源生命周期交公共层。

死亡侍僧与食腐捕蝇草按minion_died的death_id读取冻结DeathRecord，核对原实体与控制者。前者只匹配己方死亡材料的当前亡灵身份，后者取得死者最终攻击；不读取新驻留同名牌，不把全局死亡监听当亡语上下文。

微型战斗机甲订阅双方真实开始。树皮盾哨兵、灭龙弩炮与林精使用既有is_inspire：本人成功完成的手动英雄技能；对手技能及间接主体不计。弩炮在续接时从当前敌方角色随机造成5点随从能力伤害，树皮给原随从两点生命。

## 唤醒原休眠实例

林精无限期休眠，只安装dormant_triggers。AwakenCapturedMinion保存MinionReference和原DormancyState.id，核对物理驻留与同一个休眠实例后，委托原AwakenMinion。离区、新驻留或先醒后重新休眠使旧请求失效；永久载体仍不能唤醒。不新建实体、不触发召唤/战吼、不授予立即攻击。

指令复用原私有帧、严格解码、异常回滚、clone和回放；没有新持久状态字段，schema270保持，语义由core-effects-v330保护。原引用、休眠实例、完整历史与工作帧不进入玩家DTO。

`python -B -X utf8 -m examples.card_reactive_growth`以原玩家命令展示触发与唤醒，各稳定位置独立恢复、克隆与回放。跨职业和显式法力属于实验，不认证正式标准套牌；正式卡池、热修、全部可达内容与国服校准仍须独立闭合。
