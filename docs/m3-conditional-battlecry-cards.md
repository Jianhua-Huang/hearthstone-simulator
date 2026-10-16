# 条件战吼、当前属性与物理牌库

本页维护接入契约；实际进度、验收证据及下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)登记。十六张卡的完整原行、显式配方和pin在[conditional-battlecry数据](../data/cards/conditional-battlecry-effects-v1.json)。

卡牌原生battlecry复用现有属性、伤害、冻结、Imbue、抽牌和存储费用。霜冻小鬼冻结本体；女祭司给当前敌方普通随从-2攻击至下次本人开始，再灌注；时光锯刃为完整3/2武器并由战吼灌注，原装备替换、英雄贡献和磨损保持。

轮回编织者和灰叶树精使用原quote_unselected_cost读取本方当前手牌法术金额，至少5才分别伤害或授予圣盾/吸血。织梦者和花木护侍查询原imbue_count至少2；前者原MINION_ABILITY伤害并保印刷吸血，后者原Draw两张。幸存者从hero_damage_taken查询本回合本人英雄实际正伤害，包含护甲，不以当前缺血替代；精魂用activated_powers的manual/当前turn查询，效果触发不当作使用技能。没有副计数器。

三个目标规则通过原PlayerTargetRuleSpec注册：编织者只看本方玩家DTO手牌kind及当前cost.amount，织梦者只看本方公开imbue.count，害虫克星只看原目标公开当前tribes。未知种族明确报错，不当无类型过滤。玩家动作枚举、原接受输入和恢复使用同一注册协议；行为主体仍可用可信状态复查自身条件。全知GameState不交给玩家谓词，也不从闭包捕获Game。原TargetSpec(IF_AVAILABLE)维护无条件时无目标入场与有匹配时选择，持牌条件变化后不另找替代目标。

神圣布蛋者使用`hs_sim.engine.zones.DrawMinionWithAttack(player_id, attack, source_id)`，当前只有该真实0攻击抽牌需求。它查本方实际DECK实体的当前kind/attack，保留每个物理实体权重，沿原RNG一次choice和MoveCard(draw=True)；同卡面不同附魔可分别匹配。不改PoolQuery、普通DrawMatching或生成池，不自行移动实体、制造DrawRecord或另发随机选择通知。空匹配不疲劳/不耗随机；满手交原draw/burn结果，新请求本身可在队列中等待并经FrameCodec恢复。新指令由core324保护，旧保存布局schema268保持，无新增GameState字段。

扒窃机按实际牌库数量至少25抽牌；笼中颅骨按执行时剩余物理手牌加生命。克洛纳捕获原牌库底最多五张CardReference并ModifyStoredCost(set_to=1)，不重排或改绑。青铜龙士兵用原DoubleStats(health=True)，增加当前剩余生命至最大值，保留原伤害，不按印刷生命倍增或重置受伤。后世之嗣按当前双方受伤普通随从数量给本体+2/+2，英雄不参与。

`python -B -X utf8 -m examples.card_conditional_battlecries`用玩家命令运行全部根卡，逐稳定位置独立恢复/clone/回放。场景为混合职业40法力实验，部分牌库含实验衍生物或重复卡，不认证正式标准套牌。条件的原接受/主体复查、当前与印刷攻击、剩余生命、手牌价格、人工/效果技能归属、到期和分段顺序是内部契约；正式卡池、热修与精确国服证据仍待M0/M6。
