# 自身回合历史与冻结提交卡面

翡翠厚赠的有限手牌禁用复用owner_deadline与原真实本人开始索引，按原创建区间校验第二次后续开始；不按全局奇偶或对手回合猜时钟。到期标记可保留为无作用原材料，无新倒计时账户，见[抽牌保留契约](m3-draw-retention-limits.md)。

根心之石只问最近已关闭本人区间是否存在随从提交，直接读取该区间的完整原冻结提交行，不把种族交集查询误用为“任意随从”；直接召唤和当前区间不代替上一自身回合。无前一区间及接受窗口政策见[抽牌组契约](m3-physical-draw-groups.md)。

本页描述 `prototype-v112` / `core-effects-v112`、snapshot schema109 的公共接口。实际执行、验收与下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。原批范围不包括条件式固有费用、额外或跳过回合调度，也不证明完整卡池或国服时序。2026-10-09新增调度沿用本页真实区间，见[独立回合调度](m3-turn-scheduling.md)；跳过机会不记录为实际区间。

## 实际回合区间

`GameState.owner_turn_history` 保存不可变 `OwnerTurnRecord`，由内核的真实开始和自然交接入口写入。按玩家各自保存序号及前一个自身区间；查询不使用全局回合奇偶或手牌获得时间推断过去。

| 事实 | 语义 |
| --- | --- |
| `id`、`player_id`、`owner_index`、`previous_id` | 实际区间身份、归属和同玩家前驱 |
| `turn`、`start_action`、`start_event` | 原全局回合、开始动作及开始前事件游标 |
| `origin` | `scenario` 是实验场景的概念首回合；`actual` 是真正执行的开始入口 |
| `publication_event/action` | 真正发布的开始事件；可以晚于建立区间的动作 |
| `end_event/action` | 真正自然结束事件，尚不表示结束主体和到期已经结算完 |
| `closed_event/action` | 所有自然结束反应及到期处理完成后的实际交接边界 |
| `start_interruption` | 启动到期处理中、发布开始事件之前发生致命终局的明确证明 |

`from_scenario` 产生一个概念首回合，可以由任一玩家先手。构筑初始化清除临时场景区间，开局和换牌不制造自身回合；真正 `StartFirstTurn` 才记录第一实际区间。首 `game_started` 精确绑定开始游标后一项。相邻区间的旧关闭与新开始动作、事件游标一致。

自然结束先发布 `turn_ended`，再处理完整主体、反应和到期，最后才关闭区间。主动调用额外结束能力不关闭或创建回合。中途致命终局保留开放区间；工程规则 `draw_after_turn` 在自然交接处关闭当前区间后结束，不制造下一回合。

## 启动与事件发布分别记录

`StartNextTurn` 已建立新区间、更新资源，然后处理关键词到期；`BeginTurnEvents` 随后发布 `turn_started`。到期反应可以选择等待，真正发布事件可能发生在更晚的 `SelectChoice` 动作。

等待时，最后开放区间可以处于 pending，挂起帧必须保留唯一真正的 `BeginTurnEvents` 和原开始 root action。发布后记录实际事件序号及动作，只允许单调推进。致命启动在解释器丢弃队列之前验证这项工作，保存 typed `OwnerTurnStartInterruption`，恢复再与真正的 `hero_death` 终局事件核对；不能仅由终局 status 倒推出这个阶段。

## 冻结从手牌提交的卡面

每个 `PlayRecord.played_face` 保存完整 `FrozenPlayedFaceFact`：原 play/source/player、所属区间、提交 card ID、印刷类型、完整 `CardMetadata` 和明确单学派。在 `prepare_play` 付款前捕获，付款成功后随记录进入历史。

冻结事实描述当时提交的牌。后来变形、转控、离场或获得新的卡面不重写它；同一物理牌回手再打产生新的事实。被反制或后来终局中断的成功提交仍保留；非法操作与异常事务回滚不留下记录。额外主体、保留结果和选择恢复不再追加提交，真实 Rewind 随原 timeline 恢复整段历史。

内部非行动方 `PlayFromHand` 分别保存出牌玩家和真实区间 owner，不给付款者伪造回合。合法开局内部提交保存 `owner_turn_id=None`、明确 opening stage 和 first player；真实区间查询排除它。既有 `card_committed` 的根身份和事件序号区分同一个动作内的 pre-first 提交与已开始回合的提交。

召唤、获得、自动 CAST、抽到时施放及历史施法不产生手牌提交事实。既有 [出牌历史](m5-play-history.md) 与独立施法历史仍各自负责原语义。

## 纯查询及完整候选

```python
from hs_sim.engine import (
    CardType, PlayedTypeQuery, SpellSchool, query_previous_owner_turn,
)

dragon = query_previous_owner_turn(
    context.state, context.player_id,
    PlayedTypeQuery(CardType.MINION, tribes=("dragon",)),
)
arcane = query_previous_owner_turn(
    context.state, context.player_id,
    PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE),
)
```

`query_for_definition(definition)` 从明确注册定义构造同一查询。结果 `PreviousOwnerTurnMatch` 保存原查询、选定区间、有序完整 `OwnerTurnMatchRow` 和聚合 bool，每一行保留完整冻结事实及 true/false。先遍历并验证全部候选，再聚合；前面的 true 不隐藏后面的未知。

当前 profile `owner-turn.latest-closed-v1` 选最近已关闭的自身区间。自己的当前区间不参与；对方回合查询己方最近 closed。没有这个区间时结果为空。它是版本化内部政策 **R-158**，须在 M6 校准，不能用本接口声称额外或跳过回合的调度已实现。

随从按明确提交种族交集匹配；`all` 双向匹配非空种族。`metadata=None` 或 `tribes=None` 是未知，明确报错；`tribes=()` 是已知空，不匹配包括 `all` 在内的任何种族。未知查询主体即使没有历史也报错。法术按明确单学派相等匹配；无学派 `None` 不与 `None` 匹配，不暗加多学派能力。

查询不修改状态、事件、RNG或分配器。规则回调可用结果组合既有效果，条件式固有费用将在独立 H2 接入。

## 保存、原接受窗口和玩家边界

schema109 保存严格 typed 区间与卡面，拒绝旧1～108，要求原引擎；不静默补历史。FrameCodec验证完整卡面与冻结注册定义一致。普通快照、clone、回放及 Rewind 共用该表示。

六族原接受窗口保留完整区间和提交卡面前缀。开始身份和游标、已关闭记录、已存在的发布/结束/中断事实与冻结卡面不得被重写；原开放区间只可发生真实单调进度。完整边界检查绑定实际事件及挂起工作。这里是可重算一致性验证，不是未签名独立存档的外部来源认证。

进度事实不能晚于所属捕获状态的动作号。原窗口缺少一个进度事实而当前已经具备时，该进度的真实动作必须不早于原窗口捕获动作；同动作中的早期emit及等待后更晚发布都合法。由此拒绝较晚窗口把早已发布的回合改为pending，致命中断使用真正game-ended动作，不借较早root动作推断。

完整历史、冻结卡面、区间游标和原接受证明只属于全知引擎。玩家继续使用 `PlayerPort` 的观察、合法动作和过滤事件；公开view55/action7保持，不把全知快照或查询明细直接交给玩家。

原生公共效果示例见 [owner_turn_history.py](../examples/owner_turn_history.py)：打出的龙变为野兽，随后历史仍按龙匹配；对方回合及下一自身回合使用同一 closed 区间，付费法术选择后继续，并对未知查询验证事务回滚。实际验证结果以项目状态为准。
