# 实际护甲获得与当前回合条件

本契约服务于BE_559力量展现的真实条件。实际进度、验收及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护；卡面存在、内部执行和国服校准分别记录。

`armor_gains.py`保存不可变`ArmorGainRecord`：物理英雄、玩家、活动玩家、原turn/action/本人回合区间、原余额、增加量、提交后余额、事件位置与入口。`GameState.armor_gain_history`保存有序事实，没有第二个护甲账户或可变累计缓存。

原`GainArmor`和三种英雄安装路径在数值提交后、原公开通知前调用同一记账入口。普通手牌英雄使用`hero_card`，`ReplaceHero`使用`replacement`，`InstallGeneratedHeroCard`使用`generated_hero`。安装只记录新授予的护甲，旧余额不重复计算。零数量保存原操作但不满足正增甲条件；场景初始护甲、吸收、失去与支付不成为增甲。原支付、死亡、检查点和公开通知保持；安装继续发布原`hero_replaced`，授甲是否还应发布普通`armor_gained`属于待国服核定的既有通知政策。

`gained_this_turn(state, player_id)`只查询本玩家当前全局turn的正量State事实，不读当前护甲或宿主日志。花光护甲、换英雄不取消已发生的事实；零量、对手与过去回合不满足。力量展现通过普通`InvokeBehavior`取得实际执行的新上下文，再接受伤害或消灭分支，避免payload上下文先于已捕获的施法开始反应。接受后，本次伤害反应新获护甲不改写同一分支；后续使用重新查询。假分支为3点原来源SPELL伤害，真分支为普通Destroy，没有新CAST、额外付款或卡牌层结算器。

每份事实发布私有`armor_gain_recorded`，紧接原`armor_gained`或`hero_replaced`。恢复核验全部有序事实、有效时间线中的完整私有事件及原公开操作，拒绝裁行、错金额、英雄、回合/区间或重复位置。允许后续合法余额变化和英雄替换。普通State、事务、Rewind、JSON、FrameCodec与回放负责保存或撤销；退休的回溯尝试不污染查询。有效事件只在边界核验使用，结构一致性不认证未签名存档来源，也不重建全部历史护甲余额。

core615/schema506要求新字段及严格类型化完整记录，拒绝旧schema1～505；观察114、命令12与replay1保持。私有事实不进入玩家DTO。精确国服条件接受、零量通知、安装授甲触发及继承政策仍需M6证据；M0正式池与完整可达域独立闭合。


## K486 原增甲的独立额外奖励

[剃刀沼泽摇滚明星](../data/cards/past-passive-armor-spirit-cards-v1.json)以有限ArmorGainBonusProfile声明原生随从监听及固定2点奖励。extra_from_context核验原armor_gain_recorded完整payload和发生身份，只接受来源控制者的正量普通根；零量、对手及已标记奖励子行不再生产这种奖励。每个原根的每个物理在场来源独立接受一次，多个来源各加2，不互相递归。其他普通增甲监听仍能收到真实子增甲，不将奖励静默隐藏成余额改写。

GainExtraArmor冻结原父行和SourceAllocationFact，沿既有armor/GainArmor写入、记账及通知。ArmorGainRecord仅添成对可空bonus_parent_id、bonus_source；普通授予两者均空，没有第二个护甲账户。奖励父必须是同受益者的正量非奖励根，子行须在原父之后、同turn且不早于原action，金额为2，同原父/物理来源驻留不能重复。已接受奖励保留原接收者和来源事实，后来离场/转控不重新寻找另一来源；未来根仍按原活跃监听资格捕获。

完整历史与待执行GainExtraArmor共同核验原分配、原父、重复交付及严格类型，沿原FrameCodec、回溯、事务和玩家隔离。普通英雄安装授甲可成为原根，原公开hero_replaced与armor_gained各自政策保持。反递归及精确事件窗口是当前本地执行契约；历史玩家观察不等于CN37正式校准，也不为未签名存档提供来源认证。实际结果和版本仅在两份主台账维护。
