# 烈火炙烤的原牌回手和伤害余量

CATA_585 的完整源以 TAG_SCRIPT_DATA_NUM_1=8 保存初始伤害，双语主面省略动态@；数据包仅作显示归一化，不省略实际规则或改为零伤害。原 TargetPredicateSpec(damaged=True) 限定双方受伤随从，普通法术目标、反制、付款和真实施法入口共用。

ReturningDamageProfile 声明已知印刷默认8。未带额外参数的新生成/基础复制/普通重置牌采用该值；不影响其他必须携带来源参数的原生法术。SpellRemainderDamageValue 只保存原 card_id、实际 cast_id、damage_id 和正余量，沿既有 spell_base_value 附件及 SpellCastRecord.native_spell_value 冻结。没有新增全局余量账本。

DamageReturningSpell 绑定实际活跃施法和原 MinionReference，直接调用共享 settle_health_batch。结算前记下 next_damage_id，结算后读取这一实际提交的 DamageRecord，不扫描事件或以最后一条历史猜结果。只有实际法术伤害造成的正生命损失超过正的原随从生命时，才产生余量；预防、转换、无效目标等不伪造回手。法伤、原物理法术的本地加成、健康规则和死亡检查由原管线负责。

返回请求保存伤害前原墓地 SourceAllocationFact，并复用 ReturnSpentSpell。真正交付时仍要求同一原卡、区域版本和控制者；另一反应已先取走原牌时，旧请求过期。普通重置清掉原费用与其他局部附件，再安装经过实际伤害/施法校验的正余量，随后才交付和通知；满手沿原烧牌流程处理同一物理对象，不额外生成副本。

余量是新的基础值，后续真实施法重新获得当时加成。关于法伤/倍率可跨余量累积，存在[玩家实战报告](https://www.reddit.com/r/hearthstone/comments/1u8mrp7/408968_damage_this_has_to_be_some_kind_of_record/)及[倍率案例](https://www.reddit.com/r/hearthstone/comments/1vrrean/torch_atlesh_the_greatstaff_infinity/)，它们不替代正式国服校准。当前复制保留参数，基础复制采用印刷默认；整卡历史重放读取原首次实际接受的冻结参数，不能拿后来同一张手牌的余量替代旧出牌。

schema422严格区分原亡语生成值与新余量值，拒旧421及以前；原 CardDefinition 字段未变。已知印刷默认允许普通新牌无额外附件，但存在的余量必须完整、为正，并匹配实际施法和伤害记录；这不认证未签名存档来源。玩家只通过既有 base_damage 看到允许公开的数值，不取得原施法/伤害/分配证明。

精确国服减伤/转移、反应先后、反制和重复/继承来源等边界仍待M6。当前内部验收、相关验证、剩余标准内容及M0正式池/发布状态仅在两份原台账维护。
