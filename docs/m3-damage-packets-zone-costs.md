# 实际英雄伤害次数与区域计数费用

真实TIME_047狡诈的郊狼按本回合敌方英雄受伤次数减费，JAIL_204单监囚犯在双方没有随从时固定为2费；TIME_715为了荣耀！按敌方随从数减费，JAIL_514秘密监控按本人全部手牌数减费。CATA_452织法者的光辉和CATA_568穆拉丁的奋战复用原法术实际伤害单位、角色攻击声明计数，分别接完整6/6龙召唤及抽两张主体。完整固定源与审核配方见[卡效数据](../data/cards/quantity-cost-effects-v1.json)，进度、验收与下一项只在[项目状态](project-status.md)及[机制台账](mechanism-backlog.md)维护。

## 一次实际受伤与伤害单位

HeroDamageTakenCostSpec增加有限profile cost.enemy-hero-current-turn-damage-count-v1，复用原HeroDamageTakenCostFact的完整伤害前缀、物理分配上界、时钟及金额，不加状态字段或计数缓存。该profile每个最终目标为原敌方英雄、原全局turn相同且damage_dealt>0的已结算packet贡献1；一次6伤害贡献1，两次1伤害贡献2。来源归属不替代目标归属，敌英雄自伤也计入；护甲承担的实际伤害计入，零伤害、免疫/防止及最终转为治疗的packet不计。

原cost.hero-own-turns-damage-v1仍按本人英雄在本人行动回合实际收到的伤害单位汇总，不改成次数或当回合范围。两种profile共同校验每一原始行、连续ID、有序batch/packet与原分配前缀；原接受窗重新查询全部history，紧凑历史严格绑定原前缀且允许以后合法新增。新报价在当前全局回合重新判断；付款后新增伤害只影响以后报价，不改原支付。精确国服packet窗口、重定向和来源信用仍需校准。

## 双方无随从的固定金额

IntrinsicCostSpec增加board_no_minions与board.current-no-minions-v1，要求唯一条件及固定金额赋值。CostPresenceMatch保存原双方完整有序BOARD行；普通随从计入，包括休眠随从；地标和已有惰性交互物不计。通过注册定义判断类型/惰性，不拿玩家可见的active标志替代随从存在。条件为真时设置固有费用，之后本地附魔与外部修正仍走原费用管线。

出牌前原空场2费收据不因单监囚犯自身入场而改成5费，后续另一张同名卡按新场面报价。保存/恢复不重选时点，不把当前场面拿来覆盖原条件。

## 普通法术复用物理计数

BoardMinionCostSpec增加enemy范围，普通MINION/SPELL均可作为费用消费者；all/friendly原政策保持。原双方完整物理行保留，只有所选敌方普通随从贡献，地标/惰性交互物不计、休眠普通随从计入。

HandCountCostSpec增加friendly范围，普通MINION/SPELL均可使用。实际手牌报价计入当前物理提交牌自身及其他同名卡，friendly_other仍只排除实际subject。虚拟生成报价明确为当前手牌之外的一张假设卡，friendly计当前手牌数量加1，friendly_other计当前手牌数量；不插入或分配实体。全部原手牌、subject及分配上界保存于原HandCountCostFact，并由相同捕获/类型/金额验证器重演。

这些扩展没有改已保存字段布局，schema268及观察85/命令12/replay1保持；core-effects-v313标识新增有限profile、范围与卡牌类型资格。旧profile默认值和历史代表注册表保持。完整付款、生命周期、选择、回滚、恢复、克隆与回放仍复用原解释器；玩家投影不输出原双方手牌、报价条件或伤害证明。正式合法池与全部可达生成内容不由本实验定义子集推断。
