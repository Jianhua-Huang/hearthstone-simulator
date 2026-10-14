# M5-13c：出牌前抉择与合并抉择

**2026-10-09撤除边界：**无依据的8类专用组合已从代码、专项测试及当前必做队列移除。普通抉择/兼得、实体预选及真实历史继承继续保留；磁力、裂变、同一静态奥秘/任务/持续载体及独立印刷战吼/连击组合在注册时明确拒绝。ChooseBranch没有独立价格字段，ChooseOneSpec没有安装政策。旧实验与内部证据见[反向审计](mechanism-combination-audit.md)，当前开发版本与实际验证见两份主台账。

原批次提供出牌/技能激活前的分支声明和合法性检查。`prototype-v75` / `core-effects-v75`、snapshot schema 74、player-view-v44、player-actions-v7、representative-m5-v38，外层 replay 仍为 1。旧 schema 1～73 明确拒绝，没有隐式迁移。本文为内部原型契约；国服精确规则另列 R-112。

## 声明与动作

`ChooseBranch(id, label, behavior_id, targeting=None, target_rule='any_entity', requires_board_space=False)` 声明一个分支。`ChooseOneSpec(branches, combined)` 至少有两个普通分支，且必须显式定义合并分支；所有分支 ID 唯一。例：

```python
from hs_sim.engine import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, PlayCard

definition = CardDefinition(
    id='example_choice', name='分支示例', kind=CardType.SPELL, cost=2,
    choose_one=ChooseOneSpec(
        branches=(ChooseBranch('draw', '抽牌', 'example.draw'),
                  ChooseBranch('armor', '护甲', 'example.armor')),
        combined=ChooseBranch('both', '兼得', 'example.both'),
    ),
)
# 行为 ID 须在注册表冻结前注册；主体由共享分派器安装。
game.apply(PlayCard(player_id=1, entity_id=card_entity_id, branch_id='draw'))
```

普通主动随从、法术、主动英雄技能可使用声明。英雄技能用 `UseHeroPower(..., branch_id=...)`；玩家命令使用公开字段 `branch`。卡牌/技能可见信息仅提供分支 ID 和标签，行为 ID 不进入玩家 DTO；对手隐藏手牌不泄漏分支。`Game.legal_targets(entity_id, branch_id=...)`、合法动作、执行校验使用同一分支目标域。存在不支持的私有目标条件时玩家接口明确拒绝，不静默遗漏分支。

分支选择、目标、场位和费用在支付前验证；普通牌不接受额外分支，抉择牌不接受缺失或未知分支。选定分支以外的目标要求不限制当前动作。无目标、必须目标、存在才选目标以及分支专属场位要求遵循共同目标契约。这里的 `requires_board_space` 是显式声明，不能从效果名称猜测召唤是否应当阻止出牌。

分支没有独立费用修正字段；当前使用主体的共享报价和支付规则。特殊资源消耗或预备步骤仅在具体真实卡需要且现有公共模块不能表达时再补契约。

## 捕获、合并与生命周期

`PlayRecord`、`SpellCastRecord`、`HeroPowerRecord` 保存 `branch_id`。手动动作在支付/提交前捕获分支，后续反制、目标替换、重复效果、回溯与暂停恢复都读取冻结记录。提交反应中获得或失去合并能力不改变已经提交的分支。目标替换使用该分支的目标域；只支付和计一次出牌。

`CardDefinition.choose_both=True` 在随从上安装印刷能力；`GrantChooseBoth(target_id, source_id=None, expires_turn=None)` 授予可沉默、可到期的附件。按活跃场上来源的当前控制者决定是否只能选合并分支；多个来源不重复执行。控制变化、休眠、沉默、变形、回手、当前/基础复制复用公共生命周期。已致死但尚未过死亡检查点的来源暂时仍生效，此窗口属于 R-112。

合并分支必须独立声明完整目标域、执行顺序和效果，不自动拼接两个回调。这样可以表达伤害分段、抽牌时点、变形主体等差异；正确卡文适配仍需证据和测试。分支执行复用正常效果队列及死亡检查，不能绕过统一结算。

## 自动来源、重复与内部选择

| 入口 | 分支策略 |
| --- | --- |
| 手动打出、手动技能、回溯重试 | 动作必须明确分支；重试沿用原动作 |
| 同次法术的重复遍、保留多种结果 | 沿用原激活记录，组合能力途中变化不重新选分支 |
| 自动/存储法术、间接技能 | 可显式指定合法分支；否则普通分支使用对局 RNG 随机选择，有合并来源则选唯一合并分支 |
| 抽到时施放、历史重施 | 是新激活，重新读取当前组合政策并捕获分支 |

自动入口先选分支再找目标，不能通过排除“没有合法目标”的分支改变随机概率。所选分支失败时沿用共享施法/技能失败记录；单个合并选项不消耗分支随机数。显式分支与当前组合政策冲突明确报错回滚。这是原型自动来源政策，来源专属的玩家预选、继承分支或其他策略仍需 M5 扩展，并经 M6 校准。

自动效果的 `choices` 参数管理的是**分支效果内部**的发现等选择，不管理本节的激活前随机分支。`RequestChoice` 和 `ChooseInOrder` 继续处理结算中的暂停；`RequestChoice.repeat_key` 仍可显式缓存内部选项。滋养已不使用这个缓存，也不生成模拟的 `SelectChoice` 动作。分支主体中的真正选择仍能暂停，帧、记录、RNG 和失败回滚保持一致。

## 代表与验证

必要代表为已存在的滋养 `EX1_164`，以及新增愤怒 `EX1_154`、战争古树 `EX1_178`、范达尔·鹿盔 `OG_044`。滋养合并分支先获得两个可用晶体再抽三张；愤怒合并分支按 3 点、1 点两个伤害指令后抽牌；古树合并分支获得 +5/+5 与嘲讽。分段死亡检查和组合时点仍待国服校准，不宣称真实卡完整支持。

原批次 62 项[专项](../tests/test_m5_choose_one.py)覆盖普通/合并目标、费用/场位、自动来源、变形、控制与附件生命周期、主/额外技能、反制/目标替换、重复/回溯、暂停/恢复、事务/终局以及玩家私有边界。重复施放 56 项和代表卡 70 项回归已通过；最终全量3673项（512.906秒）、55示例及36项台账检查通过，见[项目状态](project-status.md)和[全量日志](../outputs/v72-full-tests.txt)。

```powershell
python -m unittest discover -s tests -p test_m5_choose_one.py -v
python -m examples.choose_one
python -m hs_sim replay outputs/choose-one-replay.json --card-set representative
```

[人工场景](../examples/choose_one.py)通过玩家接口完成鹿盔、古树、愤怒和滋养组合，5 动作/28 事件，中途普通边界保存恢复与完整回放一致，摘要 `e77982d9e80569521b083f8ec5ca9b84c75aa86dc35ac0494585d4f893bd7277`。它不证明国服构筑合法性。滋养双牌示例现在 2 动作/10 事件；希奈丝特拉示例 5 动作/33 事件，分别减少旧的结算后选择动作和请求/选择事件。真正挂起恢复由专项及其他选择示例继续验证。

## 证据和保留范围

冻结卡文来自本地源及[候选摘录](../outputs/m5-13c-choose-one-candidates.json)：206 条 CHOOSE_ONE 标签记录、102 条可收藏标记、8 个调查根及一层引用。这些计数不是合法池或已支持卡数。[2017 官方更新](https://hearthstone.blizzard.com/en-gb/news/20944006/hearthstone-update-august-8-8-8-2017dlc7xql)支持鹿盔对卡牌和英雄技能的组合基础定义；[官方 HCT 报道](https://hearthstone.blizzard.com/en-us/news/21363149/the-bar-is-raised-on-day-2-of-the-hct-world-championship)记载了转控鹿盔后滋养获得两种效果。历史资料不能证明当前国服具体窗口。

R-112 保留：提交前捕获、来源在提交反应中变化、致死来源检查点、自动分支先于目标及失败概率、分段死亡/抽牌/变形顺序、多技能、重复/回溯和历史新激活的国服时序。

原批范围记录：当时保留玩家长期/下一次合并、来源预选/继承、分支费用和组合声明，并拒绝抉择与磁力、裂变、奥秘、任务、持续效果、被动技能、choice-only或主体条件目标等混合形状。这是当时的接口限制，不自动证明这些组合都是目标炉石的缺失机制；具体必要性以[2026-10-09反向审计](mechanism-combination-audit.md)及两份主台账为准。

战吼身份及重复的旧顺序保留为历史；当前下一项以[机制清单](mechanism-backlog.md)的独立基础队列为准，不另开组合开发。正式池 M0、集中校准 M6、批量卡牌 M7 顺序保持。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为choose_one.py：5动作/30事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。

## 当前物理生成来源补充

`generated_choose_one.py` 现连接四种真实物理历史整牌 profile 的随从抉择。安装前接受完整原合并来源、分支及RNG；安装/入场后普通目标和各授予主体分别接受，实际分支dispatch不制造出牌/施法记录。重复与保留结果沿原分支，后一实际child从新局面接受，详见[公共分支契约](m5-generated-choose-one.md)。该来源批次格式 prototype-v147/core147/schema142，实际证据仅由两份最新台账维护。

原批验收不被冒作当前全量。已有战争古树/鹿盔只作必要实际卡路径验证，没有新增正式适配。抉择根额外独立印刷战吼/连击声明已撤除，见[历史撤除说明](m5-printed-choose-one-bodies.md)；普通抉择根保持，现有真实入场授予按自身来源权限处理，不作为扩张组合的要求。玩家长期/有限次合并另见公共政策，实体预选/显式继承另见物理配方契约；分支定价已撤除，特殊来源及组合需求按具体真实卡后置，国服校准与正式池继续开放。


## 玩家长期和有限次数政策

[玩家政策公共层](m5-player-choose-both.md)补充来源独立的长期、下一次和多次合并，以及显式种类/来源、自然到期、一次消费和原接受证明。场上来源仍按R-112，不把玩家政策ID混成场上附件。手动、自动施法/抽牌/历史、四物理profile和技能沿各自真实窗口；重复和保留结果不另扣用途。该玩家政策引入批次为prototype-v147/core147/schema142、观察61；普通抉择沿主体共享报价和原付款，不提供分支价格字段，特殊继承来源和根按真实卡需求处理。

## 物理预选与显式继承

[独立模块](m5-choose-branch-state.md)保存来源受限的实体预选，在纯查询和实际根接受时组合场上/玩家政策。复制、重置和兼容回溯明示继承，实际原历史记录可由RecastSpell及四物理profile显式传递分支。已接受分支及一次支付保持，新的真实根按自己的窗口重新接受。不同分支定价已撤除；其他特殊来源按具体真实卡需求后置，本补充不宣称整类抉择已完成。

## 共享付款与已撤除的组合接口

普通抉择各分支沿主体共享报价和一次实际支付，不提供ChooseBranch.cost、installation_policy或裂变分支映射。磁力、裂变、同一静态奥秘/任务/持续载体及额外独立印刷战吼/连击根仍在注册时拒绝。

旧[分支定价](m5-choose-branch-costs.md)、[磁力](m5-magnetic-choose-roots.md)、[裂变](m5-shatter-choose-roots.md)、[长期载体](m5-long-term-choose-roots.md)及[持续安装](m5-ongoing-choose-roots.md)页面只是已撤除历史入口，不能作为现行接口或基础机制缺口。

普通兼得、玩家合并政策、物理预选及真实历史继承保持；已有批量/整牌来源范围见[继承契约](m5-history-branch-replays.md)和最新台账，不附带已撤除的价格或安装政策。特殊授予、producer和跨机制需求按后续真实卡处理，不穷举组合。
