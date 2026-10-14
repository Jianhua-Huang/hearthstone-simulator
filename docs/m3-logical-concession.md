# 独立逻辑认输

宿主使用 `Concede(player_id)`；玩家通道提交 `{'revision': ..., 'action': {'type': 'concede'}}`，座位仍由宿主绑定。玩家 ID 必须为整数 1 或 2。命令只接受 type，不能指定输家、赢家、目标或另一个座位。观察修订值、错误投影及原事务管线保持。

任何已提交的 playing 边界允许双方各自认输，包括非主动方、换牌以及由任一玩家持有的待选。已结束比赛拒绝后续操作。宿主合法列表含双方动作，玩家只得到本人认输；普通出牌/结束回合等仍受当前行动权约束。若普通动作枚举遇到未知规则或数量预算，原错误继续明确返回；可直接用有效观察修订值提交认输，不依赖隐藏牌或候选枚举。

认输将比赛设为 finished，赢家为另一座位，只发布原有 game_ended 事件，reason=concede。它不造成伤害、不摧毁英雄、不产生死亡事实、不执行亡语、不制造回合或支付检查点、不选择分支，也不消费 RNG 或结算步骤预算。已经完成的动作前缀与付款保留。

待选时，原帧的 prefix 与 continuation 仍交给既有终局中断管线验证完整接受义务，之后按原语义关闭待出牌、反应、批次、资源及回溯等工作。未执行的流程记为 interrupted；不调用 on_select，也不伪装为 completed。认输不会取消此前真实伤害、死亡、揭示或支付。

英雄致命窗口可能在待选时仍有未结束的 episode。HeroLethalRoot 的两个可空字段 interrupted_action/interrupted_event 绑定本次真实终局事件。原 stack、原 parked hashes、episode 状态及历史继续保留；completed 保持 false，active coordinator 清空。这是中断收据，不是英雄恢复或自然致命窗口完成。字段必须成对、时钟严格有效，不能同时声称自然完成；终态校验还要求与实际认输事件、输赢和当前 action 一致。

保存与恢复、克隆及 replay 使用原管线。引入时schema220 要求新完整 root 字段，拒绝旧1～219；语义版本 prototype-v250/core-effects-v244，命令 player-actions-v12，观察 player-view-v76、replay1 布局保持。原玩家 DTO 不暴露帧、root、episode、付款证明、RNG 或中断收据。未签名存档的一致性校验不提供外部来源认证。

暴雪的[世界赛报道](https://hearthstone.blizzard.com/en-us/news/21472377)明确记录通过认输结束传统对局，证明该基础入口有真实需求；它不规定客户端在异步动画中的每个即时点击窗口。这里以已提交逻辑边界为输入政策，精确国服窗口仍需 M6 校准。没有新卡牌或跨机制组合；实际执行结果和下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)登记。

