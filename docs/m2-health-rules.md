# M2：伤害、治疗修正与替换

唤光长枪的双方吸血由有限原生接收者声明扩展本层同批恢复列表，两个原请求各自经过治疗规则；不新增数值层、死亡窗口或全局光环。来源归属、旧普通吸血及未国服校准边界见[契约](m3-lightcaller-lifesteal.md)。

真实原生伤害与攻击提供者仅扩展有限来源、嘲讽绕过和本体免疫条件，数值/目标/生命周期仍交原执行器。当前种族、占位和未实现克洛玛图斯来源边界见[契约](m3-native-health-attack-providers.md)，不能从登记数量认证正式标准支持。

显式玩家健康来源保存原物理事实与受益方，普通玩家效果默认保持原语义；逻辑伤害委托原健康层，下一真实对手期间复用原实例/费用/时钟。严格捕获、解码、玩家隔离和统一格式常量见[玩家健康来源契约](m3-player-effect-health-source.md)，实际进度与验收仅在两台账。

对应 M2-06。以下保留原阶段契约，其当时规则为 `prototype-v75` / `core-effects-v75`，snapshot schema 74，代表包 `representative-m5-v38`。本页是内部可执行契约，尚未完成国服目标补丁的官方时序校准。总体进度见 [项目状态](project-status.md)，范围与阶段见 [长期计划](roadmap.md)。

## 数据与模块边界

显式无限随从伤害另有[内部上限政策](m2-infinite-health.md)：只有typed无限请求设置同批临时numeric_limit，保留原防护/替换/吸血/历史；普通整数没有全局封顶。准确国服数值待校准，不能将客户端“∞”显示门槛当作伤害。

真实过量给英雄另有[一次SPELL预算分流契约](m2-excess-damage.md)：来源数值只算一次，按原随从生命分配后两份复用本层TARGET及同批结算。它不同于下述逐点随机分配，不增加第二套伤害执行器。

[health_rules.py](../hs_sim/engine/health_rules.py) 从批次开始时的状态准备不可变 `PreparedHealth`；[combat.py](../hs_sim/engine/combat.py) 计算圣盾、免疫、护甲和生命伤害结果；[resolver.py](../hs_sim/engine/resolver.py) 统一提交伤害、治疗、吸血及事件，并保留死亡检查和武器耐久责任。

`Heal` 增加显式 `HealingKind.EFFECT / SPELL / HERO_POWER`。`DamageKind` 保留原分类；不会仅凭来源牌是法术就自动把普通效果当作法术。`HealBatch` 与 `DamageBatch` 都代表一个准备、结算和死亡边界；连续返回两个单体指令仍有中间检查点。

随机分配已有两条明确路径。`effects.SplitDamage(player_id, amount, source_id, include_hero, kind)`用于非SPELL的`EFFECT/HERO_POWER/MINION_ABILITY`，每次按当前存活角色抽取并结算一点，再沿原解释器继续余量；死亡与待选可在点之间发生，空池尾部不继续抽样。`random_split_damage.RandomSplitDamage`则要求物理施法根，按其声明profile先确定整笔SPELL预算并保存接受/分配证明。它们不能互相冒充，也不能因后者只接受SPELL就推断其他来源缺执行器。两条路径的数值修正规则和精确窗口仍按各自明确政策及M6校准范围解释。

`CardDefinition.spell_school` 使用 `SpellSchool` 枚举，无派系为 `None`；目前明确表达奥术、火焰、冰霜、自然、神圣、暗影、邪能。只有法术定义能填派系。代表适配器显式映射本地 `SPELL_SCHOOL` 标签并拒绝未知值，没有从文字猜测。[官方 20.0 更新](https://hearthstone.blizzard.com/en-gb/news/23642550) 说明这七种魔法派系的引入；不据此证明当前完整卡池的派系数据或合法性。

## 规则表达

`HealthRule` 保存为 `AbilityInstance(kind='health_rule')`，可来自定义的 `health_rules`，也可通过 `GrantHealthRule(target_id, rule, source_id, expires_turn)` 授予。规则、来源、附件 ID 和到期状态进入快照、死亡记录与回放。

| 字段 | 用途 |
| --- | --- |
| `flow` | 匹配伤害或治疗 |
| `operation` | `ADD / SCALE / SET / CAP / PREVENT / REDIRECT / CONVERT` |
| `amount / denominator` | 加法/设值/上限操作数，或整数分数倍率；乘除后向下取整，禁止浮点 |
| `layer` | `SOURCE / TARGET`，区分来源端与承受端数值规则 |
| `source_relation / target_relation` | 相对于能力持有者的 `any / friendly / enemy / self` |
| `target_kinds` | 英雄、随从或两者 |
| `damage_kinds / healing_kinds` | 只填对应流的分类；空元组表示不限制 |
| `schools` | 限制来源法术派系，空元组表示不限制；若只作用法术伤害，还应明确 `damage_kinds` |
| `redirect_to` | 重定向到能力持有者、其友方英雄或敌方英雄；武器不能接收生命效果 |

原型支持英雄、随从和装备中的武器提供这些规则。存活及在场资格在批次开始时冻结；手牌、墓地和已经失效的来源不提供规则。沉默、复制、变形、回手、转控和到期继续使用公共生命周期机制；关系条件随持有者当前控制者解释。

示例：所有随从受到的法术伤害翻倍。

```python
from hs_sim.engine import CardType, DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule

rule = HealthRule(
    HealthFlow.DAMAGE, HealthOp.SCALE, 2,
    layer=HealthLayer.TARGET,
    target_kinds=(CardType.MINION,),
    damage_kinds=(DamageKind.SPELL,),
)
```

## 明确的原型处理顺序

1. 验证来源及显式类别。原目标已离开角色区域时跳过，不通过重定向重新激活失效目标。
2. 选第一条匹配的流转换规则，将伤害与治疗互换；每个包至多转换一次，互相相反的规则不循环切换。
3. 解析重定向链；匹配能力按附件 ID 排序。指向当前目标的规则忽略；一旦返回已经经过的目标，抛错并回滚整个动作，不静默丢失伤害。
4. 若最终为法术伤害，加入当前控制者的法伤。正常治疗不加法伤；吸血生成的恢复包再转伤害时，不重复加入已经计入原伤害的法伤。
5. 先来源层、后承受层；每层依次做加法、倍率、设值、上限、防止。同类按附件 ID 排序。加法不产生负数；明确防止会终止后续数值修改。
6. 按包顺序提交。伤害依次检查规则防止、零伤害、免疫、圣盾，再扣护甲和生命；治疗按缺失生命钳制。最终承受者决定承受端修正及护甲/圣盾，不在原目标与最终目标间拆分溢出伤害。
7. 全批主要包完成后结算固有吸血及其转换，随后发布事件、结算战斗武器耐久，再进入既有死亡/触发检查点。

同批中的来源被较早的包打到致命，不会撤销已冻结的修正；分开的效果会重新采集来源。两个包打同一圣盾时，第一包消耗圣盾，第二包可造成伤害。转换或重定向不会额外插入死亡检查点。

**这些优先级尚未官方校准。** 特别是转换后的法伤、倍率叠加、重定向相对原英雄的免疫/护甲/伤害上限、多个拦截者的优先级，都需在 M6 用目标补丁证据验证。当前关系/类型/派系筛选也不能代表任意卡牌条件；一次性替换、受伤量动态规则和选择目标仍需 M3/M5 扩展。

## 吸血与转换

吸血依据实际未被防止的伤害，仍包含护甲与过量伤害。它生成带有原来源和类别的恢复包，再走同一套治疗修正。因此法术伤害翻倍和法术治疗翻倍可以分别作用于吸血法术的两个阶段；治疗最终仍按缺失生命钳制。

恢复被奥金尼类效果转换为伤害时，转换产生的吸血伤害不能再次启动吸血。这个明确的机制护栏独立于工程步数预算。[官方 2017 年 8 月 8 日更新](https://hearthstone.blizzard.com/en-gb/news/20944006/hearthstone-update-august-8-8-8-2017) 说明奥金尼与吸血组合只触发一次；本引擎具体的来源继承、关键词、倍率和终局顺序仍属待校准契约。

生命费用、护甲费用、增加最大生命、设生命和消灭都不是伤害/治疗包，不经过本层。费用规则见 [费用与资源](m2-resources.md)。伤害经过本层及免疫/圣盾/护甲处理后，最终扣血进入独立的 [生命损失替换层](m5-health-loss.md)；生命费用和显式 LoseHealth 也可进入该层，但不会因此被当成伤害。

## 事件与扩展责任

`damage_dealt / damage_prevented / healed / healing_prevented` 保存基础量、法伤、修改后量、来源控制者、原目标、规则 ID、重定向路径、转换标志及派系。伤害结果额外保存护甲吸收量与生命伤害量。`health_effect_converted / health_effect_redirected` 明示替换过程；`lifesteal` 保留原伤害量及实际恢复量。

声明的 `Damage` 和 `Heal` 分别进入可替换的批处理入口，原生批处理共同调用 `settle_health_batch`；转换和固有吸血留在本批内，不重新调度成独立外部效果。通常通过 `HealthRule` 扩展数值和替换，避免更换批处理器后只改变普通治疗却漏掉吸血。自定义底层处理器须明确保留整体边界、吸血护栏及 `CombatExchange` 的武器消耗责任。

## 代表卡与验证

新增先知维伦 `EX1_350`、奥金尼灵魂祭司 `EX1_591`、莫尔葛工匠 `BT_733`、博尔夫·碎盾 `AT_124`、活化铠甲 `LOE_119`、治疗之触 `CS2_007`、大地之环先知 `CS2_117`、神圣新星 `CS1_112`。全体 70 条代表记录都维持 partial / internally_tested。

神圣新星暂按“敌方随从伤害批次，再友方角色治疗批次”执行，两个目标列表在行为展开时固定。伤害死亡及亡语新造角色是否应进入后续治疗列表，连同其他特殊时序保留为 M6 问题，不能据基础场景通过声称全交互正确。

M2-06 于 2026-09-24 的历史验证（v8）：**449 项全量回归通过**，包括 [45 项本层组合测试](../tests/test_m2_health_rules.py)、[62 项代表卡测试](../tests/test_representative_cards.py)；已有武器、资源、属性、死亡、快照和回放回归保留。当前 schema 74 严格保存嵌套规则与结算帧，拒绝旧 schema 1～73；外层 replay schema 仍为 1。

```powershell
python -m unittest discover -s tests -q
python -m hs_sim simulate examples/scenarios/health-rules.json --actions examples/actions/health-rules.json --card-set representative --replay-out outputs/health-rules-replay.json
python -m hs_sim replay outputs/health-rules-replay.json --card-set representative
```

[组合场景](../examples/scenarios/health-rules.json) 和 [操作序列](../examples/actions/health-rules.json) 演示：维伦加倍自伤，治疗之触被奥金尼转换、被博尔夫承接并受到莫尔葛修正；沉默奥金尼后再次治疗；下一回合应用过载。6 次操作、27 条事件，双方英雄最终 30 血，玩家 1 可用法力 9、锁定 1；博尔夫承受 32 伤害后死亡，敌方获得 1 尸体。v8 历史回放摘要 `7ea5c7c73f779ebc3bfd207783e1d40353a14156c9d08f4808df26fc6e3714ac` 一致。

M3-01 的挂起选择/结算帧已内部验收，见 [选择契约](m3-choices.md)；M3-02 普通开局也已内部验收，只读信息视图已内部验收，受限玩家动作也已内部验收，下一主项为 M3-03b 版本化候选池。M0 地区部署/完整合法池、M5 特殊规则及 M6 集中校准仍未完成。

当前学派限定的原生法伤在原提供者查询进入普通包及一次随机分配总额，见[独立学派法伤契约](m2-school-spell-damage.md)。HealthRule的原按包修正含义保持，不冒充法伤提供者；精确CN政策待校准。
