# 历史发现、重施与池内批量施法

真实原生法术参数绑定原亡语执行与物理材料，当前费用/亡语抽取连接原手牌奖励；首回合和后续正常抽牌共用可移除来源门禁。有限字段、公共执行及未覆盖继承边界见[亡灵资源契约](m3-undead-resource-native.md)。

M5-10d 公共子集，`prototype-v75` / `core-effects-v75`，snapshot schema 74。玩家视图 v32、动作 v6、外层回放 1、代表包 `representative-m5-v38` 不变；未增加真实卡牌。实现见 [spell_history.py](../hs_sim/engine/spell_history.py)，验证见 [68 项专项](../tests/test_m5_spell_history.py)。概率、计数、来源和窗口政策登记 **R-090**，尚未获得国服校准。

## 历史候选与发现复制

v79扩展：`cards.ability` 不会被忽略。当前可执行法术种类不能带战吼，因此current战吼条件为false；printed查询历史卡面的定义。参见[能力筛选上下文](m5-ability-filters.md)，该功能不等于历史战吼重演。

`SpellHistoryQuery` 描述施法玩家阵营、`hand/repeat/effect/draw/history` 来源、回合区间、施法 ID 上界及排除项；`cards: PoolQuery` 继续按印刷费用、派系、职业、关键词等过滤。`outcomes` 明确区分：

- `successful`：已完整执行且没有失败；默认不包含当前正在执行的法术。
- `completed`：已结束的尝试，包含反制和无目标失效。
- `attempts`：包含进行中或被终局截断的尝试。

`spell_history_candidates` 是宿主/规则查询，不向玩家提供全知历史。它读取历史里的卡牌身份和当时施法玩家，不从当前实体区域或当前控制者反推历史。历史候选来自真实记录，独立于正式生成池；不因普通生成禁令删除确实施放过的历史牌。

`DiscoverSpellHistory` 使用这些候选建立私有选择，选择后生成基础卡复制。该行为不重新施法，也不重建原实体附件、原费用或过去选择。空历史跳过；满手按正常生成烧牌；自动施法内的发现沿用自动选择政策，玩家来源可以挂起并通过受限玩家接口恢复。

`distinct` 必须与具体规则匹配：`cast` 逐次施法为候选，允许同卡多个选项；`card` 按确切定义 ID 去重；`identity` 按已登记的生成别名身份去重，未登记别名以原 ID 为身份。后两者按组等概率抽样，并以组内最早记录的卡面作为生成模板，不以重复施法次数加权。`cards.exclude_source=True` 排除来源当前定义的所有历史记录；别名范围和具体“其他法术”的口径仍需单卡及 M0/M6 确认。

## 历史重施

`RecastSpell(player_id, cast_id, source_id=None, target_id=None, targeting='random', choices='random')` 新建基础法术实体，引用旧 `SpellCastRecord` 的印刷身份并在当前状态执行。新施法标记 `origin='history'`，`recast_id` 指向被引用的旧尝试；新实体 `origin_entity_id` 指向旧法术实体，发起效果来源独立放在 `caster_id`。

重新执行会重新计算当前连击/法力渴求和随机结果。`targeting='original'` 重用旧目标引用并重新校验，旧目标失效则失效；`random` 重新抽目标，`explicit` 使用指定目标。旧选项与旧 RNG 结果不会被机械重播。自动施法的支付、出牌、回响及反制窗口隔离继续沿用 [施法契约](m5-spell-casts.md)，双生法术仍走公共衍生流程。抽到施法标记不会使历史重施自动补抽。

`RecastFromHistory` 在开始时冻结候选记录与截止 ID；后续产生的历史不会加入同批。可显式设置总次数、按最早/最新/随机选择、是否放回及去重身份；`count=None` 使用初始分组数。每次完整执行及其触发/选择结束后才选择下一项，失败尝试仍消耗一次名额。所有循环受工程预算限制，耗尽回滚，不冒充官方平局。

## 版本池批量施法

`CastFromPool` 使用既有版本/模式候选池、元数据过滤、生成身份去重和整数权重抽样；隐式限定物理法术。它检查所有合格候选的实现，不能因为某个候选未实现就偷偷剔除，也不退回另一个版本池。

- `refresh='per_cast'` 每次重新查询当前职业等条件；前一张改变英雄职业时，下一张可使用新的候选。
- `refresh='frozen'` 在开始时冻结候选、权重和查询职业，保留原候选范围。
- 两种政策都逐张选牌并结算目标、效果、触发和选择，然后继续；不提前抽完全部结果而改变 RNG 交错。
- `replacement=False` 按生成身份移除已选卡，包括别名；默认允许重复。
- 默认来源离场不自动取消后续工作。显式 `while_source_in_play=True` 记录来源区域版本，离场或换区后停止；源卡特例必须选择其对应政策。

数量由效果创建时的显式整数冻结，例如用历史查询结果长度构建批量施法；新施法不会让同一批的总次数膨胀。空候选停止，无目标失效仍计一次，终局停止剩余工作。池内法术记录为普通 `effect` 来源，宿主通过发起实体关联；没有伪造手牌打出。

## 恢复与证据

历史及池内批次续接是冻结、可序列化的效果。历史边界检查候选顺序、截止 ID 和引用存在；池边界核对冻结候选/权重与原版本声明、移除身份数量及来源区域版本。重施历史检查祖先 ID、卡牌身份和原实体引用。选择、克隆、JSON 恢复、回放、错误/预算回滚和玩家隐私都有专项覆盖。

[官方倒带卡文](https://hearthstone.blizzard.com/en-gb/cards/90592-rewind/)及冻结 `ETC_532` 确立历史发现需求；`OG_134` 确立基于历史数量的随机施法需求。`DMF_236` 的同费用施法替换还需要打断窗口组合，不能由本批接口存在宣称完整实现。计数口径、随机概率、别名归并、原目标/原选择政策、来源中止条件和特殊自动施法分支仍为 R-090，具体真实卡适配归 M7，完整候选池归 M0。

68 项专项覆盖历史筛选、复制/重施区别、去重政策、嵌套批次、职业切换、选择及玩家动作恢复、终局、候选缺失、预算、回滚、快照损坏及回响/双生/抽到时组合。原有自动施法 54 项和抽取 60 项另已通过；全量结果见 [项目状态](project-status.md)。

## 计划纠正与下一项：回溯关键词

旧机器计划把 `REWIND` 家族误写成“按本局法术历史建立发现候选”。本批已纠正：`ETC_532` 英文名 Rewind、中文名倒带，是历史发现卡；**回溯关键词**要求玩家查看当前随机结果后，选择保留或重新执行，适用于法术和随从。官方 [时光流转机制说明](https://hearthstone.blizzard.com/en-us/expansions-adventures/across-the-timeways)及 [34.2 更新说明](https://hearthstone.blizzard.com/en-gb/news/24244423)确立这一区别。冻结数据的 `TIME_000`、`CORE_EDR_004` 及保留两种结果的 `END_036` 是需求依据。

M5-11a 回溯检查点已通过 58 项内部专项，见 [回溯契约](m5-rewind.md)；它是独立于历史发现的结果撤销机制。M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；M5-12b-01 发掘进度通过内部验收，多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。整族仍 partial，特殊施放来源/计数和条件光环继续留在 M5。

## 逐次原Cast与整牌原Play的分支继承

RecastSpell与RecastFromHistory可显式声明branch_policy='inherit'；default current保留旧重选。批量每次使用真正选中的原Cast，去重/随机/放回和完整主体执行后继续的窗口保持。新合并政策及有限用途每个新根独立接受，目标按该分支及原声明重新校验，主体内选择/RNG继续新执行。

整牌历史法术使用独立spell_branch_policy，从自己的原Play occurrence继承而保持effect CAST身份；它不借批量Cast的祖先ID、手牌付款或物理profile。原记录/窗口/收据、选择恢复、临时配方与剩余范围见[公共契约](m5-history-branch-replays.md)。本扩展不认证所有正式来源或R-090国服时序。

## 历史发现的预选交付

`DiscoverSpellHistory`现在接受`branch_policy='current'|'inherit'`。current仍生成没有选择配方的基础手牌；inherit在offer形成时使用原分组canonical首个Cast的branch，只授权hand。待选内保存typed AddToHand，不重施法，不重放旧目标/RNG或支付。去重、别名、随机取样和烧牌仍沿本页原政策；配方在card_created前原子设置。见[声明及来源边界](m5-choose-branch-producers.md)，本接口不是所有历史来源或R-090国服认证。
