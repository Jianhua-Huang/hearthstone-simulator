# 持续玩家程序在实际入场时设值

BE_209耐普图隆安装独立的持续PlayerEffect，不同步修改已有随从、手牌或牌库。SummonEntryStatsProfile只声明来源、原程序、当前种族筛选及完整SummonStats；实际新入场由原属性设置设施执行，来源死亡、沉默或转控不移除旧玩家的程序。多个真实安装独立保存，各次设为5/5，不相加。

普通enter_minion在物理材料、当前复制和显式入场属性安装后、战吼与召唤通知前接受程序。真实光耀之子因此先成为5/5，再按自己的5点生命值执行原战吼。[开发者答复](https://www.reddit.com/r/hearthstone/comments/1whw4cv/reign_of_the_black_empire_how_does_this_work/?sort=qa)明确这一相对顺序；召唤覆盖与普通光环、复生生命值、沉默移除等精确政策仍待国服校准。

附肢、号角士兵和星舰等直接发布召唤通知的路径，通过公共通知入口接受同一原入场窗口。窗口按物理实体和原board_presence_id唯一，保存当时已匹配的原程序集合，空集合也保留；后通知不重复设置，也不把较晚安装的程序追溯到旧入场。临时查询索引只从有效原事件重建，恢复/回溯更换状态后重新建立，不作为独立进度存档。

实际受益者决定程序归属。当前复制的材料和伤害先安装，再进行5/5设置；固定入场属性也遵循这一顺序。变形不视为新召唤，不重新应用；再次真实离场/入场有新窗口。未知当前种族不当作空种族或从候选删除，实际动作明确失败并回滚。

私有安装、入场窗口和属性应用事件，连接原战吼、玩家实例、物理在场和属性附件。恢复检查已接受程序、原实例及完整窗口/应用对应，玩家DTO和公开日志不包含这些证明。它核验保存内容一致性，不认证未签名存档的来源。

复用普通PlayerEffectSpec、PlayerEffect、Enchantment及属性执行器，无新Effect或GameState/Entity/PlayerState字段。apply_summon_stats只增加可选来源/标签，旧默认保持。core611/schema503，保存布局不变，旧core610仍须原引擎；观察114/命令12/replay1保持，默认311注册表指纹保持。真实主卡与光耀之子完整原行/双语主面、两原附魔证据独立保存；附魔证据不冒充可执行卡牌。进度和下一项仅在两份原台账维护。


## K484 下一次使用与召唤完成的不同窗口

SummonEntryStatsProfile保留默认set，仅增加next_play_add这一有限模式供星光漫游者使用。它在原反制/容量接受后、物理入场或磁力材料冻结前消费并安装普通属性附件。普通apply_entry不重复消费该模式，旧耐普图隆设值政策保持，见[原使用材料契约](m3-next-draenei-basics.md)。没有next_summon_add模式。

刺鬃乐师ETC_831的Finale读取原实际出牌条件，安装普通独立PlayerEffect，监听私有minion_summon_finished。其奖励先移除原实例，再用BuffCapturedMinion交付+1/+1。原来源死亡、沉默和转控不撤销已安装程序；新程序的安装时钟必须早于原随从入场，不能追溯消费当前创作者，也不永久排除同一个来源实体。

CompleteMinionSummon复用原成功召唤、付费PlayRecord或完整生成PhysicalReplayProgress，保存原物理入场分配；原连续在场、当前受益玩家及活跃存活资格共同决定通知。普通召唤在原入场反应完成后接受；付费主随从在原generic on_play、战吼及连击主体后、FinishPlay前接受；整卡重演仅第一份实际交付等待自身完整生成主体，数量额外体独立完成，不借主随从的战吼。巨型附肢及战吼/延系产生的子体可先完成，休眠体不消费奖励，变形没有新召唤窗口。

原完成关闭与通知逐项对应，待选队列须保留原付费召唤的唯一完成尾；选择不能制造内部控制。上述证明及原入场材料不进入玩家DTO/日志。新增一个可保存Effect，没有新增GameState、Entity、PlayerState或其他模型字段/显式payload类型；普通消费、属性、死亡、随机和选择仍由原执行器负责。

初始入场前方案被[2025年玩家附回放的原始报告](https://us.forums.blizzard.com/en/hearthstone/t/thornmantle-musician-and-crater-experiment-ordering/153453)及[2023年玩家实际测试](https://www.reddit.com/r/CompetitiveHS/comments/140kves/)否定，因而改为上述完成窗口。这些是一手历史观察，尚不能认证固定国服37.0的全部时序；精确唤醒、当前种族/控制、触发排序及完整生成域仍分别核定。保存一致性不等于未签名存档来源认证。
