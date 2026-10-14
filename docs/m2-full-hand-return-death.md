# 场上随从回到满手时的死亡

本增量修复原ReturnToHand满手分支直接移入墓地、跳过死亡记录与亡语的问题。复用[实体生命周期](m1-lifecycle.md)与[死亡归因](m5-death-attribution.md)，没有新增回手、死亡或触发执行器。实际进度和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

ReturnToHand先按原to_owner选择目的玩家，并使用现有hand_capacity查询实际容量。正常回手沿原移区、印刷重置与可选费用流程。手牌已满时，原随从继续保持BOARD、原owner和当前controller；标记普通destroy/ReturnToHand原因与doomed，由原死亡协调器在既有检查点记录死亡、移墓地、处理适用的亡语、残骸与复生。该失败路径不成功入手、不重置材料，也不实施成功回手后的改费。

原card_burned通知保留，player_id表示失败交付目的玩家；后续minion_died和死亡记录依原当前controller归属。目的玩家与当前controller不同时，不能先改控制者或墓地归属再计算死亡收益。死亡记录保存当前身材、伤害、附件、印刷费用、原场位与原因；沉默后的能力不会在死亡前重新安装。已经退役的目标再次回手按原stale规则跳过。

死亡结算、选择等待、事务回滚、快照、回放与玩家信息沿原解释器。没有新持久字段、账户、能力授予或组合模块。已有死亡延迟也沿原协调器处理，而非由回手处理器提前移除。全知死亡材料不暴露到玩家观察或事件接口。

规则身份更新为prototype-v281/core-effects-v275。数据形状没有变化，schema246及其旧1～245拒绝政策保持；旧规则/core身份由现有守卫拒绝。观察player-view-v82、命令12、外层replay1及默认306定义指纹保持。

必要隔离来源仅[固定EX1_581闷棍](../data/support/full-hand-return-death-basics.json)，2费、敌方随从目标、原ReturnToHand行为；未新增生产卡包。NEW1_004群体主体与WW_441/WW_044t原生溢出只留前审原文。B151已保存满手回手与普通Destroy的[直接反证](../outputs/burn-classification-audit-20261012/baseline-probes.json)。支持规则线索的2025 Ciletos和2019 Boom Bots记录是官方论坛上的社区第一人称描述，明确不是Blizzard规则声明或当前国服实测。

原[test_lifecycle_mechanics.py](../tests/test_lifecycle_mechanics.py)中错误“满手回手无死亡/亡语”测试已改名并更正为正常死亡与召唤亡语产物，旧源码与变更证明保留；没有撤除该检查。[19项专项](../tests/test_full_hand_return_death_basics.py)覆盖必要来源、真实付款、正常/失败对照、通知与死亡分离、当前死亡材料、沉默/复生/零残骸、重复和顺序容量、owner/controller分离、可配置容量、等待恢复、动作及选择回滚、stale和玩家信息。

实际执行见[本批验收](../outputs/full-hand-return-death-basics-20261012/verification.json)。准确事件窗口、目的容量特殊规则与国服最终一致性仍待M6；B150的原生存储溢出仍明确未支持并报错回滚，不能由本项满手BOARD死亡修复推定所有card_burned都触发亡语或本牌主体。M0正式池、M7批量接卡及完整基础目标仍未完成。
