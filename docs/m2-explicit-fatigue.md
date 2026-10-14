# 主动受到疲劳与共享计数

公共入口为 `TakeFatigue(player_id, source_id=None, on_fatigue=None)`。它表达一次真实疲劳递增，不依赖牌库为空。空牌库的 `Draw` 复用同一个 `fatigue.advance`；固定数值的 `Damage(..., kind=FATIGUE)` 只表示伤害类型，不递增账户。

玩家账户仍为原 `PlayerState.fatigue`，没有新账本、持久结果类型或计数缓存。效果实际执行时校验账户、物理来源和回调，计数加一，发布原 `fatigue` 事件，并把确定的数值交给原 `Damage` / `DamageBatch` / 生命结算管线。护甲、免疫或伤害上限影响伤害结算，不撤销已经发生的计数递增；双方账户独立，换回合或来源离场不清零。

主动入口不产生 `DrawRecord`，不移动牌库实体，不发布物理抽牌事实。自然空牌库抽取保留原抽取记录、事件 `draw_id` 和 `FinishDraw`，没有额外疲劳效果检查点。原致命终局可以中断未开始的后续递增、抽取和回调。

疲劳伤害继续没有卡牌来源，`DamageKind.FATIGUE` 的原来源限制不变。入口的 `source_id` 是导致效果及接收回调的物理实体，不会赋给伤害包；它不会让疲劳变成法术伤害或本牌造成的伤害。空牌库抽取的原伤害归属保持。

`on_fatigue` 是可选的已注册行为名，需要物理来源。回调取得原 `fatigue` 事件，`context.event.amount` 是本次确定的名义疲劳数值，`event.player_id` 是承担疲劳的玩家；`context.player_id` 沿原行为规则使用来源控制者。上下文在递增时捕获，回调在该伤害包及原检查点之后执行，不能把这份捕获状态当作伤害后的实时状态。名义数值不会从后来的可变疲劳账户或实际生命损失重新读取。

回调和未开始的 `TakeFatigue` 复用原 `BehaviorCall`、类型白名单帧、选择、事务回滚、保存、clone 和 replay。`on_fatigue` 进入原已注册行为字段校验，未知名字明确拒绝；玩家观察不取得回调状态或私有牌库。未签名快照仍不是外部来源认证，本文不增加完整疲劳历史真实性证明。

必要代表仅为隔离实验中的 `ETC_068` 次中音号小鬼：战吼执行一次 `TakeFatigue`，原事件数值交给普通 `Buff`。完整本地六条原始记录及 PIN 保存在 [疲劳原始证据](../data/support/explicit-fatigue-basics.json)，其余五条只作缺口依据，不增加适配或生产卡池。生产代表包仍为 64，不能据此声称完整疲劳卡族或正式池已经接入。

规则依据为[官方卡页](https://hearthstone.blizzard.com/en-us/cards/90439/)、[官方疲劳介绍](https://hearthstone.blizzard.com/en-us/news/22819074/endgame-moves-finessing-fatigue)和[奥妮克希亚迷你系列介绍](https://hearthstone.blizzard.com/en-us/news/23763644/non-printable)。这些资料证明递增疲劳和主动/抽到时疲劳需求。防护后仍取名义数值、回调窗口及来源归属为当前内部执行政策；没有精确国服实测，仍需 M6 校准。其他来源卡、计数修改、特殊负面抽取主体及完整合法池不由本文宣称完成。

新引擎为 `prototype-v251` / `core-effects-v245`，schema 221 拒绝旧 1～220；观察 76、玩家命令 12、replay 1 保持。实际执行、验证结果及下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。
