# 原抽牌、死亡与已施放法术的续接

完整六张原始卡面与配方见`data/cards/original-material-spells-v1.json`，整体PIN为`7dd248ded52126d35d8547b790cadc6cc960d047064d556af829d28cf7b33b05`。本契约说明已实现语义及明确边界；实际进度、验收和下一项只在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护。内部测试不等于国服精确校准。

| 卡牌 | 原材料与窗口 |
| --- | --- |
| FIR_941 烧灼映像 | 沿原分组匹配抽牌的成功HAND回调，保存实际抽到的原手牌引用；CopyStoredMinion在首次入场前固定8/8并安装圣盾，原牌留手，复制不执行战吼，数量与容量由原归因召唤负责。 |
| CATA_978 辛达苟萨的胜利 | 原目标随从8点SPELL伤害；原HealthResult中`max(0,damage_dealt-max(0,health_before))`冻结超量值，原InvokeHealthResult在新局面抽一个实际手牌受益，ModifyStoredCost减费并沿原下限处理。护盾、无超量或空手不产生减费。 |
| JAIL_225 劫持 | 3点SPELL伤害后按原健康结果的直接damage/poison死亡归因定位原DeathRecord。CopyCard接不可变原死亡行，创建属于本方、费用设为2的印刷基础牌库复制，origin_entity_id指向原尸体，不把复生体或之后的墓地卡面当作来源。 |
| END_025 永时火焰箭 | 原生吸血SPELL3；原击杀成立后用已有PlayerEffect.source_allocation保存当时真实GRAVEYARD法术分配事实。原玩家效果监听真正本方turn_ended，先移除自身，再ReturnSpentSpell归还原物理实体；不新建同名卡，也不追随旧法术离墓后的新驻留。 |
| FIR_910 灼烧之风 | 3点SPELL伤害的原结果窗口捕获原角色引用，DiscardMatching在实际执行时查询当前手牌火焰法术。只有实际成功弃牌才在其原反应/主体之后以原ApplySpellTarget再造成3点；旧随从引用失效不重绑复生体，候选为空不产生第二段。 |
| TIME_702 潮起潮落 | 原HandProgressSpec在card_committed监听本方MINION原PlayRecord，卡必须已在手。完成只记原独立进度；本牌主体冻结成立与否后3点SPELL伤害及5甲。直接召唤、法术和随从战吼期间才获得本牌不追认之前承诺。 |

## 复制体的入场前授予

CopyStoredMinion新增可空`minion_grant`，复用已有CreatedMinionGrant；本批实际只授予Divine Shield。有授予时必须提供原SummonCause。CopyEntryMaterial保存原授予声明与grant_source_id，验证其来自原归因请求中的真实来源，不能借其他实体冒充授予者。

当前/基础复制和固定SummonStats安装后，复用card_creation.install在首个入场/召唤事件前安装授予，再刷新光环。不能在on_summon或复制后另GrantKeyword代替；首次观察、数量生成的每份实体及保存材料均须已含正确圣盾。未声明时保持旧路径，不为无来源复制添加任意授予。

CopyCard新增DeathRecord操作数，只允许原BOARD随从的`mode='base'`。原死亡行必须与当前死亡历史对应ID逐字段一致，源卡面仍须已注册；不把不可信历史结构或当前墓地实体伪装成原尸体。物理创建、洗牌位置/RNG、费用附魔、原实体血缘和事件发布复用原copy_physical_card。这里没有实现“任意死亡材料的当前状态复制”。

## 成功弃牌续接

DiscardCard和DiscardMatching新增默认空的`on_success: tuple[Effect,...]`。只有原HAND引用真正移到GRAVEYARD并提交card_discarded后才返回这些效果，原被弃主体、存储亡语与事件反应先由既有解释器处理；失效引用或空匹配不执行成功续接。多个实际弃牌各消费自己的成功续接，没有额外弃牌/死亡账本。

灼烧之风使用原健康结果捕获时的角色引用。随从保存原MinionReference，英雄使用原英雄ID，第二段交已有ApplySpellTarget进行真实驻留/存活检查。首段致死后本地政策仍可实际弃掉一张火焰法术，但不能将第二段迁移到新复生体；两段各自按执行时法伤结算。

## 原已施放法术归还

ReturnSpentSpell只接受原施法者墓地中可手动使用SPELL的SourceAllocationFact。执行时先校验原分配、注册卡面及非未来边界，再比较原卡面、类型、owner/controller、区域、epoch与entered_order。已离墓、再获取或再施放的旧驻留按失效跳过；错误身份与未来事实报错。

本地归还政策先reset_to_definition，清旧本地费用、临时租约及进度，再用原Resolution.move进入原施法者手牌，创建新的真实获取记录。实体ID和owner保持，不伪造抽牌、弃牌或死亡。满手时沿已有graveyard_delivery_overflow事实和card_burned处理，并使旧驻留终结，不能在以后空位时补交。

延迟由已有持久玩家效果的一次本方结束触发实现，触发后移除。不是占用秘密/限量持续区的目标或符印，不把多次待归还卡挤出。已有AddPlayerEffect的捕获开关保存的是通用source_allocation，本批仅将其作为原法术引用，不伪造健康事件或伤害来源。其他玩家结束不消费；本方结束事件捕获后才添加的效果按原事件接受政策等待后续本方结束。

## 保存与待校准项

CopyStoredMinion、CopyEntryMaterial和弃牌请求新增保存字段，使用core344/schema275；旧1～274明确拒绝，观察85/命令12/replay1保持。没有新Entity/Player/GameState字段或新历史账本。待选、回滚、clone、回放和玩家信息隔离沿原解释器；引用、授予者、分配及完整死亡材料不进入玩家DTO/事件。

当前明确边界仍需国服证据：烧灼映像只使用成功HAND续接，烧牌或奖励前离手目前不召唤；劫持采用印刷base复制而非继承旧附魔；永时火焰箭归还时重置旧本地费用/临时状态；超量、重定向、原角色第二段、承诺期持有及本方结束的精确窗口均是本地政策。这些不能因本批内部归档宣称整卡边界或官方支持已完成。

`python -B -X utf8 -m examples.card_original_materials`使用真实六张卡和已注册依赖，经玩家DTO动作验证。短牌库、高法力和跨职业实验不认证正式套牌；M0正式补丁/热修/合法池、全部实际可达内容、M6与阶段验收继续独立推进。
