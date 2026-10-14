# 英雄生命实际变化事实与次数

原英雄当前赋值也进入本页共同事实：hero_health_set保存实际剩余量变化，最大量保持；不变不追加次数，原本人区间/付款消费者与恢复沿原历史。见[赋值契约](m2-remaining-hero-health.md)，没有新生命历史或计数缓存。

血肉巨人SCH_140要求本人回合中英雄生命变化的次数，且获取本牌前的变化也有效。已有当前缺失生命报价、单包HealthResult和尸体资源历史均不能代替这个数量。必要[完整本地raw/pin](../data/support/hero-health-change-basics.json)为10费8/8；官方[卡库检索](https://hearthstone.blizzard.com/en-us/cards/59585-flesh-giant)支持卡文，打开仅导航，不证明精确国服提交窗口。实际执行与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

## 原提交、单一事实

新增hero_health_history.py只记录原处理器已经产生的实际数值，不执行伤害、治疗、支付或属性变化。不可变HeroHealthChangeRecord保存原玩家、活动方、回合、动作、本人回合区间、原事件类型、前后物理英雄及卡面、最大/当前生命。GameState只有hero_health_change_history及next_hero_health_change_id两个新增字段；无Entity/Player累计缓存、卡牌字段、Effect、玩法事件类型、外部动作或新生命执行器。

原事件携带私有hero_health_transition完整前后九元组及hero_health_change_id，真实变化指向唯一事实，未变化为None。记录只在当前生命前后不相等时追加：金额或护甲变化、最大生命单独变化、未生效治疗/伤害、防止、消灭标记都不是变化次数。最大/当前生命政策仍由原处理器决定；不改变它们的公式、数值和死亡检查点。

原有负属性操作可以产生负生命上限并进入原终局检查；事实忠实保存该整数结果，不新增非负上限限制。

| 原提交入口 | 记录依据与原事件 |
| --- | --- |
| 原伤害/治疗批次 | 每包实际HealthResult，包含转换、吸血及现有伤害下限；health_resolved，增长替换不再另计 |
| 原LoseHealth | 实际扣除或替换结果；health_lost、原增长事件或health_loss_floor_resolved，只选择一个依据 |
| 原最大生命增减/转移 | 原当前生命实际变化；max_health_gained/max_health_lost，原两方转移保持同一原子窗口 |
| 原生命支付 | 共享纯PaymentPlan的资源写入同时写事实，health_spent绑定原前后；护甲部分不当作扣血 |
| 原Buff/SetStats及移除/到期 | 原属性运算和生命钳制结果；stats_changed/enchantment_removed/attachments_expired |
| 原英雄替换/恢复 | 原物理前后英雄及实际当前生命；hero_replaced/hero_recovered；仅换身份而生命相同不增加次数 |

原批次的每个数值包在提交时记录，原事件批量发布前记录全部就绪，首次原监听读取完整已提交批次。没有新触发或检查点。原生命支付的纯投影和实际写入共享同一事实，资源提交后、原支付事件捕获前记录存在；支付证明不单独补写或猜测。

## 纯数量与真实回合

health_change_count(state, player_id)仅遍历可保存的State事实，不扫描宿主事件。只计原player_id等于原active_player且有真实owner_turn_id的记录；不依据全局回合奇偶、目前活动方、今天的英雄或卡牌获取时间推断。

场景初始化不增加次数；完整开局中真实回合开始前产生的数值变化仍保存为owner_turn_id=0，排除于本人回合数量。原回合开始、结束反应和到期区间沿owner_turns.py的真实区间，尚未关闭的终局区间保持原政策。对手回合变化有记录但不计本人回合数量，后续获取读取此前有效前缀。

## 回溯及严格保存

原回溯恢复完整before State，因此撤销尝试的生命事实及本账本游标也被恢复，不能给重试重复减费。宿主事件仍保留每个尝试；边界校验按原timeline_rewound/event_start退休已撤销后缀，只绑定当前有效时间线的完整事实。事实身份仅在当前保存时间线连续，未宣称在撤销尝试之间保持全局单调。

数量查询不用这一宿主日志筛选。原回溯自身的物理身份分配、随机、资源和玩家知识仍沿原机制；本账本不增加新回溯执行器。保留累计结果的来源仍按既有机制执行，不能把真实恢复与保留结果混同。

严格状态读取要求两个新字段以及记录全部字段；拒绝bool/浮点整数冒充、未来物理英雄、错误卡面、回合区间、游标或原事件映射。原health_resolved继续保存一个完整HealthResult，并核对新增英雄过渡元信息。等待帧复用model中冻结类型及原State读取，snapshot/clone/replay与事务回滚使用相同账本。

原事件前后封套与State账本进行完整映射校验，不能删除一端而保留另一端。该内部一致性校验不认证未签名存档的外部来源，也不证明协同重写原时间线与全部事实的真实性。

## 信息与下一消费者

玩家只见原公共英雄生命与日志；私有历史、游标、过渡封套及捕获状态不输出到observe/PlayerPort。host API可从hs_sim.engine导入HeroHealthChangeRecord和health_change_count；卡牌行为读State副本，不直接写账本。

事实基础引入prototype-v212/core-effects-v206/schema200，观察74、命令11和外层replay1保持。现行共享协议及已接入的必要SCH_140有限费用消费者见[费用契约](m3-hero-health-change-costs.md)；原数值事实/时钟/回溯不变，不做组合或任意公式。精确国服变化口径、上限/替换/支付/批次窗口待M6；U53/U59整体、完整基础清单、H2/M0/M6/M7及最终模拟器目标仍未完成。
