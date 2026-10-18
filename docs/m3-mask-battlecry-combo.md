# 面具生成与原战吼产出的连击减费

DINO_427装扮商贩沿用普通战吼和独立连击。双语官方主面的五个childIds一致，精确对应DINO_402、DINO_403、DINO_428、DINO_429、DINO_432；完整原行及官方主面保存在[data/cards/mask-battlecry-combo-v1.json](../data/cards/mask-battlecry-combo-v1.json)。面具域是具名内容清单，不按名称、已实现子集或开放标准生成池推断。

实际战吼用原PoolQuery/matches_metadata按执行玩家当前职业排除本职业及中立牌，再交给既有GenerateFromCandidates统一抽选一张。完整合格清单须可执行，未知合格内容报错；不因缺实现裁池。该有限来源不需要另建格式池，也不改变五张已有面具定义。

公共GenerateBattlecryCard只绑定一张普通法术或武器产出，可包装GenerateFromPool或具名GenerateFromCandidates。前者要求单张、放回、可收藏、单一牌型、普通手牌交付且无额外创建授予；后者要求整个有限清单具有同一个允许牌型。原GenerateBattlecryWeapon仍仅接受武器池请求，不能经新入口静默改变它的契约。

两种请求共用原输出绑定、普通随机与create_hand_card；实际新实体在排队反应执行前被记录。为保留既有格式，唯一账本、记录和私有事件仍使用battlecry_weapon_outputs、BattlecryWeaponOutput、battlecry_weapon_bound历史名称；BattlecryCardOutput只是同一记录类的别名，没有平行账本。SourceAllocationFact保留实际SPELL/WEAPON类型，消费端combo_card必须声明匹配类型，错误类型直接拒绝。

连击只从同一原物理出牌/自动主体及结果遍数的战吼取得原HAND CardReference，然后交原BuffStoredCard(CostSpec(delta=-2))。不搜索当前手牌或同名牌。满手烧掉、离手重入、转交或变形不改绑；正常存储费用层持续生效。重复战吼后使用最后一次匹配输出，重复连击各减2，沿用原费用下限。来源死亡不撤销已接受的独立连击。

原BuffStoredCard仅为此扩展法术的纯费用请求：必须带CostSpec，attack/health均为0，且使用物理CardReference。费用目标验证、附件分配、刷新和通知仍走原实现；不给法术开放攻击/生命增益，也不开放被弃材料的法术增益。

输出验证、原事件完整性、连击等待上下文前缀、异常回滚、独立恢复、回放和玩家隔离复用[武器产出契约](m3-generated-weapon-combo.md)。历史名称不进入玩家DTO；全知账本不是可发给玩家的信息，也不是未签名外部存档的来源认证。

引入core499/内容preview-v317；没有新增模型或保存字段，schema411、观察95/命令12/replay1保持，原引擎身份校验区分新效果集合。精确当前职业、重复战吼产出选择、连续驻留和微观时序仍待M6国服校准。固定面具域的内部验证不关闭M0正式补丁/热修/合法池、完整可达或发布验收；实际测试与下一项只见原两份台账。
