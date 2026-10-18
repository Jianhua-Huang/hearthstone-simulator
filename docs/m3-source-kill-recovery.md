# 原击杀来源与复活消费者

实际进度、验证证据及下一项仅在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。本页规定霜之哀伤与乌索克实际需要的有限能力，不认证正式标准卡池或国服全部规则。

`KillSourceReference`保存原实体、卡面、类型与区域epoch，可绑定原死亡记录。`killed_minion_deaths`纯读既有DeathCause/HealthResult：随从按原物理来源及epoch匹配，不按当前控制者或后来的入场顺序筛选；武器按致死战斗结果中的weapon_id/weapon_zone_epoch匹配。有效`weapon_transferred`记录连接同一武器的连续驻留，换装、重新出牌或新复制实体不能仅凭同名借用击杀。不会根据当前生命、普通伤害次数或当前装备猜击杀，不另建击杀账本。

自然亡语使用原死亡的来源epoch；历史触发通过原选择根找到原死亡，显式继承则跟随原能力的继承身份，保留该主体的原来源参数。它们没有伪造自然死亡上下文。当前复制视作新的物理击杀来源；同一实例转控保留此前击杀，回手/重置/变形后的新epoch不借旧记录。这些具体来源政策仍待M6核对。

`ResurrectKilledMinions`要求实际运行中的亡语和普通SummonCause，按原死亡顺序冻结确切死亡ID，随后交给既有`Resurrect`和原完整材料/数量/容量/通知/继续流程。可以复活原双方受害者，交付给本次亡语玩家。旧附魔不替代普通印刷复活材料；未知内容继续报错。来源死亡、满场、选择恢复、异常回滚与回放沿用公共管线。

`AttackAllOtherMinions`保存原攻击者BoardPresenceReference及已尝试的物理驻留。每步从当前双方存活、活跃、未尝试的其他随从中随机选取一个，走普通`ForceAttack(..., combat_relation='any_minions')`，再继续；新入场随从可加入，已尝试驻留不重复。原攻击者离场、死亡或不活跃则停止。强制攻击不消耗手动攻击机会；反击、死亡、复生、目标改道与等待使用原执行器。随机顺序、新入场参与、尝试消费及复活位置仍是待国服校准的本地政策。

公共效果core485，新增两个Effect及一个不可变payload。schema401、观察94、命令12、replay1保持；没有Entity、PlayerState、GameState或CardDefinition新字段。新增诊断击杀选择不进入玩家投影。完整正式生成/可达范围、M0/M6和阶段发布验收仍开放。

[官方32.0.2热修](https://eu.forums.blizzard.com/en/hearthstone/t/3202-hotfix-patch/11694)明确修复乌索克配合活体梦魇的2/2副本。本适配复用原创建和复制流程，不另写该卡专用复制；这条证据不能认证攻击顺序、击杀连续性或当前国服所有时序。
