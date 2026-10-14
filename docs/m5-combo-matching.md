# 连击双窗口匹配与接受证明

本契约扩展[独立连击主体](m5-combo-activations.md)、[连击次数](m5-combo-repeats.md)和[持续来源条件](m5-repeat-source-conditions.md)。本契约定义公共接受与匹配接口，实际执行与证据只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。R-153 为本地候选规则，尚未国服校准。

## 两个物理接受对象

独立连击主体只覆盖真实付费手牌的随从、武器和英雄牌。法术连击的条件数值分支保留现有 on_play 与 Spell 接受证明，不新增 Combo 根收据；召唤、复制、星舰发射和英雄技能也不虚构付费出牌。

`ComboRecipient(carrier_id, card_id, kind)` 分别保存提交窗和实际接受窗的物理实体、该窗当前卡面与类型。它不等同于继承连击的声明卡面、能力授予者或玩家政策的 source_id。提交面与实际面分别作为各自窗口的匹配依据。

提交窗在原付款与 PlayRecord 安装之后、实体移动与 card_committed 反应之前。只有原提交声明非空，才匹配 play 玩家政策；冻结的连击条件为 false、后来反制、满场或磁力不撤销这次已接受的用途消费。无提交声明仍保存显式空收据。

实际窗保留原入口：普通随从在入场处理器中、已排队的入场反应执行前；巨型在附属物及原 body 守卫之后；武器和英雄牌在装备或替换之后。只有完整实际声明非空且原 PlayRecord.combo 为 true，才接受场上来源与 activation 玩家政策。回调最终返回空效果仍属于已接受的主体声明。

## 范围、种族和持续条件

`ComboRepeatSpec(repetitions=2, kinds=(MINION,), scope='friendly', match=None)` 保留 max 设值语义。self 严格只允许 `(MINION,)`，比较实际来源载体与实际接收载体的 ID；同卡名副本、声明来源卡和 source_id 不能代替自身。

`ComboRepeatMatchSpec` 包含独立可空的 recipient_metadata 和 source_eligibility。前者为 `ComboRecipientMetadataFilter(basis='accepted_window_face_printed', tribes_any=())`，使用该原窗口卡面的印刷种族 OR、多种族和 all 语义；空限制不要求种族元数据，武器/英雄的非空随从种族限制为 false。需要的随从元数据未知时明确拒绝。

场上来源条件复用 `RepeatSourceEligibility`、注册 presence profile 和完整纯见证查询。每个活跃、存活、未消费的友方场上来源先完整查询见证，再与接收类型、self 和种族相交；其他条件为 false 不隐藏必要元数据错误。another 排除来源的物理 carrier ID。查询不执行主体、不发事件、不消费用途、不推动 RNG。

玩家政策只允许 friendly 和接收种族，不允许物理 self 或持续场上来源条件。两个 trigger 分别按各自窗口对象匹配；已接受 play 政策进入最终计划后不按实际窗卡面重匹配、不再消费。场上来源、新 activation 政策和原 play 政策共同取 max，全部匹配来源均保留，低于或等于最大次数的有限政策也各消费一次。额外执行、继承主体数量和保留结果不增加用途消费。

## 明确空结果与完成义务

每个付费物理根保存提交收据引用，并在实际阶段保存 `ComboAcceptanceReceipt`。实际 status 为 activated、disabled、no_payload、countered、board_full、magnetized 或 colossal_canceled。disabled 保存实际声明但不保存计划；无主体和取消保存空主体、空政策收据与独立证明。实际接受前的终局中断可以没有实际收据，不能伪造一次 activation 消费。

`ComboPolicyReceipt` 保存连续捕获 ID、play_id、phase、turn/action、该窗 recipient、eligible、完整匹配政策与 consumption_applied。收据按真实捕获顺序追加，唯一 `(play_id, phase)`，同根提交先于实际接受。父根等待、较晚选择动作执行子付费根后再恢复父根时，不能按 play_id 重排这条收据链。

原私有 rule/proof state 只允许最后一条收据为尚未消费的 false，此前全部 true；消费时精确应用已接受用途并将该条改为 true，再发原消费事件。Game 的 waiting、稳定和终态边界要求全部 true。BC 用途事件的原上下文可以保存一致的这一中间状态，不因新增 Combo 收据改变既有 BC 先消费顺序。

两族 durable 接受收据先安装，再以同一个最新 PlayRecord 保存原 BC/Combo 证明。提交和实际 Combo 证明独立；无 BC 的根、空根和取消根也必须持有自己的证明。所有主体、批次及保留结果完成后，按 Combo 实际证明、BC 原证明、Combo 提交证明、唯一 FinishPlay 的顺序关闭。关闭工作透明，不发事件、不刷新光环、不增加死亡检查点。

随从的唯一 FinishPlay 由提交入口持有，待结算窗口要求 resolve 与提交证明位于完成之前。边界从全部活动物理 PlayRecord 枚举义务，不能仅从存在的队列完成标记推断根。巨型记录另存精确 play_id，避免同实体回手重打后通过 source/action 近似关联旧入场。

## 生命周期、恢复与历史

已接受计划、完整主体和接收描述保持不变；后续沉默、移除、变形、见证消失或转控不撤销接受。每次额外主体仍读取新执行局面，下一真实付费根重新捕获。普通回溯重试恢复原检查点后重建收据；保留多结果复用原两窗对象、计划和一次消费。

活动证明重演完整原窗，绑定全部原玩家政策及实际窗的原场上声明，包括 false、非最大、离场和已消费来源。共享全附件 ID 清单，禁止跨族/附魔/玩家效果冒充；用途按实际应用的收据链精确递减，不以任意更小剩余值代替证明。原收据前缀不可变，仅证明所属的最后 staged 标志允许 false 到 true。

完成后只保留紧凑事实，检查存储接收对象、静态范围/种族、政策用途和批次/保留关系，不用当前见证、presence、控制权或当前接收卡面重判过去。允许原来源合法消失；未签名存档不能认证协调改写或已移除来源的全部历史真实性。终局丢弃队列及修改中断记录之前验证仍待关闭的原证明，不补跑未执行主体。

## 接口与保留范围

接口版本为内核/规则107、私有 schema104，旧1～103明确拒绝；新字段不隐式补默认。玩家观察54只公开 Combo 政策 scope 及 detached recipient_metadata match，列表与 added/used/removed/expired 事件保持同形，不公开 source_eligibility、内部 ID、收据或原状态；命令7、外层 replay1、代表包64保持。

本批不新增真实卡。种族/self/持续条件用必要合成内容验证，TRL_092/GDB_873现有默认行为保持。当前不能通过 PLAY 区 Transform 演示提交前后不同卡面；该区别由纯匹配描述符表达，实际组合验证使用接受后变形、回手与下一根。任意动态 Combo 主体授予、同一外部动作连续付费嵌套、自动 CAST、Dark Gift 交付、固定多轮 producer、其他族/轴及 M0/M6/M7 继续保留。
