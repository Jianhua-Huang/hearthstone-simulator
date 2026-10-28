# 原攻击的奥秘重定向

误导（EX1_533）和叛变（LOOT_210）的完整原行及中英官网主面保存在[固定数据](../data/cards/attack-redirect-secrets-v1.json)。这是过去奥秘72候选域的真实效果依赖；域和生产者资格仍单独审计，不据两张适配推断完整池已开放。

`RandomRedirectAttack(window, source, profile)`只接受原对手攻击窗口和已经揭示的完整奥秘来源，有限profile为`other_character`与`attacker_neighbor`。原攻击声明事件、窗口、源驻留、forced标志、机会消费和过量伤害政策保留；不以一次新ForceAttack假冒原攻击，也不重复消费英雄攻击或武器耐久。

误导按玩家、英雄、物理战场顺序保留每个其他存活角色一个权重，排除攻击者和当前受保护英雄。叛变只检查攻击随从的即时左右物理槽；休眠和地标占位不连通远处随从。活动性、将死和原驻留由公共管线核对。普通嘲讽、潜行和手动目标选择限制不再重跑；伤害保护和反击仍由原战斗批次执行。免疫候选资格目前是明确未校准的本地政策，不能当作国服认证。

无候选时未揭示的奥秘保留，RNG不推进；揭示后候选消失则已揭示来源消费而不改向、不抽样。单候选直接选定；多候选沿原RNG均匀选一次。揭示或内部请求等待后重新核对当前窗口和实际候选，不重绑离场攻击者；选中后的等待保留原结果和目标驻留。转控不改写历史候选阵营，原目标离场则取消原攻击，不另选目标。

`RedirectCharacter`保存完整分配、可选在场引用、生命、活动和将死事实；`AttackRedirectSelection`保存两张完整有序物理战场、两名英雄、完整候选/选中ID及MT19937前后状态、动作/事件时钟。`CharacterAttackRecord.secret_redirects`是一个不可变元组，不在永久历史中嵌套GameState。原`attack_redirected`诊断事件保存私有完整收据，接受窗、原揭示来源、候选重算、随机局部重演、顺序与最终交付均交叉核对。它提供内部一致性，不为未签名存档认证外部来源。

新`any_characters`只用于具有原奥秘接受证明的交付。普通玩家攻击仍须先合法地指向敌人，裸CombatDamage和新ForceAttack不能借此创建一次己方攻击。己方英雄在自己的回合被误导随从击中时，可用当前武器攻击力反击，但不会作为防守方磨损武器；主动英雄被改向己方随从仍沿原英雄声明和一次武器磨损。原普通`opponent`、`friendly_minions`、`any_minions`契约保持。

已接受的耐普图隆替身攻击计划继续保留其接受时成员、目标和强制子攻击；后续父窗口改向不重写整个旧计划。真实来源的恢复/回放检查沿既有替身执行器进行，不穷举新组合。[2022年玩家实测报告](https://www.reddit.com/r/hearthstone/comments/xfbdd1/secret_rogue_wild_one_bug_one_qol_suggestion/)仅作为历史边界材料；后续评论的解释是推测。未确认的更早接受顺序仍保留，不声称完整官方交互。

[2019年本人报告](https://us.forums.blizzard.com/en/hearthstone/t/misdirection-sending-a-minion-into-a-hero-with-a-weapon-damages-the-minion/13089)和[2020年米莎报告](https://us.forums.blizzard.com/en/hearthstone/t/misha-took-damage-from-my-weapon-on-misdirection/26536)支持主动回合英雄被击中的武器反伤需求。这些是历史玩家证据。精确当前国服免疫资格、占位邻接、奥秘排队/执行优先级与单候选RNG政策继续作为待校准差异；按用户安排不等待实测、不裁掉候选。

保存结构增加上述历史元组与两个显式payload，引入core798/schema621，旧1～620需对应旧引擎。候选名单、原两种窗口字段、支付/死亡/区域账户与玩家信息边界不新建平行路径。完整接受材料、候选和随机状态不进入玩家DTO。实际验证结果和下一项仅维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。
