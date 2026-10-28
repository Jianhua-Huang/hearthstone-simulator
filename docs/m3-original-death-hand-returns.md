# 原死亡实体回手与奥秘手牌空间检查

## 实际来源

本批接入CFM_800战术撤离与LOOT_204诈死，服务标准宿主实际可达的完整过去奥秘域。[资料包](../data/cards/death-hand-returns-v1.json)保留两主卡、一张只读减费附魔LOOT_204e的三个完整原行及四份完整中英文主面。附魔只作效果证据，不注册空白可执行牌。完整72候选及原179/84参考名单、顺序、角色、权重和来源版本保持；完整来源与WON_040仍未开放。

两卡共用ReturnDeadMinion。它绑定原DeathRecord的id、原墓地实体和施加来源的完整SourceAllocationFact；不按名称找另一张卡，不新建随从或重放战吼。诈死额外安装普通本地费用delta=-2，使用原费用下限与后续支付。

## 原死亡与物理驻留

原minion_died通知的source、controller、batch、position必须与原死亡记录一致。DeathRecord.copy_source.origin证明原BOARD驻留；可返回对象必须仍处于其第一次GRAVEYARD驻留，具有相同entity_id/card_id/owner/controller/entered_order及原zone_epoch+1。缺少完整死亡事实显式失败；已经离场、重新入场、再次死亡或已溢出失效的旧材料不能命中新驻留。

实际接收者是死亡时控制者，物理owner保留。实际移动只使用原Resolution.move；回手重置使用reset_to_definition及与普通回手相同的Jade/C'Thun保留政策。原进手记录先建立，普通减费在返回/进手监听前完成，再刷新光环和发布原hand_history通知。原战吼不会因此执行，后续打出仍是同一张物理卡的正常付款和出牌。

原死亡记录、残骸收益和已捕获的亡语/复生继续保留。回手不撤销过去死亡，也不重复计一次死亡或残骸。后续复活仍可使用原死亡历史，这与移动原墓地实体是两个操作。未加入无依据的通用亡语抑制或复制整套结算器。

## 手牌空间与溢出

SecretHandSpace是瞬时的只读条件结果：卡牌函数只报告匹配，奥秘内核按当前Ruleset和玩家hand_cap检查实际空间。旧布尔条件、目标规则、SecretSpec字段与旧完整卡牌定义保持；非法条件返回值仍回滚动作。该结果不进入帧，不注册为payload，也不能作为解释器工作排队。

战术撤离和诈死在接受时满手则保留。揭示反应或待选可能随后填满手牌，此时已接受的ReturnDeadMinion复用graveyard_delivery_overflow烧牌通知，并使原墓地驻留失效；不再制造一次随从死亡。相同材料重试不能在后来有空位时重新领取，也不改成生成一张同名卡。

这项检查也用于现有BT_709邪恶计谋和GIL_903隐秘的智慧。[直接实测讨论](https://www.reddit.com/r/hearthstone/comments/gcvdpz)与[另一条本人对局报告](https://www.reddit.com/r/hearthstone/comments/htwy37)支持两种抽牌奥秘在满手时保留，并有评论报告死亡回手同样受空间限制。八/九张手牌时仍按原抽牌与溢出处理；空牌库和疲劳规则没有因此改动。折价篓的满手政策没有独立证据，本批保留其旧本地政策并继续登记待核定。

## 恢复与协议

ReturnDeadMinion是唯一新增Effect，使用既有SourceAllocationFact而不新增payload或状态历史字段。FrameCodec保存、读取排队材料时，校验原死亡身份、完整实体/来源分配、控制者、墓地epoch和分配上限；当前已合法离场的材料执行为原目标失效，不能从未来或另一死亡借用材料。它不提供对未签名存档的来源认证。

核心更新core-effects-v795，快照618并拒绝旧1～617；729个Effect、281个payload，内容constructed-cn37-preview-v699。原观察、命令与回放布局保持。待选、clone、回放、真正回溯重试、异常RNG回滚、实际减费付款和双方玩家信息边界均由本批专项核验；[实际结果](../outputs/card-integration-20261014/k637-death-hand-returns/verification-01.json)分别登记专项、直接相关范围和保全证据。

## 本地政策与后续

本地旧Fireplace对战术撤离使用Bounce；旧SabberStone使用CopyTask，其战术撤离测试只核对卡牌身份，而诈死测试明确核对原实体id。它们不能证明当前国服实现。本地选择原物理实体回手，首个实际移动原墓地驻留的后果取得该卡；后来奥秘保留。精确揭示/控制变化、死亡后果相对时序及复合随从特殊保留规则仍属本地待校准边界，不冒称官方一致，也不为此裁减完整候选池。

下一继续EX1_136救赎与TSC_929紧急机动。救赎必须保留印刷最大生命并以1剩余生命入场，不能用设最大生命1代替；紧急机动需核原死亡当前材料与休眠入场，按真实缺口补最小公共能力。
