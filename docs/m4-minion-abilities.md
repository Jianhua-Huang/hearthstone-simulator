# M4 有限次随从能力与泰坦

对应原始 M4-02b 批次：`prototype-v75` / `core-effects-v75`、snapshot schema 74、`representative-m5-v38`，玩家观察 `player-view-v44`、动作协议 `player-actions-v7`。本批建立有限次能力数据模型，首先实现泰坦的激活规则；不表示所有场上额外能力或全部泰坦卡已经支持。整体进度与国服验收目标见 [项目状态](project-status.md)。

## 声明、实例与玩家操作

`CardDefinition.activated_abilities` 保存不可变 `ActivatedAbilitySpec` 元组。每项有稳定 `id`、纯行为 `behavior_id`、可选展示描述 `card_id`、目标声明、使用条件和场位条件。入场时安装为独立 `AbilityInstance(kind='activated')`，每个实例保存自身 `consumed` 状态；卡牌定义不保存对局中的使用次数。

泰坦声明必须是带 `Keyword.TITAN` 的普通随从，恰有三个不同能力 ID；[古神独立基础](m4-old-god.md)复用同一模型，以四个能力和首次免费机会声明互斥政策。注册表验证行为、条件及描述引用；展示牌必须是 `choice_only`，不能生成物理实体、构筑或施放。不能通过单独 `GrantKeyword(TITAN/OLD_GOD)` 生成没有能力的载体。其他激活策略、任意授予/刷新能力留待实际卡牌需要时扩展。

宿主动作是 `UseMinionAbility(player_id, entity_id, ability_id, target_id=None)`；`Game.legal_actions`、校验与执行共用能力和目标规则。`Game.legal_ability_targets` 可查询指定能力的目标域。玩家使用固定座位接口，例如：

```python
port = game.for_player(1)
listing = port.legal_actions()
command = next(a for a in listing['actions'] if a['type'] == 'use_minion_ability')
result = port.submit({'revision': listing['revision'], 'action': command})
assert result['accepted']
```

命令形如 `{"type":"use_minion_ability","minion":"e7","ability_id":"TTN_903t3","target":null}`，不含内核附件 ID 或可篡改座位。自定义目标/使用条件仍必须声明玩家可见性；不支持的全知条件明确拒绝。随从 DTO 的 `minion_abilities` 仅列 `ability_id/card_id/used`，日志的 `minion_ability` 保存本次所选能力，来源离场后仍可辨认。

## 激活与战斗规则

泰坦入场或唤醒当回合可使用能力。每项能力一次，与普通攻击共享 `attacks_this_turn`；通常一回合一次，已有风怒提供两次。冻结阻止主动使用。能力免费，不走施法、战吼、普通出牌支付或 `card_played` 路径。

仍有未用能力时禁止普通攻击，即使剩余能力没有合法目标。全部用完后遵循普通攻击条件和剩余次数；泰坦保留入场即可行动资格。沉默移除泰坦及其能力，但不返还已经消费的次数；刚入场就被沉默的随从重新受普通召唤失调约束。公共行动预算已支持超级风怒的四次上限；能力仍各自只能消费一次。

目标按能力自身 `TargetSpec` 校验，来源仍是随从：嘲讽不约束技能目标，魔免不阻止随从能力，敌方潜行和休眠遵守共同目标保护。能力伤害显式使用 `DamageKind.MINION_ABILITY`，不加法术伤害，沿用剧毒、吸血与公共伤害规则。实际造成伤害时移除来源潜行；非伤害能力和完全防止的伤害保留潜行。

原批次新增 `ForceAttack(attacker_id, defender_id)` 供效果驱动的战斗使用。当时范围是活跃随从攻击敌方角色，不受主动攻击的冻结、泰坦能力余量或当回合次数限制，也不消费这些次数；共用战斗伤害、反击和死亡检查。失效目标跳过，英雄攻击者明确拒绝。友方强制战斗、特殊禁攻规则与更多来源当时并未纳入该批。现有公共执行器另有显式友方随从关系，见[关系专项](../tests/test_v123_forced_relations.py)；本轮不扩展该路径。

基础方向来自 [官方泰坦 FAQ](https://hearthstone.blizzard.com/en-us/expansions-adventures/titans)；复制、沉默、目标、强制攻击及伤害细节参考 [官方开发者说明首帖](https://us.forums.blizzard.com/en/hearthstone/t/dev-talk%E2%80%94totally-titans-all-about-the-new-keyword/109540)，未将评论区回复当作证据。这些历史说明不等于国服当前补丁的局面校准。

## R-042：使用、结算与冻结窗口

原型先消费选中能力和一次行动机会，再发出 `minion_ability_started`；捕获的行为经公共解释器执行，结束时由独立 `FinishMinionAbility` 发出 `minion_ability_used`。中间等待选择会保存剩余帧，不重新消费能力。完成事件保存初始能力描述和控制者，来源之后死亡/沉默不会把捕获中的效果自动改成另一能力；只有完成时仍有效的场上触发能响应。

当前冻结期限判断加入泰坦行动机会，但没有逐一模拟未来目标可用性。零攻击泰坦仍可使用能力；目标改变、冻结施加/消除、强制攻击中途转控、伤害显形与其他反应的精确窗口仍需国服校准。内部用例表达当前契约，不宣称这些复杂窗口已经获得官方实测确认。

## R-043：生命周期和后续效果

| 操作 | 当前契约 |
| --- | --- |
| 当前状态复制到战场 | 保留能力使用状态，新实体有自己的行动机会 |
| 基础复制、复生/重新召唤 | 安装印刷能力，三个能力重新可用；复生继续遵循 1 血规则 |
| 回手/洗回、复制入手再打出 | 按共同区域重置表重新安装印刷能力 |
| 再休眠/唤醒、控制权转移 | 保留已使用能力，准备度/回合次数共用既有规则 |
| 沉默/变形 | 通过附件生命周期统一移除或重建，不能残留旧能力 |

特殊复制、诺甘农的能力增强、萨格拉斯传送门绑定和阿古斯费用能力等需要各自代表卡和扩展契约，尚未接入。一般实体复制通过不代表所有泰坦自身效果完整。

`DrawToHandLimit` 在执行时冻结当前手牌空位数，随后返回共同 `Draw`，使用 `Ruleset.max_hand`；空库按每次抽牌处理疲劳。期间抽牌触发改变手牌数量的精确处理仍待校准。恢复法力和恢复英雄生命继续走既有资源/治疗原语，保留转换、倍率等交互。

随机发现/生成的静态池根据独立元数据排除泰坦，发生在检查候选是否有可执行适配之前；这是明确规则排除，不是偷偷删除未知牌。区域检索、从牌库抽取和显式召唤不受此过滤。未来进化等其他生成路径仍需单独接入。

## 代表卡、恢复与验证

本批冻结五条真实记录：艾欧娜尔 `TTN_903`，三项能力描述 `TTN_903t/t2/t3`，以及 `TTN_903t4` 衍生物。三个能力分别抽至手牌上限、恢复英雄生命、刷新法力；艾欧娜尔在自己的能力完成后召唤 5/5 嘲讽随从。满场、来源死亡/沉默、疲劳与公共治疗交互有内部验证。来源与单条指纹进入 [代表台账](../data/support/m1-representatives.json)，共 269 条真实记录，其中十二条是非物理描述（三个协议、三个泰坦能力、两个任务线阶段、四项灾变），另有一个测试英雄；完整池分母仍未知。

快照保存能力声明、消耗状态、行为引用及等待选择的完成帧，严格拒绝旧 schema 1～73。回放外层仍为 schema 1；规则、效果签名与内容指纹必须匹配。非法目标、条件异常与效果失败按既有事务回滚，包含能力消耗、事件、玩家知识和 RNG。

[54 项专项测试](../tests/test_m4_minion_abilities.py) 覆盖次数/目标、风怒/冻结、沉默/复制/复生/休眠、伤害/潜行、强制战斗、艾欧娜尔、玩家信息、挂起恢复、回滚与严格编解码。v23 批次全量 **1,076 项通过（64.709 秒）**，当时 M4 共 342 项内部用例；不作为官方一致率。

```powershell
python -m unittest tests.test_m4_minion_abilities -q
python -m examples.use_titan
python -m hs_sim replay outputs/titan-replay.json --card-set representative
```

[艾欧娜尔示例](../examples/use_titan.py) 全程通过玩家命令，完成三能力循环；8 次动作、36 条事件，中途存档恢复与完整重算回放一致。任务/任务线及进度模型已在 [任务契约](m4-quests.md) 内部验收；下一项持续目标和玩家长期效果，之后扩展奥秘；M0 完整池/热修、M5 特例、M6 国服校准和 M7/M8 全量覆盖继续保留。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为use_titan.py：8动作/38事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 2026-10-25 攻击限制与明确的主动技能限制

原 `cannot_attack` 只限制普通攻击，不自动禁用随从主动技能。[官方泰坦开发者完整首帖](https://us.forums.blizzard.com/en/hearthstone/t/dev-talk%E2%80%94totally-titans-all-about-the-new-keyword/109540)末尾问答明确把烦人的粉丝与技能动作区分，不能只读前半“用技能替代攻击”便推导全部禁攻都限制技能。原泰坦一般禁攻、条件场面禁攻及绑定来源失效三项内部测试保持原代码和预期。

增加有限政策模式 `cannot_attack_or_use_minion_abilities`，明确同时禁止主动攻击和 `UseMinionAbility`；与原攻击次数、仅禁英雄目标和攻击禁令分别查询。条件、来源驻留及印刷许可仍交原 `current_policies`，没有另建状态账户或结算器。原印刷禁攻许可只可解除原 `cannot_attack`，不解除这种额外行动禁令。古神首次免费机会在此门禁之后判断；零攻击、嘲讽、召唤失调及攻击目标资格不能被误套到主动技能。

真实当前生产者只有诅咒之链对应的既有 `ChangeControl.cannot_attack_this_turn` 路径：原瞬时控制、归还附件与期限不变，以同一来源/本回合到期的政策表达主动技能限制。先安装该政策，再在原刷新器重绑冻结时钟，然后发出原授予/转控事件；不让冻结机会查询漏看刚安装的禁令。其他控制路径及普通攻击禁令保持。冻结仍沿既有“捕获丢失行动机会”的内部时钟政策；该复杂边界未当前国服校准。

外部 `ChooseFamilyAbilities`/`TriggerFamilyAbility` 不因场上古神不能主动行动而被禁止，也不消耗其物理技能/免费标记/攻击次数；强制攻击执行器未改。真实问题来自[诅咒之链夺取克苏恩后的直接报告](https://www.reddit.com/r/hearthstone/comments/1xbkagb/error_when_stealing_opponents_cthun/)，只保存了解析网页观察（直接HTTP403），不是当前国服37.0实验或官方裁定。完整官方历史首帖及七张完整原行绑定于[来源包](../data/support/minion-action-prohibition-v1.json)。规则签名为 `core-effects-v731`；结构schema587及状态/Effect/命令/观察形状不变，只增加原有限模式的合法值。实际执行及校准状态仅在两份原台账维护。
