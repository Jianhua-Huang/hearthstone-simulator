# 完整本人回合的印刷类型出牌关系

执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本页是[原本人回合及冻结提交卡面](m5-owner-turn-history.md)的追加只读接口，不定义具体卡牌的连续数量或费用重置时机，不表示国服校准已经完成。

## 原事实和完整关系

```python
from hs_sim.engine import CardType, PlayedTypeQuery, query_owner_turn_history

history = query_owner_turn_history(
    context.state, context.player_id,
    PlayedTypeQuery(CardType.MINION, tribes=("elemental",)),
)
for interval in history.intervals:
    original_turn = interval.owner_turn
    complete_rows = interval.rows
    any_matching_play = interval.matched
```

`OwnerTurnTypeHistory`保存原 player、query、完整有序 `OwnerTurnTypeMatch` 元组和 `outside_owner_turn_faces` 元组。固定 profile 为 `owner-turn.all-intervals-printed-type-v1`。每项保存完整原 `OwnerTurnRecord`、该玩家在该本人区间提交的查询类型卡面及 true/false、聚合 bool。多个匹配提交仍是同一匹配区间，空区间明确保存空 rows 和 false；不能丢掉非匹配行或空区间后推断“连续”。

只消费原 `owner_turn_history` 和 `play_history.played_face`。本人序号和前驱取原真正开始的区间，不按全局回合奇偶推断。既有额外和跳过调度继续决定哪些区间真实存在；额外同玩家开始各有实际区间，跳过机会不制造空区间。场景的概念首回合明确保留 `origin='scenario'`，构筑开局不造区间。

所有本人区间均保留，包括已关闭、当前开放、真实开始但尚未发布事件，以及开始中断后仍开放的终局区间。`publication_event`、`end_event`、`closed_event`和明确 `start_interruption`保持原值，查询不将建立区间、发布开始、自然结束和稳定交接混为一谈。某种费用政策该如何使用这些区间，须由该真实消费者另行声明和验证。

## 提交卡面和范围

行使用原冻结 `FrozenPlayedFaceFact`，按实际提交玩家、原区间 ID 和 `query.kind`筛选。这里只支持原 `PlayedTypeQuery` 的随从种族或法术单学派；查询类型以外的提交不进入关系行，其他玩家的提交不借用该玩家的区间。变形、控制转移、死亡或以后卡面变化不改变原行；同一物理牌回手再打是新的提交。召唤、生成和自动 CAST仍不伪造手牌提交。

开局前合法提交没有实际 owner 区间，原非行动方内部手牌提交绑定当时真正的另一玩家区间。两者保留在 `outside_owner_turn_faces`，不移入本人区间，不制造本人开始，也不执行该区间的类型谓词。其未知种族仍明确保留，不据此构造一个 false 匹配行。该字段只包含所查询玩家及类型的原卡面；其他玩家和类型仍在原全知 State历史中。

公共关系与既有“最近已结束本人回合”共用 `_validate_type_query` 和 `_match_face`；参数守卫及原种族/单学派匹配从原代码完整提取，没有另一套匹配规则。随从按原提交印刷种族，`all`双向匹配非空集合，已知空不匹配；查询主体或本人所选区间候选的未知种族明确报错。先检查完整候选，不让前一个 true 隐藏后面的未知。完整历史会检查较早的候选，旧单回合接口仍只检查它原来选择的区间。

法术单学派按原明确值相等匹配；无学派不与无学派匹配。不暗加多学派、当前种族、任意表达式或授予能力。

## 不改变旧接口及证明边界

`query_previous_owner_turn`仍只选最近已关闭本人区间，保留原 `PreviousOwnerTurnMatch`、完整 true/false 行、unknown范围和 `owner-turn.latest-closed-v1`。它没有被改为全历史查询，原 H2固有条件、原接受证明和所有回合/出牌/付款执行器仍使用既有语义。

新两类只读值严格检查原字段类型、玩家/区间/查询对应、本人序号/前驱、原顺序、重复提交、聚合 bool和每行匹配值。它们是引擎用可信 State 重新得到的关系，不是可独立接收的外部存档或来源认证。完整性来自实际 State 查询，不能用自行拼装的较短对象冒充一次原捕获；未来冻结费用消费者仍须保存其完整原状态依据并验证原窗口。

查询只读取原事实，不分配实体/附件/游标、消费 RNG、写历史或生成事件。原等待和后续发布/关闭可以合法推进；之前得到的冻结值保持原状态，新查询读取新状态。异常事务和真正回溯复用原历史恢复，不另造一份可变连续计数缓存。

## 代表和兼容性

必要 [CS2_118 岩浆暴怒者完整 raw/pin](../data/support/owner-turn-type-history-basics.json)是3费5/1中立基础元素，原文字为空，没有漏接主体；只在隔离验证注册表声明完整普通随从。支持文件 pin为 `b492c6115b29f02a9afd9eda9ad9d12a0200095846ed6676f82120f7f0a3f563`。本页支持文件中的WW_025艾泽里特巨人和TRL_313灼烧仅保存完整需求原行；WW_025的独立隔离费用声明另见[连续元素数量费用契约](m3-player-elemental-streak-costs.md)，不改变本页查询政策。[官方艾泽里特巨人卡库](https://hearthstone.blizzard.com/en-us/cards/100234-azerite-giant/)提供连续回合需求文字，不提供本页查询的国服时序验收。

本接口引入时仍为prototype-v221/core-effects-v215/schema206、观察74/命令11/replay1，生产代表64/合成3保持。没有新 State/Entity/Player/卡牌字段、存档字段/显式帧类型注册项、Effect、事件、动作或执行器；已有保存、原类字段和原测试无需协议迁移。新关系只属于全知引擎，不直接交给玩家观察、动作或过滤事件。生命周期、选择恢复、回放和信息边界沿原管线；真实连续费用政策、完整基础范围、正式池和国服校准继续开放。

原FrameCodec自动收集模型内frozen dataclass；本页两只读结果也属于该自动类型集合。没有新增专用帧字段或显式类型注册入口，不应把旧“无帧白名单项”表述理解为自动集合完全不变。

种族字段按生产元数据已有标识使用小写elemental；必要CS2_118声明与连续元素及上回合元素费用查询共同对齐该标识，原严格匹配规则和raw/pin保持。见[上回合元素费用契约](m3-previous-owner-elemental-costs.md)。
