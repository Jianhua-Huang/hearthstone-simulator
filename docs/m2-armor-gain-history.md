# 实际护甲获得与当前回合条件

本契约服务于BE_559力量展现的真实条件。实际进度、验收及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护；卡面存在、内部执行和国服校准分别记录。

`armor_gains.py`保存不可变`ArmorGainRecord`：物理英雄、玩家、活动玩家、原turn/action/本人回合区间、原余额、增加量、提交后余额、事件位置与入口。`GameState.armor_gain_history`保存有序事实，没有第二个护甲账户或可变累计缓存。

原`GainArmor`和三种英雄安装路径在数值提交后、原公开通知前调用同一记账入口。普通手牌英雄使用`hero_card`，`ReplaceHero`使用`replacement`，`InstallGeneratedHeroCard`使用`generated_hero`。安装只记录新授予的护甲，旧余额不重复计算。零数量保存原操作但不满足正增甲条件；场景初始护甲、吸收、失去与支付不成为增甲。原支付、死亡、检查点和公开通知保持；安装继续发布原`hero_replaced`，授甲是否还应发布普通`armor_gained`属于待国服核定的既有通知政策。

`gained_this_turn(state, player_id)`只查询本玩家当前全局turn的正量State事实，不读当前护甲或宿主日志。花光护甲、换英雄不取消已发生的事实；零量、对手与过去回合不满足。力量展现通过普通`InvokeBehavior`取得实际执行的新上下文，再接受伤害或消灭分支，避免payload上下文先于已捕获的施法开始反应。接受后，本次伤害反应新获护甲不改写同一分支；后续使用重新查询。假分支为3点原来源SPELL伤害，真分支为普通Destroy，没有新CAST、额外付款或卡牌层结算器。

每份事实发布私有`armor_gain_recorded`，紧接原`armor_gained`或`hero_replaced`。恢复核验全部有序事实、有效时间线中的完整私有事件及原公开操作，拒绝裁行、错金额、英雄、回合/区间或重复位置。允许后续合法余额变化和英雄替换。普通State、事务、Rewind、JSON、FrameCodec与回放负责保存或撤销；退休的回溯尝试不污染查询。有效事件只在边界核验使用，结构一致性不认证未签名存档来源，也不重建全部历史护甲余额。

core615/schema506要求新字段及严格类型化完整记录，拒绝旧schema1～505；观察114、命令12与replay1保持。私有事实不进入玩家DTO。精确国服条件接受、零量通知、安装授甲触发及继承政策仍需M6证据；M0正式池与完整可达域独立闭合。
