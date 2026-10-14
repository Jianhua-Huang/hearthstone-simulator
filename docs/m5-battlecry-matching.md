# 战吼原接受对象与条件匹配

本契约扩展已有战吼重复公共能力，依赖[战吼重复](m5-battlecry-repeats.md)、[玩家次数政策](m5-battlecry-modifiers.md)及[持续来源条件](m5-repeat-source-conditions.md)。实际执行、验证结果与下一项仅维护在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。本契约是 R-152 本地政策，尚未国服校准；种族匹配使用合成场景验证，不宣称已找到或适配全部构筑种族次数来源。

## 原接受对象

`BattlecryRecipient(carrier_id, card_id, kind)` 保存该次物理手牌出牌到达战吼接受窗时的实体 ID、当时当前卡面和类型。`BattlecryAcceptanceReceipt(player_id, payloads, plan, recipient)` 无论主体集合非空还是为空，都必须携带它。接受对象不是 `PlayRecord.card_id` 的提交面、继承战吼的声明卡或附件的授予者。

普通随从在入场处理器内接受，发生于已排队的 `minion_summoned` 反应实际执行之前；不能将“已入场”写成“所有召唤监听已完成”。巨型继续使用附肢及入场反应后的较晚窗口与既有物理 body 守卫、实际玩家政策；取消的延后窗口记录明确空主体及物理接收对象。武器/英雄在装备或替换后的原窗口接受。窗口不因新增条件而统一。

完整非空主体集合、接收对象与 max 次数计划先接受，然后消费有限玩家政策，最后开始一般 on_play、战吼及连击主体。原完整证明贯穿整次出牌，在 `FinishPlay` 之前关闭。空主体不查询战吼来源、不消费战吼用途；非空主体但全部来源不匹配，仍建立次数为一的完整证明。

## 声明与纯匹配

`BattlecryRepeatSpec(repetitions=2, kinds=(MINION, WEAPON, HERO), scope='friendly', match=None)` 保留原 max 设值语义。`scope` 只支持 `friendly` 与 `self`，后者严格要求 `kinds==(MINION,)`，匹配实际附件载体 ID 与接收载体 ID。相同卡名的另一实体、`source_id` 授予者或战吼声明卡均不能代替自身。

`BattlecryRepeatMatchSpec` 包含两个独立可空操作数：

- `recipient_metadata=BattlecryRecipientMetadataFilter(basis='accepted_carrier_face_printed', tribes_any=())`：空种族不要求种族元数据；非空种族对随从使用公共 `PoolQuery(tribes_any=...)` 的 OR、多种族与 `all` 语义。武器/英雄不具有默认随从种族含义，返回不匹配。需要的随从元数据未知时明确拒绝。
- `source_eligibility=RepeatSourceEligibility(profile_id, tribes_any=(), exclude_carrier=False)`：复用原完整见证查询和注册 presence profile。`another` 排除实际来源载体 ID；接收随从可以是另一个见证，同卡名的另一物理实体仍成立。

每个原活跃场上来源先校验完整声明/profile，完整查询所需见证，再与 kind、scope 和接收种族相交。另一操作数为 false 不允许隐藏必要见证元数据错误。查询不执行卡牌主体、不发事件、不消费用途、不推动 RNG。

玩家战吼政策可声明接收种族，拒绝 `self` 及持续场上来源条件。玩家政策的 `source_id` 仅记录出处，不能要求该出处继续作为场上载体。所有匹配来源都进入计划，包括低于或等于最大次数的来源；每个匹配有限玩家政策每次真实根消费一次，与额外执行和保留结果数量无关。不匹配政策保留用途。

## 生命周期、恢复与紧凑历史

已接受的计划、主体和接收卡面不因随后的见证消失、沉默、变形、转控、区域迁移或选择而撤销。额外主体仍读取新的执行局面；下一次真实出牌和普通回溯重试重新捕获，保留多结果沿用同一原根计划。没有增加法术式死亡延迟、额外支付、出牌或自然回合时钟。

恢复重演原完整窗口，并双向绑定所有原战吼附件和玩家政策的静态声明及物理身份，包括不匹配、非活跃、非场上和已消费来源。扫描其他附件族和附魔，拒绝同 ID 更换载体/族/声明、撤销消费、把存续原来源从证明中删去。合法后续分配、删除、消费、区域变化及载体转控允许。

关闭后仅保留紧凑收据；历史验证可以使用原接收描述检查存续来源的静态 kind/self/种族，不能重新查询当前见证、控制权、presence 或现在接收卡面。原已移除来源无需仍存在。未签名存档不能认证协调重写或已移除来源的全部历史真实性，此契约不作来源认证承诺。

## wire 与玩家边界

内核/规则 v106、私有快照 schema103，明确拒绝旧 schema1～102；缺少新字段不能隐式补默认。私有 match 必需完整两个字段 `recipient_metadata`、`source_eligibility`，收据必需严格类型化 recipient。原注册表验证、所有区域/死亡记录、原上下文及不可变帧都校验声明/profile。

玩家观察 v53 的战吼政策增加 `scope`、`match`；公开 match 仅含 detached `recipient_metadata`，不包含持续来源条件、物理 ID、见证 ID 或完整接受证明。原法术公开 match 内部形状保持，玩家动作 v7 与外层 replay schema1 保持。全知状态、快照、诊断事件不能传给玩家。

本批嵌套真实付费出牌的组合验证使用选择续接后的独立外部动作。直接在同一外部动作内再次执行 `PlayFromHand` 会触发现有出牌历史严格递增 action 校验；这一来源/历史能力仍待独立设计，不据此宣称任意嵌套出牌已覆盖。

本批没有真实 Dark Gift 可执行适配。EDR_100t7 的 this/selected 只作物理范围需求证据；手牌/牌库交付仍待公共机制。战棋 Dragon's Eye 的额外一次属于战棋与 +1 轴，不能冒充构筑 max2 代表。连击、亡语、英雄技能、结束主体匹配及费用/主体/周期/+1/CAST 等轴继续按主清单推进；M0/M6/M7 仍未完成。
