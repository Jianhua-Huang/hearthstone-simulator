# 普通卡池发现的原始选择连接

TLC_483 宝库闯入者需要原发现结果与原实际收件，连续发现同名牌也不能借用另一张牌。普通卡池此前只为特殊交付保留完整 ChoiceResult，普通延后交付只保存卡面。现在统一绑定原选择，并将结果保存在已选择的不可变 DiscoveryPick.result 中。实际进度、验证和下一项仅在原两份台账维护。

共享 choices.choice_effects 先沿既有入口提交 CardDiscoveryRecord，再为每个实际选中的 ResolvePoolDiscovery 注入完整原 ChoiceResult。手动、自动施法和其他自动选择仍共用原入口；未选择的候选分支必须保持 choice_result=None，selection.result=None，不能提前声称已选择。

实际 resolve_discovery 校验完整原菜单顺序、选中项、来源、玩家、提示及选择结构；require_original_result 将结果与原 card_discovery_history 的完整不可变记录对照。完成的 pick 保存该结果，批次内原 choice ID 必须严格递增且不重复；续接/待选恢复拒绝丢失、未来、错玩家或改变的原结果。选择事实仍表示选择，不能把它当作成功入手证明。

after_each 把已提交的 pick 交给原 deliver_pick。after_all 完成或无放回候选耗尽时，按原顺序逐个将已提交 pick 转换成同一组原创建效果；现有普通 DiscoverFromPool 没有生成洗牌组声明，原交付效果、检查点、RNG、费用、临时材料、溢出和反应顺序保持。此处仍由原创建器执行，没有新增交付执行器。

场上发现直接复用 DiscoverySummonOffer.result 构造同一种进度对象，保留原 producer/entry、完整候选、数量与实际召唤身份。赠礼、按印刷费用治疗、手牌后召唤复制和余项洗入继续保留自己的实际完整选择与执行器，统一边界同时核对其原选择历史。

没有新增状态/实体/玩家字段、生产 Effect、事件、游戏触发或结算检查点。CardDiscoveryRecord 原值保持，不修改 K171 已捕获的完整费用前缀。新增 payload 字段及普通选择语义使用 core460/schema377，旧1～376存档仍须原引擎；内容v256、观察93、命令12和replay1保持。原全知结果、菜单与内部帧不得进入玩家投影。这是当前提交历史的一致性检查，不提供未签名存档的来源认证，也不宣称完整批次的外部真实性证明。

本契约描述 core460/schema377 的原选择连接阶段；后续实际收件及发现后语义通知见[原交付契约](m3-discovery-delivery.md)。该后续阶段接入 TLC_483，TLC_460/460t 仍待独立实现；M0 正式池与 M6 国服精确发现/交付窗口继续独立开放。
