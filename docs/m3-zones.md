# M3 手牌、牌库与区域内选择

真实条件消费者继续使用既有属性、攻击、施法和物理库存事实；跨冻结反应的原邻位组仅增加有限法术续接，冻结/死亡仍由公共执行器负责。保存、末次武器奖励及初始资格的边界见[契约](m3-conditional-consumers.md)，当前执行版本以原两份台账为准。

真实卡牌应组合已有公共效果，敌方随从持续嘲讽仅增加有限声明范围；生命设值、连击复制、武器死亡、随机额外效果与牌库逆序继续共用原执行器。新增范围及待国服边界见[配方契约](m3-public-effect-consumers.md)，下文历史初始范围不覆盖此后新增形状。

焚火林地第三次本人结束通过已有DiscardCard弃本物理HAND引用，当前复制和base复制仍走原进度/附件政策；不借存储摧毁、场上死亡或独立移除期限冒充弃牌。持牌消费者及待CN边界见[契约](m3-held-draw-forms.md)。

黑暗贿赂通过原物理抽牌组保存本组手牌，再用既有MoveCard交给对手；满手走原移区溢出，保留拥有者。defining_hand_source的特殊转交仍明确拒绝，不以普通手牌验证覆盖该缺口；见[抽牌组契约](m3-physical-draw-groups.md)。

真实同手卡面洗入由ShuffleSharedHandCard对完整敌手物理候选选一张，再交原MoveCard及CardReference。它不提供敌手选择或全知列表；同卡面依据和待CN政策见[私有手牌与复制契约](m3-copy-followups-hidden-pairs.md)。

本页描述 M3-03b-02 区域操作契约，当前版本及完整验证结果见[项目状态](project-status.md)。v79 已扩展[能力条件筛选](m5-ability-filters.md)。它不表示国服全部区域相关卡牌或官方交互已经校准。

代码集中在 [zones.py](../hs_sim/engine/zones.py)。区域内候选来自本局实际实体，和 [静态生成池](m3-generation.md) 分开：不查正式随机生成池，不因不可收藏或不可构筑而自动排除现存的牌，也不默认排除与来源同名的另一张牌。

## 原实体、新实体与捕获引用

`CardReference(entity_id, player_id, zone, card_id, zone_epoch)` 是一个不可变的物理牌引用，推荐用 `CardReference.capture(entity)` 建立。它保存当时的实体、控制者、区域、牌 ID 和修订号；只用于手牌/牌库，是受信任效果数据，不是玩家命令。

执行时先检查引用中的卡牌定义已实现，再检查实体是否仍满足全部捕获条件。未知定义报错；已离开区域、改了控制者、牌面或修订号的目标记录宿主诊断 `zone_target_skipped` 并跳过。已经离开后又以同实体/同牌面返回原区域，仍因修订号改变而失效；不能在选择反应后误操作再次进入的卡。

| 操作 | 身份与保留规则 |
| --- | --- |
| `AddToDeck` | 新实体，安装印刷定义；owner/controller 均为目的玩家 |
| `MoveCard` | 保持实体 ID 和 owner，controller 改为目的玩家；默认保留本地状态，可显式 reset 为印刷定义 |
| `CopyCard(mode='current')` | 新实体和新附件 ID，owner/controller 属于目的玩家；保留当前基础属性、伤害、耐久、尸体值、附魔、能力及沉默，记录 origin_entity_id |
| `CopyCard(mode='base')` | 新实体和新附件 ID，只用当前牌 ID 的印刷定义，不继承本地改动 |
| `DiscardCard` | 同一实体从手牌进入墓地，不生成死亡记录，不触发亡语或复生，也不增加尸体 |
| `RemoveFromGame` | 捕获的手牌/牌库牌或场上随从同时移入私有setaside，不进入墓地，也不建立死亡/弃牌/销毁事实；见[独立移除契约](m3-nondeath-removal.md) |

复制只支持从手牌/牌库进入手牌/牌库；场上复制仍使用原有 `CopyMinion`，回手与场上洗入仍遵循 [生命周期契约](m1-lifecycle.md)。手牌/牌库复制不继承攻击次数、入场顺序、光环、冻结等战场上下文。附件 source_id 保留历史来源，不影响新实体作为能力执行主体。

## 位置、容量、抽牌与弃牌

`AddToDeck(player_id, card_id, position='random', source_id=None)` 支持 top、bottom、random 或从 0 开始的整数插入间隙。整数必须在当时牌库长度范围内，越界报错，不静默截断。随机插入不打乱原牌之间的相对顺序。多次置顶逐个执行，因此后插入的牌位于更上方。

`GenerateFromPool` 已支持 `destination='deck'` 与相同 position。它先冻结生成牌 ID，再逐个执行加入牌库；各次随机插入位置在各自执行时计算。对局尚未设置正式的牌库容量上限；不能把工程结算预算当作游戏容量，精确上限和满库处理继续由 M0/M5/M6 核对。

`MoveCard(card, player_id, destination, position='bottom', draw=False, reset=False, source_id=None)` 只在手牌/牌库间移动。进入手牌追加到末尾；同一玩家手牌移到自身为 no-op。移入已满手牌时原实体进入目的玩家墓地并记录烧牌，保留 owner；只有 `draw=True` 才记录抽牌事件，且必须从该玩家自己的牌库进入手牌。普通 `Draw` 复用同一移动处理函数，原本的疲劳及逐张结算保留。

`CopyCard(card, player_id, destination=Zone.HAND, mode='current', position='random', source_id=None)` 不移动来源。满手烧掉新建复制，原牌不受影响；牌库复制使用指定插入位置。复制在效果执行时读来源当前状态，不在 Python 闭包保存实体。

`DrawMatching(player_id, query, empty_deck, count=1, selection='random', source_id=None)` 按印刷元数据及显式能力条件检索，selection 为 random 或 first。能力条件的 current 基准读取实际实体附件，printed 基准读取卡面声明。**empty_deck 必须显式选择 skip/fatigue**：前者空库无事发生，后者委托普通抽牌产生疲劳；牌库非空但没有匹配牌始终跳过，不抽任意替代牌。该参数是公共原语契约，不是对所有定向抽牌卡的统一官方裁定；接单卡时必须确定其正确策略。

`DiscardMatching(player_id, query=PoolQuery(), count=1, selection='random', source_id=None, reveal=True)` 按条件随机或顺序弃牌。两种 Matching 操作都每次选一张、执行并结算其反应，然后重新检索下一张；新加入或离开的牌影响下一次候选。空候选不消耗随机数。数量受结算预算约束，累计超限回滚。

`DiscardCard(card, source_id=None, reveal=True)` 默认公开弃掉的身份；False 只向控制者明确揭示，另一方可看到原牌背离开。此前已知的身份不会因此被遗忘。普通场上监听者可订阅 `card_discarded`。原生 `CardDefinition.on_discard` 已接入成功弃牌后的本牌主体，保存原不可变弃牌记录与独立上下文，复用既有解释器；见[本牌弃牌主体](m3-own-discard-bodies.md)。该入口不提供通用动态授予，其他隐藏区域触发与完整来源仍须显式支持，未知主体不得作为白板注册。

`ShuffleDeck(player_id)` 打乱整个牌库，使用本局 RNG；`ReorderZone(player_id, zone, entity_ids)` 要求当前区域完整、无重复的实体 ID 排列，不增删实体或改动附件。手牌重排保留可追踪句柄；牌库排列不进入玩家输出。

## 区域内选择

自动区域复制使用`CopyMatching(player_id, owner_id, zone, query=PoolQuery(), mode='current', count=1, selection='random', source_id=None)`。当前只支持手牌/牌库来源及复制到手牌，复用原候选和CopyCard；每个物理槽一个权重，同名原牌仍是独立候选。`lowest_cost`只用于手牌，按来源当前控制者的原纯报价比较，唯一最低不消费RNG，并列使用原随机源；一般random选择及空池政策与既有匹配操作保持一致。

每份复制及其入手反应完成后，下一份重新检索来源区域。来源原牌不移动，当前/基础材料和满手烧毁沿原CopyCard。未知定义/元数据继续明确报错，候选查询不接正式生成池。该入口不创建玩家选择或发布候选列表；内部RNG、物理来源、费用比较和完整帧不进入玩家DTO。原源保留、生命周期、失败回滚与挂起的新指令由共同解释器负责；精确复制政策及来源自己的可见性例外仍须逐卡国服校准。

`ChooseFromZone(player_id, owner_id, zone, query=PoolQuery(), operation='copy_base', sample_size=3, distinct='card', source_id=None, prompt=...)` 将选项交给已有 `RequestChoice`，无需另建玩家输入通道。

| 参数 | 当前契约 |
| --- | --- |
| player_id / owner_id | 选择者与被查看区域的玩家，可不同，选择者也可以不是当前行动方 |
| zone | 只允许 HAND/DECK；墓地、战场和其他区域不套用本契约 |
| query | 复用印刷类型/费用/职业/收藏性/稀有度/种族/派系/关键词及显式能力条件；当前能力读取本物理实体，所需信息未知则报错 |
| sample_size | 正整数时最多随机提供该数量；None 提供全部合格项，超过展示上限则报错，不截断总池 |
| distinct='entity' | 保留每张物理牌；重复牌可各占一个选项，选中效果引用精确实体 |
| distinct='card' | 仅复制操作可用；按精确牌 ID 分组，不自动合并其他印刷 ID，先按 ID 排序并按定义均匀抽选 |

distinct='card' 的 current 复制在抽出定义后，从同 ID 的物理牌中等概率固定一个引用，以保留该张牌的本地改动；额外重复牌不会提高这个 ID 被展示的权重。样本不足只展示现有项，空候选不请求选择。无抽样的物理选择保留区域顺序，这意味着调用方明确允许选择者获知该顺序；通常的牌库发现使用随机抽样。

operation 可为：

- `copy_base`：选项固定印刷定义，分支用 `AddToHand`；原牌之后离开不影响生成定义复制。
- `copy_current`：固定物理引用，分支用 `CopyCard`；执行时仍匹配才复制其当前状态。
- `take`：将选中的物理牌移入选择者手牌，不记录抽牌。
- `draw`：将选择者自己牌库中的物理牌抽入手牌。
- `discard`：弃掉选中的手牌，默认公开。
- `top` / `bottom`：将选中的牌库牌置于该牌库顶部/底部，保留本地状态。

取牌、抽牌、弃牌和重排只允许 distinct='entity'，避免把含不同附魔的多张牌悄悄当成同一个物理目标。候选、已固定的物理代表及效果分支进入帧，恢复后不重抽；当前状态复制与请求反应的精确官方顺序仍待 M6。

展示的手牌候选牌面明确加入选择者知识，未展示的敌方手牌仍为未知。牌库选项只显示候选牌面，不分配牌库实体句柄；不会借选项暴露来源牌在牌库中的位置。对手看到的 pending 仍只有选择者，无选项数量、牌面或选择结果。

## 可见性、版本与验证

新增玩家事件为 `card_added_to_deck`、`card_moved_to_deck`、`card_moved_to_hand`、`card_discarded`、`deck_shuffled`、`deck_reordered`、`hand_reordered`。牌库变化事件的 target 始终为空，不发布插入位置、实体 ID 或原始 Event.data；进入牌库会退休追踪句柄。复制的 origin_entity_id 只在宿主状态。一般烧牌沿用现有公开身份契约，官方可见性仍待校准。

当前运行时为 v21，快照拒绝旧 schema 1～73；观察为 player-view-v44，命令为 player-actions-v7。引用、查询和效果都是帧允许类型，严格恢复验证不执行存档里的 Python 代码。所有动作仍先在分叉执行，错误会撤销区域、附件、实体/附件计数器、知识、日志与 RNG 的改变。

[44 项区域测试](../tests/test_m3_zones.py) 覆盖移动/复制、位置、满手、重排、疲劳策略、反应后重查、私有选择、重复实体、当前复制、来源失效、未知定义、回滚/预算、快照/回放，以及三个真实代表卡。代表包为 `representative-m5-v38`，共 260 条原始记录，仍均为 partial / internally_tested。

新增暗影视界 `UNG_029`、亡者之牌 `ICC_091`、灵魂之火 `EX1_308`，均已校验本地源文件及单卡指纹。暗影视界从本局牌库的法术 ID 中选择 current 复制；亡者之牌按当时剩余手牌顺序返回复制入库效果；灵魂之火复用法术伤害后随机弃牌。三个适配都没有宣称覆盖所有复制/弃牌特殊交互。[18.0.1 官方热修帖](https://us.forums.blizzard.com/en/hearthstone/t/1801-server-hotfix/39314) 明确暗影视界仍可发现牌库中另一张同名牌，因此本局区域候选没有套用随机生成的排除自身规则；这条历史证据不代替当前国服整体校准。

```powershell
python -m examples.zone_operations
python -m unittest discover -s tests -p test_m3_zones.py -q
```

[组合示例](../examples/zone_operations.py) 是跨职业机制场景，经过玩家接口依次打出亡者之牌、暗影视界、选择、灵魂之火，并验证等待快照恢复与完整回放。固定 seed 29 下为 4 次动作、23 条原始事件，最终 1 手牌、5 牌库、5 法力，对方英雄 26 血；摘要 `f815ad29ef8fb55c41adcc2dab74d943b4fbad85343873902122eb308c1a4bd2`。输出 `outputs/zones-*` 是全知宿主存档/回放，不是玩家观察文件。

[交易/锻造及跨层对局](m3-hand-actions.md) 已通过内部验收，星舰基础链路已内部验收，地标通用入口与星港已内部验收，英雄牌/雷诺发射历史已内部验收，一般休眠与唤醒已内部验收，泰坦能力也已内部验收，任务/任务线进度也已内部验收，持续目标与玩家长期效果也已内部验收，奥秘与打断窗口已内部验收，M5-01 初始依赖盘点、出牌历史/连击/流放已内部验收，M5-02 法术迸发/暴怒与有限次触发已内部验收，M5-03 存储升级、手牌进度/腐蚀/注能已内部验收，M5-04 额外出牌条件已内部验收，M5-05 磁力已内部验收，M5-06 巨型已内部验收，M5-07a 兆示基础已内部验收，M5-07b-01 相邻光环/生成费用及三职业代表已内部验收，M5-07b-02 术士相邻牺牲已内部验收，M5-07b-03a 死亡之翼/奥卓克希昂已内部验收，M5-07b-03b-01 古加尔牌库销毁已内部验收，M5-07b-03b-02 关键词光环/艾萨拉已内部验收，M5-07b-03b-03 奥拉基尔已内部验收，M5-07b-03b-04 希奈丝特拉已内部验收，M5-07b-03b-05 奥妮克希亚已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。正式卡池完整性、容量常量、特殊区域自身触发、延迟复制/附魔窗口及官方顺序继续由 M0/M5/M6/M7 跟踪，不能用本批内部通过替代这些门槛。


M4-01b-02 追加 `AddToHand(..., cost=CostSpec(...))`：在创建/入手事件前原子安装费用附件，入手反应不会看到未修正费用；不匹配类型报错。专用 choice-only 定义不能生成物理实体，详见 [协议契约](m4-protocols.md)。

当前 CardReference 还捕获 `zone_epoch`；移区/换控制者/牌面改变后旧引用失效，即使同一实体随后原样返回。重新排序不改修订。储存随从属性修改可用 BuffStoredCard，手牌换形可用 UpgradeHandCard；精确保留表与限制见 [升级基础](m5-hand-upgrades.md)。

M5-04 成功进入手牌时会写入 HandEntryRecord；当前复制和基础复制各自获得新的获取记录，重排/同手牌移动/存储升级不会刷新。烧毁没有成功获取，跨手牌按最终控制者记录。见 [获取生命周期](m5-play-conditions.md)。

M5-12c-03c：`SummonFromPool` 在执行时验证版本池候选、检查场位再抽样，连续调用逐次重新检查场位。传送门复用物理洗入、抽到施放和玩家灌注累计，在施法行为中捕获费用查询；见 [R-105 契约](m5-imbue-portals.md)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为zone_operations.py：4动作/23事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 当前材料复制到现有实体

TransformStoredIntoCopy使用原当前复制材料安装到已有接收者，与CopyCard的新实体分配及TransformStoredCard的印刷重置分别表达。完整材料安装后才通知，特殊来源与复合政策未由此完成。见[公共契约](m3-stored-copy-transform.md)。


## 单个物理手牌的随机洗混

ShuffleHand(player_id, source_id=None)仅表达指定一方当前手牌的随机排列，来源和完整物理归属在RNG前核验。内核MT19937执行一次普通均匀shuffle，允许结果恰好原序；0/1张不抽随机。它不调用双手重新分配，也不改变owner/controller、实体、区域修订、手牌进度、当前身材、费用或附魔，不新建入手、抽取、弃置和洗牌库记录。

多张参与随机的卡统一退休隐藏追踪句柄，无论实际是否换位；否则对手能通过保留句柄获知隐藏排列。确定的0/1张保留原有效追踪。完整顺序一次交给原reorder_zone，在同一请求内完成写入后才捕获反应，没有中间空手或晚到的另一组手牌借位。每个请求发布一次原hand_reordered，带原ShuffleHand来源；内部reorder_zone只增加可选source_id关键字，旧ReorderZone数据形状及默认无来源事件保持。

新Effect按现有机制allowlist进入FrameCodec，待选前后和多个相继请求继续保存原剩余工作及MT状态，不重抽已执行排列。异常整动作回滚包括顺序、附件、知识、历史和RNG；玩家只取得原投影，不暴露全知顺序证明或随机状态。core692/schema551拒绝旧1～550存档，未声明迁移；无新状态或payload字段，观察117/命令13/replay1布局保持。实际随机算法及精确国服窗口仍待校准。
