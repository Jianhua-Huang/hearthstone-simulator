# M5-13d-02m-01-B2-05：结束回合重复来源匹配

本文件描述已接入、尚待内部验证的公共契约。当前运行版本为 `prototype-v110` / `core-effects-v110`、snapshot schema107；实际执行、验收与下一项只在 [项目状态](project-status.md) 与 [机制清单](mechanism-backlog.md) 登记。R-156未国服校准，不能据此宣称结束族、正式池或长期目标完成。

观察54、命令7、外层 replay1 与 `representative-m5-v64` 保持。305条代表原始记录、306定义、14个 choice-only 保持，本批不新增真实卡。既有 [结束主体](m5-end-turns.md)、[次数计划](m5-end-turn-repeats.md)、[主动入口](m5-end-turn-activations.md)、[候选和随机 producer](m5-end-turn-producers.md) 的自然时钟、主体资格、守卫、选择和执行窗口继续适用。

## 来源条件和主体范围

`EndTurnRepeatMatchSpec(source_eligibility=None)` 仅描述实际物理重复来源的持续条件。`EndTurnRepeatSpec(repetitions=2, scope='all', match=None)` 继续设置次数，`repetitions` 必须为严格整数且至少2；`scope` 只允许既有 `all`、`minion`。没有新的 `self`、接收对象种族、费用、主体重复、固定多轮 producer 或 `+1` 轴。

`RepeatSourceEligibility(profile_id, tribes_any=(), exclude_carrier=False)` 复用持续来源条件。查询以主体捕获所属玩家作为见证控制者；profile 显式决定在场政策、休眠、星舰、doomed及生命门槛。种族读取该见证当前物理卡面定义的印刷元数据。`exclude_carrier` 排除实际重复来源的实体ID，不能按名字、卡牌ID或附件授予者排除。profile 未注册、元数据不足或声明非法时明确报错。

重复来源自身仍须是主体捕获控制者控制的实际 board MINION，活跃、存活、未 doomed、生命大于零，附件可用且未消费。见证是否存在与重复来源本身是否有效分别判断；profile 不让手牌、墓地、武器、地标、技能或已死亡来源成为 live contributor。冻结死亡事实仅用于来源身份校验，不提供冻结的 live 来源或见证。

完整声明在主体不匹配或 stale 退出前验证。对于每个有效物理来源，先完整查询持续条件，再与 `all`／`minion` 的主体范围相交；不能见到首个见证就遗漏后面的未知元数据，也不能用范围为 false 略过非法 profile 或必要查询。空主体批次仍验证全量声明、全局ID、全部区位和冻结死亡来源，因没有接受主体而不虚构见证查询。

接收对象沿用完整 `EndTurnSubject`：物理来源、捕获控制者／实例所属玩家、卡面、入场顺序、区域修订，以及完整能力或玩家实例和声明索引。普通随从、休眠能力、武器、地标、在位被动技能和玩家效果主体继续沿各自公共政策接受。`minion` 只匹配能力支持的实际随从主体；`all` 匹配该捕获所属玩家的全部显式主体。玩家效果即使由随从授予，也不变成随从主体。

`PlayerEffectSpec.end_turn_repeats` 保留持久和有期限来源。模型、注册表、Frame与历史 contributor 均以 `allow_source=False` 验证其完整声明，拒绝 `source_eligibility`；玩家实例的 donor 只保存来源信息，没有可供此条件判断的物理 carrier。玩家来源本身不消耗额外用途，也不因匹配扩展获得新时钟。

## 原接受窗口和完整 max 计划

自然、effect、phase及随机一次 producer 保留原首次窗口。每次实际入口在原局面接受完整有序主体与每个主体的完整 `EndTurnRepeatPlan`，次数仍为 `max(1, 所有匹配来源的设值)`。全部较小或相等设值的 contributor 均保留，单位计划也明确保存；不能只保存胜出来源。

主体条件、source 条件与 producer 候选政策分别执行。结构性候选查询不执行主体条件、不查询本次重复来源见证、不增加候选权重；每个物理载体仍只有一个权重。随机一次 producer 在原处理器内查询完整有序候选、抽选一次并接受选中载体的全部合格主体和计划，不返回第二个入队效果来移动窗口。空池保持空根、无抽样；选到 false 主体仍保留真实选择和空接受。内层额外位置不重选、不重抽。

接受之后，见证消失、来源沉默／死亡／转控／变形／替换／消费／到期，均不重算已经接受的位置。新入口按其当时局面重新捕获。附件ID与实际实体绑定；合法转控后，新根使用新捕获控制者自己的来源，既有原根保持旧控制者和完整计划。紧凑历史不重查当前见证或来源当前区位。

来源键继续区分 `(carrier_id, ability.id)` 与 `(owner, instance.id, spec_index)`；同名卡、同行为ID、同 donor 或相同数值的其他ID空间不能合并。完整能力、完整玩家实例、规格、索引和 source card 身份均冻结。共享玩家实例可以在亡语、结束两族各有 `spec_index=0`，其完整族别与所属声明数组分别验证，不能跨族冒充。

## 原完成证明与比较目录

`FinishEndTurnBatch` 保存完整原 `RuleContext` 与完整 typed `EndTurnBatch`。其 context 故意早于本批安装：原批次列表长度为 `batch.id-1`，原历史长度为 `batch.first_id-1`。原证明在真实原 state 上重算 producer 完整候选、resolved request、主体全集、各主体完整来源计划和局部 RNG 关系；不得把本批诊断事实插入原 state 后再查询。

跨族引用比较需要本批 contributor 时，可以构造只供比较的目录：复制原 state，附上 typed `work.batch` 和由其完整跨度确定的 `EndTurnRecord`。这个目录只能用于接受引用全集和身份比较，不能输入主体资格、profile、见证、producer、RNG或接受查询；它不是另一个原窗口。

原 prefix 与 current 绑定完整已接受批次、完整 capture 身份、guard ID和已知 guard event、实际执行顺序、完成／跳过／中断进展及不可变死亡前缀；分配计数和接受时序不能倒退。当前本批完整 typed marker 与完整 capture span 须仍对应原 proof；原窗口、当前 marker、各 Invoke acceptance 与历史不能协调裁剪尾部次数来规避原全集。

完整 proof 保留到本批最后主体和旧反应完成。自然尾部普通监听等待时，即使全部分类主体已 completed，空批次或有主体批次仍须保留唯一 Finish。内层批次先于父批次、以及适用时先于父主体 Finish；只有主体父ID与只有批次父ID的合法窗口分别保留。未完成批次组成完整嵌套链，不能通过清空主体跨度或队列隐藏其完成义务。

## 全 false 身份、后接受窗口和来源时钟

原窗口和当前来源目录检查两方、全部实体区位及全部附件族，包括秘密、任务、休眠和玩家实例的全局重复ID。全部 `end_turn_repeat` 声明均核验完整规格和 profile；冻结 `DeathRecord` 中此类来源的卡面载体必须为 MINION，即使来源未匹配任何主体。相同ID须保持原族别、carrier和不可变完整值，合法消费只单向推进。

原 proof 将全部匹配与 false 来源身份绑定到当前存续来源、冻结死亡事实和后续完整已接受引用。旧来源最终从 live 附件中删除后，仍不能把其ID借给另一族或在后续收据中改写旧完整声明。原引用 prefix 保持；后续较旧ID的引用必须与原完整族别、carrier、owner、值、规格和索引相容。新分配ID可以合法新增。

共同窗口 collector 复用战吼、连击两窗、法术两窗、亡语整批、英雄技能 root／实际 payload batch及结束主体 Invoke／有限次／在位技能 guard／整批 Finish 的实际原窗口。不能仅按 action、根ID或 context 是否包含本批判断先后；普通早期 context 与完整 typed 接受 marker 必须区别。`FinishEndTurnBatch` 的 marker 在 `work.batch`，不是其 pre-install context；较早 HP root 与较晚 retained payload batch分别使用完整 root和完整 batch。

较早真实接受窗口可合法不包含本批；只有其完整 accepted marker已存在于本批原窗口并且完整相等时才作此分类。较晚窗口则须包含本批并独立绑定原 false 来源、完整 prefix和当前引用。透明 Invoke／Finish及所有实际 work 在 pop 后、分支处理前经过共同只读门禁，防止 foreign 原证明消失后仅留下ID引用。

玩家来源的完整实例身份与 owner 保持，剩余期限允许非增加，不允许在原窗口、后接受引用或当前存续实例之间反向增长。结束族 compact clock按 batch接受顺序验证；亡语族按其既有捕获顺序分别验证，不能将两个族的不同接受顺序拼成伪造的单一时钟。期限递减或最终实例移除不解除已接受引用的完整身份义务。没有新用途、消费事件、倒数边界或时钟。

## 原守卫、额外位置与生命周期

自然 mixed listener 槽位继续局部展开各主体的全部位置，保持普通监听交错。普通／休眠／玩家效果首次载荷保留原接受局面；有限次首次载荷保留旧实际消费后的局面，只通过一次原守卫、消费一次并保存真实 `limited_trigger_used` 收据；在位技能首次载荷保留原安装身份守卫，不执行手动技能支付或用途。

effect有限次及在位技能使用既有 `CheckActiveEndTurn`；自然有限次使用 `CheckLimitedTrigger.end_turn_context`，自然在位技能使用 `CheckHeroPowerTrigger.context.end_turn`。这些实际原 guard 窗口与独立 Invoke acceptance 都参与绑定。guard失效整组 skipped，已接受额外位置不重复消费或重查安装槽。

首次 HP Check 到首次 Invoke 没有合法 waiting 边界，稳定挂起恢复继续拒绝此伪造阶段；实际 closing和 terminal完整队列检查不能误把运行中的正常阶段当挂起。有限次消费会产生真实事件反应和选择，保持独立实际收据，不能套用 HP 的不可挂起门禁。

额外位置实际开始先记录执行事实，再取得最新局面，保持原主体、控制者、能力和计划。额外上下文可以合法缺少原附件或实例；排队 work不能伪装成已开始 fresh context。copy、变形、沉默、转控、到期、复生和其他生命周期继续由现有公共内核负责。

自然玩家期限只在既有规格选定的 owner边界倒数一次。原结束反应中新建或替换实例不加入该边界旧倒数集合；对手回合调用己方主体不推动己方期限。effect／phase、嵌套和额外结束载荷均不生成新的自然事件、owner clock、抽牌、资源刷新、休眠倒数或 RNG消耗。

## 关闭、终局、预算与私有 wire

实际 Finish handler 关闭前以 `closing=work` 把刚 pop 的完整 Finish 放回剩余队列头，仅用于同一完整跨度及嵌套关闭检查，再标记 completed。末次 Invoke 已消失、剩余队列为空或只有普通反应尾部时，不能遗漏本批 proof。terminal在任何族 interrupt及清空队列之前，对尚完整队列和所有原证明、false身份、guard收据、跨度、prefix及完成栈验证；随后只中断未完成位置，已完成或 skipped事实保持。terminal已由死亡检查点设置时，不能要求当前 state仍 playing，原接受 state则须 playing。

完整 max展开在分配位置 tuple 前受现有公共预算限制，Invoke／BehaviorCall／Finish／原 guard仍计入工程步骤。等待选择不重置步骤；错误按原事务回滚支付、事实、玩家时钟、随机和信息记录，不截断为单位计划或冒充游戏平局。新验证器不发游戏事件、不加玩法检查点、不消费用途、不修改RNG。

私有 state parser要求 EndTurnRepeatSpec 的 `repetitions`、`scope`、`match` 显式存在；match为null或仅含 `source_eligibility`，条件严格保存三个字段及JSON字符串数组。缺字段、未知字段、bool冒充整数、非法profile或跨族规格明确拒绝。FrameCodec复用精确typed字段及原接受验证，不能用constructor便利默认修复损坏wire。schema107明确拒绝旧schema1～106；旧origin恢复不由外层 replay1保证。

match、来源见证、完整 contributor、全知原 state、typed历史、比较目录、guard收据与RNG证明仅供可信宿主。玩家DTO及公开事件仍沿现有 allowlist；观察54／命令7／replay1保持，不增加玩家主动调用结束能力的命令。正常玩家结束回合与选择仍经 PlayerPort，双玩家视图保持隐藏信息隔离和深度脱离。

本契约提供恢复一致性、活跃原窗口绑定和结构关系验证，没有存档签名或来源认证。全部过去证据被协调重写的关闭历史不能据此认证为原真实对局。真实文字、完整raw、机制实现、内部执行和国服校准分别登记；条件对象、profile口径、合并政策、精确窗口及剩余未覆盖路线继续列入M5／M6。接收对象种族、physical self、`+1`、固定多轮 producer和完整正式池均不由本增量实现。

实施来源与原始 source hash gates见 [11文件拟议补丁清单](../outputs/v115-proposed-end-turn-patch-manifest.json)、[精确补丁](../outputs/v115-proposed-end-turn-matching.patch)；专项和原生的原始设计见 [92项专项草案](../outputs/v115-proposed-end-turn-tests.py.txt)、[原生v2草案](../outputs/v115-proposed-end-turn-native-v2.py.txt)。契约不把准备、AST检查或预期数量登记为行为通过；真实执行与下一项继续只维护于项目状态和机制清单。
