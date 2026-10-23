# 条件战吼、当前属性与物理牌库

本页维护接入契约；实际进度、验收证据及下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)登记。十六张卡的完整原行、显式配方和pin在[conditional-battlecry数据](../data/cards/conditional-battlecry-effects-v1.json)。

卡牌原生battlecry复用现有属性、伤害、冻结、Imbue、抽牌和存储费用。霜冻小鬼冻结本体；女祭司给当前敌方普通随从-2攻击至下次本人开始，再灌注；时光锯刃为完整3/2武器并由战吼灌注，原装备替换、英雄贡献和磨损保持。

轮回编织者和灰叶树精使用原quote_unselected_cost读取本方当前手牌法术金额，至少5才分别伤害或授予圣盾/吸血。织梦者和花木护侍查询原imbue_count至少2；前者原MINION_ABILITY伤害并保印刷吸血，后者原Draw两张。幸存者从hero_damage_taken查询本回合本人英雄实际正伤害，包含护甲，不以当前缺血替代；精魂用activated_powers的manual/当前turn查询，效果触发不当作使用技能。没有副计数器。

三个目标规则通过原PlayerTargetRuleSpec注册：编织者只看本方玩家DTO手牌kind及当前cost.amount，织梦者只看本方公开imbue.count，害虫克星只看原目标公开当前tribes。未知种族明确报错，不当无类型过滤。玩家动作枚举、原接受输入和恢复使用同一注册协议；行为主体仍可用可信状态复查自身条件。全知GameState不交给玩家谓词，也不从闭包捕获Game。原TargetSpec(IF_AVAILABLE)维护无条件时无目标入场与有匹配时选择，持牌条件变化后不另找替代目标。

神圣布蛋者使用`hs_sim.engine.zones.DrawMinionWithAttack(player_id, attack, source_id)`，当前只有该真实0攻击抽牌需求。它查本方实际DECK实体的当前kind/attack，保留每个物理实体权重，沿原RNG一次choice和MoveCard(draw=True)；同卡面不同附魔可分别匹配。不改PoolQuery、普通DrawMatching或生成池，不自行移动实体、制造DrawRecord或另发随机选择通知。空匹配不疲劳/不耗随机；满手交原draw/burn结果，新请求本身可在队列中等待并经FrameCodec恢复。新指令由core324保护，旧保存布局schema268保持，无新增GameState字段。

扒窃机按实际牌库数量至少25抽牌；笼中颅骨按执行时剩余物理手牌加生命。克洛纳捕获原牌库底最多五张CardReference并ModifyStoredCost(set_to=1)，不重排或改绑。青铜龙士兵用原DoubleStats(health=True)，增加当前剩余生命至最大值，保留原伤害，不按印刷生命倍增或重置受伤。后世之嗣按当前双方受伤普通随从数量给本体+2/+2，英雄不参与。

`python -B -X utf8 -m examples.card_conditional_battlecries`用玩家命令运行全部根卡，逐稳定位置独立恢复/clone/回放。场景为混合职业40法力实验，部分牌库含实验衍生物或重复卡，不认证正式标准套牌。条件的原接受/主体复查、当前与印刷攻击、剩余生命、手牌价格、人工/效果技能归属、到期和分段顺序是内部契约；正式卡池、热修与精确国服证据仍待M0/M6。


## K478 历史条件战吼与实际承伤资格

BT_711、DED_503和TOY_386是标准可达历史依赖，完整源包在[past-conditional-battlecries](../data/cards/past-conditional-battlecries-v1.json)。钉棍终结者的PlayerTargetRuleSpec只读本人公开奥秘槽，原主体复查当前奥秘并用ReturnCapturedMinion(to_owner=True,cost=+2)，失效目标不换另一个同名体。原回手器负责重置、owner/控制迁移、费用、入手与满手死亡。

有限HeroDamageTakenTargetProfile声明唯一actual_received_damage_current_turn依据，与原HeroHealthChangedTargetProfile分开；注册指纹包含明确条件。沿同一原生健康目标入口读取原hero_damage_taken>0，护甲吸收仍是实际承伤，零/阻止/敌方/以前回合不代替本回合本人正量。现有effective_target_spec把无条件时的目标域关闭，付款前目标接受、玩家命令与自动入口保持同一规则。没有新增玩家可见历史、全知玩家谓词或累计账户。飞刀手在主体实际执行时再读原承伤数，已提交空目标不会因等待期间新承伤而补选。

礼盒雏龙遍历完整当前本人手牌，用现有种族求值匹配龙/all，未知明确报错。空候选保持白板、单候选直接奖励；多候选复用原RequestChoice(sample_size=1,min/max=0)及完整物理引用自动抽样，无玩家菜单或发现信用。原手牌Buff后再给原来源Buff；普通召唤不调用战吼，额外战吼各自重新接受当前条件。精确分布、这项顺序及原目标/条件窗口尚未CN校准，普通卡面和第一手反馈不认证全族规则。

core701/schema560保护新有限资格，内容v568新增三依赖；无新Effect、payload、模型或玩家DTO字段，既有生命变化资格及普通回手/伤害/属性写入器保持。实际执行和下一项仍仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。
