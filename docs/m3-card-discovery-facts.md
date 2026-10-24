# 真实卡牌发现的选择事实

公共查询 `hs_sim.engine.card_discoveries.discovered_cards(state, player_id, turn=None)` 返回原完整选择收据；`discovered_this_turn(state, player_id)` 只检查本全局回合和原选择玩家。查询读取状态，不扫描事件、后来手牌或同名实体。具体内部验收与下一项只在两份原台账维护。

原有 `POOL_DISCOVERY` 继续保留其严格池分支验证。非卡池的真实卡牌发现显式使用 `ChoicePurpose.CARD_DISCOVERY`；每次必须从完整卡面选项中选择一张。`ChooseFromZone.discovery` 默认 False，仅真实来源显式声明 True。当前暗影视界、追踪术、恶火领教、似曾相识、命运交织、陷害及探险者拉法姆采用该声明；死去巨龙发现和原牌黑暗之赐使用明确卡牌发现目的。瞳中之眼仅查看并选择对手牌库顶，保持普通选择。

`DiscoverForPlayFollowup` 的首次菜单是真实发现，奖励菜单仍为普通 EFFECT；后者的原余项、物理手牌驻留及消费逻辑保持。不能把所有带 card_id 的菜单、抉择、适应、组装、随机生成或普通区域选择当作发现。不用卡名、提示文案或原始规则文本在运行时推断目的。

原 `choices.choice_effects` 在手动或自动选择已完成后、原选中工作开始前提交事实；自动施法、间接战吼、英雄技能和物理使用仍共用原随机选择入口。未选择的等待、空池和选择失败不产生已提交事实，异常回滚恢复原等待。每次实际发现保留独立 ChoiceResult，来源消失、同名牌和后来区域变化不能改写原选择。

不可变 `CardDiscoveryRecord` 保存顺序ID、全局回合、动作、真实回合区间、原选择事件和私密发布事件，以及完整 ChoiceResult。发布为不捕获游戏触发的 `card_discovery_recorded`，不新增解释器Effect或死亡/结算检查点。实际状态与原有效事件逐项对照；回溯复用既有 effective_events 撤销尝试后缀，查询始终读恢复后的状态。完整原菜单、选中项与发布内容受保存/恢复一致性验证，不提供未签名存档来源认证。

此收据表示一次真实卡牌选择，独立于其后原生产者的入手、烧毁、复制、牌库顶或场上交付。成功选择后满手烧牌仍有选择事实。它没有声称实际收件实体，也不提供 after-Discover 游戏触发。TLC_483 宝库闯入者的原实际收件实体和 TLC_460t 源生之石的其余选项使用/耐久须另行完整实现，不能用此收据或后来的同名牌替代。

TLC_462 出土神器组合该布尔查询与原 GenerateFromPool：无本回合发现时随机召唤印刷两费可收藏随从，有时改为四费；随机召唤不限当前职业。合法候选未接入须显式失败，不按已实现程度裁池。constructed.cards 正式池仍独立于实验夹具验收；这不认证 M0 标准正式池。

新增状态与选择目的使用 core458/schema375/观察93；命令12/replay1保持。旧存档须原引擎，历史证据不重标新身份。选择事实的精确窗口、地图第二菜单分类、烧牌及自动起源细节仍需 M6 国服校准；本契约不是服务端一致性证明。


## K488 原发现的来源记忆与延后猜牌

[两份可疑来源及原谜题](../data/cards/past-suspicious-guess-cards-v1.json)复用DiscoverFromPool.memory_target，新增有限DiscoveryGuessTarget。目标绑定原战吼行为、实际玩家/来源及原物理在场引用；只允许普通当前职业法术或传说随从的一次三选一手牌交付，其他发现参数保持原声明检查。没有新增DiscoverFromPool或CardDefinition字段，不从卡牌数据标签生成任意可执行回调。

选择仍由原CardDiscoveryRecord保存完整真实结果及OriginalDiscoveryOffer。实际MaterializeDiscoveredCard/FinishCardDiscovery完成后，才为仍匹配的原随从安装独立零数值Enchantment.discovery_guess，保存原battlecry_id、discovery_id和实际接收者SourceAllocationFact。原接收者包括普通满手烧毁事实；原来源已离开引用或无法安装时，不把记忆交给另一身体。新附魔不改变属性、费用或玩家资源。

一个通用授予的turn_started监听处理本实体全部独立谜题，多次战吼不会产生多个监听各自枚举全部记忆。每份谜题在原对手实际开始时接受一次问题，接受即移除该附件，最后一份清理监听；此前死亡、沉默和正常回手重置沿原附件生命周期处理。复制的来源使用新的附件身份并保留各自原选择，转控后猜牌者保持原对手，这是明确待国服核定的政策。

猜牌不新增发现事实，ChoicePurpose保持EFFECT；它只展示原三备选的完整实际顺序及预览，不重新抽池或查询现在的手牌。菜单、原答案、来源与实际开始事件按同一请求保存，普通选择处理等待、异常回滚、恢复和回放。私有offered/finished事件仅用于一致性校验，游戏奖励读取State原发现记忆，不扫描诊断日志推测答案。原始记录和等待帧均不能作为玩家DTO。

共享原发现复制执行器根据精确原驻留选择材料：原牌仍在同一手牌驻留时复制当前材料，保留手牌属性/费用；原牌离开或改变驻留时按原交付配方重建，不寻找另一张同名实体。两条分支都保留原实际接收者的复制来源，复制不再算一次发现。猜牌的完整来源、历史依据及未校准政策见[来源说明](../outputs/card-integration-20261014/k488-past-suspicious-guess/source-design-02.json)。精确国服窗口、显示顺序、转控及特殊材料仍待M6/M7，实际结果与下一项只在两份台账维护。
