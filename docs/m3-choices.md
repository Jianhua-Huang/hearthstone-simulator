# M3-01：挂起选择与可恢复结算

M5-07b-03b-04 增加 `RequestChoice.repeat_key`：显式效果内选择可在同一法术后续遍沿用选项 ID，普通发现仍每遍重新选择；选择键与缓存进入全知存档但不进入玩家 DTO。见 [重复施放契约](m5-spell-repeats.md)。

本页原批次运行时 `prototype-v75` / `core-effects-v75`，snapshot schema 74，代表包 `representative-m5-v38`。本页定义已实现的原型契约，国服官方时序校准仍在 M6。整体进度见 [项目状态](project-status.md)，开发顺序见 [长期计划](roadmap.md)。

## 1. 模块与状态边界

卡牌返回 `RequestChoice`，由 `choices.py` 建立选择；`resolver.py` 保存 `ResolutionFrame`，`continuations.py` 负责严格的类型白名单编解码。玩家通过 `SelectChoice` 提交结果。卡牌回调不能自行读取控制台输入或保留 Python 执行栈。

`GameState.pending_choice` 保存选择 ID、指定玩家、来源、提示、候选元数据和选择数量范围。单个 `ChoiceItem` 有 ID、显示标签及可选卡牌/实体引用。`purpose` 区分普通效果与换牌。它不包含执行代码，也不代表玩家信息已经过滤；状态、快照、事件仍是全知接口。玩家改用 `Game.observe` / `player_events`，见 [信息契约](m3-information.md)，内部选择/选项 ID 不直接下发。

结算帧位于 `Game`，快照顶层使用 `resolution_frame`。帧保存：根操作序号、累计结算步数、是否正在结束回合、请求效果捕获的反应、后续工作队列、冻结后的候选效果分支和可选结果回调 ID。捕获的 `BehaviorCall` 保存原 `RuleContext` 状态、事件、死亡记录或选择结果；恢复时不重新捕获或规划已经展开的指令。

分开保存状态和帧，可避免触发上下文的状态副本又递归包含整个结算帧。两个稳定边界都允许 `snapshot()`、`clone()` 和回放：普通队列已经执行完毕，或者已经挂起等待选择。处理器正在执行时仍禁止这些操作。

## 2. 公共接口

```python
from hs_sim.engine import SelectChoice
from hs_sim.engine.effects import ChoiceOption, RequestChoice, Draw, GainArmor

def choose_reward(ctx):
    return [RequestChoice(ctx.player_id, (
        ChoiceOption('draw', '抽两张牌', (Draw(ctx.player_id, 2),)),
        ChoiceOption('armor', '获得3点护甲', (GainArmor(ctx.player_id, 3),)),
    ), source_id=ctx.source_id, prompt='选择一个奖励')]

# 出牌后检查 game.state.pending_choice；只有指定玩家能够提交。
pending = game.state.pending_choice
game.apply(SelectChoice(pending.player_id, pending.id, ('draw',)))
```

`SelectChoice` 的 JSON 类型为 `select_choice`，字段为 `player_id`、`choice_id`、`option_ids`（字符串数组）。重复项、未知项、过期选择 ID、错误玩家和不合数量范围的结果均拒绝。等待期间禁止出牌、攻击、技能和结束回合；选择方可以不是当前回合玩家，双方仍可在已提交边界独立认输，见[认输契约](m3-logical-concession.md)。

- `min_count` / `max_count` 支持单选、多选和可选空选。输入顺序不改变效果顺序：选中项按原候选顺序执行，结果事件也规范化到此顺序。
- `on_select` 是已注册的行为 ID。回调通过 `ctx.choice` 获得 `ChoiceResult`，其中 `choice` 保存原选项，`selected_ids` 与 `selected` 保存结果。回调在选择反应后、单项分支前执行，获取当时的新状态，便于后续换牌处理整个选择集合。
- `sample_size` 从调用方明确提供的选项中使用对局 RNG 无放回抽样一次。全部原始候选必须可编码、引用已知卡牌/行为；不通过抽样掩盖未实现候选。抽样及 RNG 状态在首次挂起时提交，恢复不重抽。
- `max_count=0` 自动发出 `choice_skipped` 并执行结果回调和后续效果，无需提交空动作；仍消耗单调递增的选择 ID。
- `legal_actions()` 枚举选择组合，不枚举排列。默认最多展示 32 项，枚举上限 4096 个组合；超限明确抛出工程异常，不截断候选或改变规则。可以通过 `Ruleset` 调整，或直接从 pending 元数据构造合法 `SelectChoice`。

## 3. 结算与事务约定

请求选择的效果完成正常的光环/死亡检查后挂起。其反应、后续效果和外层剩余队列全部保留。提交结果先记录 `choice_selected` 事件，再依次执行：

1. 请求选择时已经捕获的反应。
2. 提交结果事件捕获的普通触发。
3. 聚合结果回调，然后各选中选项的效果。
4. 原操作的后续工作，例如出牌完成、技能完成、攻击伤害或回合切换。

每个效果仍经过原有统一检查点。反应本身也可以发起另一个选择；父选择已经选定的分支会留在剩余队列中，不重复提交。已死亡来源的实体/死亡前记录仍可供捕获回调读取。终局清空 pending 和帧，停止余下队列。

一次挂起是已提交边界。此前完成的费用支付、区域变化及事件已经生效；非法或执行失败的选择回滚到这个边界，包括状态、帧、RNG、事件和动作历史。第一次挂起前发现不可保存的指令，则整个出牌操作回滚。内核不会恢复已经提交的费用，也不会在选择时重复支付。

根操作的步数预算跨所有后续选择累计；提交选择本身也收费，不通过多次点击重置预算。预算用尽时回滚当前操作，不伪造平局。结束回合的标志也保存在帧中，恢复后的冻结/解冻与回合切换继续使用原语义。

上述请求反应与选择反应顺序是明确的原型约定。滋养已在M5-13c迁移为支付前确定分支；分支目标/合并及奥秘/施法交互见[抉择契约](m5-choose-one.md)，不再以RequestChoice模拟手动抉择。不得据此把所有抉择卡标为完整支持。

M4 发射阶段追加 `death_deferrals` 与明确的结束标记，等待选择时可以保留尚未移除的致死实体；恢复继续结算，最外层发射结束后清理。普通操作边界仍须完成死亡检查，详见 [星舰契约](m4-starships.md)。

## 4. 快照与扩展契约

原批次schema 74 的状态摘要包含整个帧和候选分支，即使无等待也显式包含 `resolution_frame: null`。必须同时存在合法 pending 和匹配帧；选择 ID、元数据、预算、根动作号、所有字段类型及引用均校验。旧 schema 1～73 明确拒绝；外层 replay schema 仍为 1。

挂起队列只编码已注册效果类型、内建不可变值类型及显式注册的扩展值。格式记录类型标识和数据，不从 JSON 执行动态导入、反序列化 Python 回调或恢复生成器。每个 `BehaviorCall` 引用的行为由调用方提供的匹配注册表解析。摘要用于检测改变，不是对恶意文件的数字签名。

自定义效果必须是 frozen dataclass；其嵌套值使用None / bool / int / str、tuple、枚举或 frozen dataclass。额外值类通过 `mechanics.register_payload_type(ValueClass)` 登记，登记集合进入机制签名；效果本身仍必须通过 `register(EffectClass, handler)` 注册处理器。未注册值、可变列表/对象、调用函数、未知效果或缺失行为在挂起提交前明确失败。嵌套深度有 64 层工程护栏。

冻结 Python 数据类不等于冻结回调函数体：实现语义变化仍要求提高注册表或效果包版本。M8 继续处理更严格的发布指纹。

## 5. 代表卡与运行示例

本批增加锁定本地记录的滋养 `EX1_164`：5 费自然法术，获得两个法力水晶或抽三张牌。两个分支复用现有资源/抽牌机制，测试包含水晶上限、满手烧牌及疲劳。其支持状态为 partial / internally_tested；出牌前分支及合并选项已内部实现，精确时序和特殊上限交互没有官方认证。完整正式发现池及更多真实来源仍按M0/M7维护；原批次额外卡牌拒绝不作为当前通用选择接口范围。

```powershell
python -m hs_sim simulate examples/scenarios/choices.json --actions examples/actions/choices.json --card-set representative --replay-out outputs/choices-replay.json
python -m hs_sim replay outputs/choices-replay.json --card-set representative
python -m examples.resume_choice
python -m unittest discover -s tests -p test_m3_choices.py -v
```

[场景](../examples/scenarios/choices.json)、[动作](../examples/actions/choices.json) 和 [保存恢复示例](../examples/resume_choice.py) 演示连续两次滋养出牌前分支：第一张补水晶后可以支付第二张，第二张抽三张牌。共 2 次动作、10 条事件，最终 10 水晶、0 可用法力、3 张手牌；双方英雄 30 血。逐步回放摘要为 `0680eb3d4044e329e13f7924a74ebd12eea7acb00e207447dc6585ab350ce3f5`。

示例现在保存普通出牌前快照和对应回放，再从该边界选择不同分支或恢复双牌流程；不再产生pending滋养选择。真正结算内挂起由选择专项及其他发现/技能示例验证。输出位于 `outputs/choices-*`，均只需本项目注册表，无需运行客户端。

本批 [34 项选择测试](../tests/test_m3_choices.py) 与 [70 项代表卡测试](../tests/test_representative_cards.py) 已通过；全量结果统一记录在项目状态。M3-02 的普通构筑/开局、先后手、换牌及硬币已内部验收，见 [开局契约](m3-opening.md)；M3-03a 玩家视图与受限操作已实现；[静态生成池](m3-generation.md) 已接入，区域操作及区域内候选已接入，地标入口与星港已内部验收，英雄牌与雷诺发射历史已内部验收，一般休眠与唤醒已内部验收，泰坦能力也已内部验收，任务/任务线进度也已内部验收，持续目标与玩家长期效果也已内部验收，奥秘与打断窗口已内部验收，M5-01 初始依赖盘点、出牌历史/连击/流放已内部验收，M5-02 法术迸发/暴怒与有限次触发已内部验收，M5-03 存储升级、手牌进度/腐蚀/注能已内部验收，M5-04 额外出牌条件已内部验收，M5-05 磁力已内部验收，M5-06 巨型已内部验收，M5-07a 兆示基础已内部验收，M5-07b-01 相邻光环/生成费用及三职业代表已内部验收，M5-07b-02 术士相邻牺牲已内部验收，M5-07b-03a 死亡之翼/奥卓克希昂已内部验收，M5-07b-03b-01 古加尔牌库销毁已内部验收，M5-07b-03b-02 关键词光环/艾萨拉已内部验收，M5-07b-03b-03 奥拉基尔已内部验收，M5-07b-03b-04 希奈丝特拉已内部验收，M5-07b-03b-05 奥妮克希亚已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)，见 [玩家操作接口](m3-player-api.md)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为resume_choice.py：2动作/10事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。

随机改打错误敌人已用原抽样/零项自动回调与RedirectAttack表达，见[独立表达契约](m2-wrong-enemy-attacks.md)。不请求玩家作选择，内部计数/choice_skipped保留；原接口与上述历史阶段证据保持，当前核心仍prototype-v201/core-effects-v195/schema189。精确CN待校准。
