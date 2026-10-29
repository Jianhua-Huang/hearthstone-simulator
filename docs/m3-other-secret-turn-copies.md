# 异职业奥秘与结束回合的真实出牌复制

[完整原行与四份官网主面](../data/cards/perjury-plagiarize-v1.json)接入伪证MAW_018与抄袭SCH_706。它们是固定过去奥秘参考域的跨系列依赖，不增加标准组牌根。原72项参考名单及角色保留，未完成的整个来源继续关闭，不能按已实现程度裁池。

## 伪证

使用本人真实turn_started及原奥秘生命周期，在原来源揭示后创建一次DiscoverFromPool。destination=cast只新增另一职业奥秘的单次声明；原当前职业的一次/两次、三选一、after_each、允许重复以及所有非适用参数拒绝保持。查询冻结接受时的当前英雄职业，双职业卡只要含当前职业就不属于other；这继承原完整查询政策，不按伪证的印刷潜行者职业替换。

完整绑定的constructed.cards决定身份、角色和权重，未绑定或合格未知内容明确报错。已有同名奥秘、容量、法力和手牌空间不裁候选；选定后沿原普通免费CAST、部署、发现完成证明及通知处理，不先入手、不另付款。空完整域不造菜单也不消耗RNG。恢复、原受益实体、游侠斥候等既有消费者仍沿[原发现施放契约](m3-discovered-secret-casts.md)。

## 抄袭

原对手turn_ended查询同一结束回合的played_cards，按提交顺序复制全部真实物理手牌出牌，重复使用同一物理卡也分别保留。反制仍是使用；自动CAST、额外召唤、英雄技能、交易与锻造不是新的手牌使用。不会取整局旧回合或另一个玩家的牌，也不把召唤/施法事件重建成出牌。

复制原提交的基础身份和印刷材料，不继承局部减费、增益或后来变形、区域、控制者变化。随从继续使用原PlayedMinionCopyMaterial，保留固有合成成分、青玉、永久基础属性和灌注数据；不另造随从复制器。

非随从直接把既有FrozenPlayedFaceFact交给CopyCard，不新增Effect、payload、历史列表或伪造SourceAllocationFact。仅允许有来源的base入手追加，无其他费用、属性、期限和牌库策略。执行和恢复都核原play_id及完整原face与实际PlayRecord相等，校验原注册卡面及物理来源仍存在；用不变owner和原提交controller建立普通copy_origin。逻辑Entity只是共享写入器的印刷输入，不声称它仍在原手牌区或具有新的分配事实。

真实雕刻武器的固有法术与基础费用从原手牌报价的完整abilities/base_cost读取，再沿原inherit_weapon_material继承；不读取后来武器的磨损/减费或当前形态。普通基础复制、独立新物理ID、复制信用、入手通知和满手烧毁由原CopyCard执行。原历史没有被签名，不提供未签名存档的来源真实性认证。

## 已取得依据和本地边界

两语言官网主面确认原始文字；[2020年玩家实测讨论](https://us.forums.blizzard.com/en/hearthstone/t/why-doesnt-plagiarize-also-keep-mana-reduction-costs-like-mind-vision-does/40238)报告抄袭不保留原局部减费和成长法术数值，[另一玩家观察](https://us.forums.blizzard.com/en/hearthstone/t/plagiarise-secret-why-does-it-not-trigger-if-i-play-nothing/42889)报告仅用技能而未出牌时奥秘保留。这些是历史玩家报告，不能认证当前国服全部边缘。

抄袭空相关记录不揭示；满手沿已有SecretHandSpace，揭示后的容量变化仍按每张实际交付处理。满手精确国服行为、揭示反应的历史切片窗口、强制提前结束及少见固有材料的线上继承规则保留本地待校准。伪证的当前职业/双职业、空池和部署失败沿既有公开机制的本地政策。按用户授权，版本对齐和规则实测暂缓，不阻塞这些明确入口。

core802/schema625、内容706；旧快照明确拒绝，玩家观察/命令/replay协议保持。实际执行范围、失败修正、保全、验收和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)登记；专项成功不代表完整过去来源已开放或官方国服校准。
