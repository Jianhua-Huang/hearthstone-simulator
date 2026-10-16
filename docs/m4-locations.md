# M4：地标实体与主动使用

原生残骸获得倍率保留可移除来源和固有死亡基数；物理消费者检索、原目标支付及真实任务/地标/第二技能依赖见[残骸消费者契约](m3-corpse-consumer-native.md)。已有第二技能槽安装仍明确未支持，不能以首次安装认证整卡。

本批为 M4-01b-03b，运行时 `prototype-v75` / `core-effects-v75`，snapshot schema 74，代表包 `representative-m5-v38`。玩家观察升级为 `player-view-v44`，命令为 `player-actions-v7`。目标地区保持国服，完整官方校准仍在 M6；英雄牌流程与雷诺发射历史已另内部验收，一般休眠与唤醒已内部验收，下一项是泰坦等有限次主动能力。整体范围见 [长期计划](roadmap.md) 与 [项目状态](project-status.md)。

## 规则依据及暂定范围

[纳斯利亚堡上线公告](https://news.blizzard.com/en-us/article/23831407/murder-at-castle-nathria-is-now-live) 说明地标可在打出后立即使用，使用不再支付法力、消耗一点耐久，并在本回合及自己的下一回合不能再次使用。[官方玩家指南](https://news.blizzard.com/en-us/article/23850855/welcome-to-the-players-tavern) 说明零耐久移除。[30.2 官方修复](https://news.blizzard.com/en-us/article/24122902/30-2-patch-notes) 明确地标不是随从但占用场位。[35.0 公告](https://hearthstone.blizzard.com/en-us/news/24267727) 包含具有亡语的地标，因此销毁时不能一概丢弃所有能力。

基础规则有上述历史官方依据；**最后一点耐久、主动效果与亡语的精确顺序、满场最后一次使用、提前开启及冷却更新窗口**尚未通过国服对局校准。下面是可复现的 **R-037 原型契约**，不得据此宣称完整正式支持。

## 场上对象与共同入口

`CardType.LOCATION` 与随从区分，`PlayerState.board` 表示有顺序的共享场位。随从、地标和建造中的星舰合计受场位上限约束。实体保存 `kind`，恢复时必须与卡牌定义一致；`Entity.is_character` 仅对英雄/随从为真。

地标使用独立 `durability`，没有攻击力、生命、护甲、冻结或战斗关键词。普通目标默认只包含角色，地标不能攻击或成为攻击目标；伤害、治疗、数值增益、关键词授予、普通角色消灭指令及随从光环不会作用于它。需要操作地标的牌必须声明 `TargetSpec(kinds=(CardType.LOCATION,), zones=(Zone.BOARD,))`，使用专用效果。冷却中的地标仍可被这些明确目标规则选中。

地标共享构筑、开局、手牌/牌库生成、费用报价、手牌操作及版本池元数据。打出使用 `PlayCard`，支付卡牌费用、指定场位，但不选主动能力的目标，也不执行主动效果；发布 `card_committed` / `location_placed` / `card_played`，不发布随从召唤事件。费用修正能影响打出，不能消耗在免费使用上。

## 使用、冷却与销毁

`UseLocation(player_id, entity_id, target_id=None)` 经过当前玩家、控制权、在场类型、正耐久、冷却、显式空间条件和 `use_rule` 校验，再通过同一目标谓词校验目标。`Game.legal_actions()`、`legal_targets()`、命令编解码和 `PlayerPort` 复用这些规则。地标的主动能力由 `CardDefinition.on_use` 声明；`requires_target` / `targeting` 只用于使用阶段。

激活扣一点耐久、设置 `location_cooldown=2`，在离场检查前捕获能力上下文，并发布 `location_activated`。每到控制者回合开始，冷却减一：自己的下一回合仍为一，再下一回合归零。对手回合不扣减。冷却不会禁用地标的被动触发或已支持的费用光环。

零耐久在激活检查点移出场位，再执行已捕获主动能力；因此最后一次使用可释放召唤所需格子。星港多于一点耐久且满场时不可使用，最后一点允许使用。地标销毁沿用不可变记录和能力反应队列，但发布 `location_destroyed`，不产生 `minion_died`、尸体或星舰组件贡献。印刷亡语可执行；当前反应顺序会先处理该销毁产生的亡语，再继续捕获的主动能力。上述详细顺序属于 R-037，后续必须校准。

`FinishLocation` 在剩余主动效果完成后发布 `location_used`。期间挂起的选择保存全部帧，继续时不会重复扣耐久或丢掉剩余效果；任何处理器失败仍原子回滚。不会把未实现的动态“地标作为伤害/治疗规则持有者”静默安装为无效能力，该用法明确拒绝并留待相应代表卡接入。

## 扩展指令与代表卡

[locations.py](../hs_sim/engine/locations.py) 提供：

| 指令 | 用途 |
| --- | --- |
| `PlaceLocation` | 效果放置地标，检查类型与场位，不触发出牌或随从召唤 |
| `ModifyLocation` | 有符号耐久调整，零值/负值进入统一销毁检查 |
| `RefreshLocation` | 清除冷却，保留耐久，用于提前开启 |
| `DestroyLocation` | 明确销毁地标，无伤害、无随从死亡计数 |

两条新增锁定记录仍保持 partial / internally_tested：

- **星港 `SC_403`**：二费、二耐久人族地标，使用时复用完整 `SC_403a/b/c/d/f` 五组件候选与公共召唤；没有删掉铁鸦或改成法术。
- **赤红深渊 `CORE_REV_990`**：一费、三耐久，使用时对随从造成一点效果伤害，再给予两点攻击。不是施法，不享受法伤，能选魔免随从；敌方潜行/免疫仍受共同目标限制。两段之间使用既有检查点，已死亡目标不再增益。

## 玩家观察与验证

公开地标显示类型、耐久和 `location: {cooldown_remaining, open}`，使用命令携带公开句柄。`open` 描述冷却/耐久状态，不保证存在合法目标或满足其他使用条件。新事件按显式白名单对玩家发布。对手手牌中的地标仍只显示牌背或此前已知身份；盲选手牌声明必须包含所有可在手牌中的类型，不能因地标身份泄漏合法动作。

[42 项专项测试](../tests/test_m4_locations.py) 覆盖主动与被动行为、角色隔离、共享场位、目标、全局费用、冷却、最后一次使用、自身亡语、显式销毁、早开/修复、构筑/开局、暗牌隔离、玩家命令、损坏存档、选择恢复和失败回滚。全量实际结果见项目状态。

```powershell
python -m unittest tests.test_m4_locations -q
python -m examples.use_starport
python -m hs_sim replay outputs/starport-replay.json --card-set representative
```

[真实卡示例](../examples/use_starport.py) 先打出并使用星港，击毁组件形成星舰，跨过冷却回合后保存，再通过玩家接口完成星港最后一次使用、加入第三个组件并发射。共十一动作、71 条事件，保存恢复与重算回放一致，摘要 `da84cfc56da09d6ed3f0d650f0de925881b51182e1d7ed0fe35014aab7440ff2`。

旧 schema 1～73 明确拒绝，外层 replay 仍为 1。地标特殊复制/转控/变形、任意冷却修改、自动激活及精确与各类亡语/移除交互仍需要对应公共契约与代表卡验收，未因本批通过而宣称全部覆盖。M4-01b 的英雄牌/雷诺/强化剂与发射历史已另通过内部验收；地标特殊规则门槛继续保留。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为use_starport.py：11动作/71事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 场上有序换面

当前公共接口已提供`LocationFaceReference.capture(state, entity_id)`与`AdvanceLocationFace(reference, next_card_id, source_id=None)`。前段版本号保存原M4历史接口；当前开发版本和执行事实以[项目状态](project-status.md)为准。这一接口已经存在，不应依据较早B4-N04调查重复建立地标换面模块。

引用固定原物理ID、控制者、印刷card_id、zone_epoch与entered_order。目标和后继必须是完整物理地标，未知定义或非法类型明确报错；原已离场、被销毁、换面或改变驻留身份的引用不得复活。最后一点耐久在原检查点离场后，已捕获主动主体和FinishLocation继续，后续换面只作过期处理。

成功换面保留物理ID、owner/controller、场位/入场顺序、耐久、冷却、用途和有效动态能力行。仅替换印刷卡面、原费用与印刷能力，并增加epoch；同面请求不更新行、不增加epoch或重置已消费能力。不按耐久推导所处阶段，也不通过DestroyLocation和PlaceLocation伪造保持身份。

`location_face_changed`采用专门玩家信息政策，原挂起上下文和引用有结构验证。原目标和已捕获主体继续按原接受上下文执行；下次合法操作采用新定义的目标与主动能力。现有源码及历史验证不等于所有真实主体/来源已适配，精确换面/冷却/最后耐久顺序仍待R-037/M6国服校准。
