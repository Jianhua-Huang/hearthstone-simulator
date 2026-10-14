# 学派限定法术伤害

本机制扩展原法伤提供者和伤害准备，不另建伤害执行器。实际进度、验证与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 声明和公共查询

```python
CardDefinition(
    'BAR_048', '布鲁坎', CardType.MINION, cost=4, attack=5, health=4,
    spell_damage=3, spell_damage_schools=(SpellSchool.NATURE,),
)
```

`CardDefinition.spell_damage_schools` 默认空元组，表示原不限学派的法伤。非空为严格、唯一、不可变的 `SpellSchool` 元组，只支持正数、原生普通非融合随从。原英雄通用法伤和空范围的授予保持；不新增学派限定的任意/存储卡授予、玩家长期来源或其他条件矩阵。

原 `AbilityInstance(kind='spell_damage')` 保存同名字段。非空要求印刷来源、可沉默、未消费、无期限、无磁力来源，完整声明及原数量验证覆盖当前、死亡和捕获状态。拒绝剥离选择器、改变金额或借用其他卡面；原普通授予可以作为独立空范围附件存在。

纯 `spell_damage_sources(state, player_id, registry, school)` 返回原顺序的合格提供者及金额，`spell_bonus` 对相同结果求和。来源沿原英雄/己方战场、active、存活及未标记死亡政策。空选择器总是匹配；非空只匹配传入学派，每个物理附件贡献一次。

实际法术始终显式传入当前/捕获的学派；`None` 表示没有学派，只获得通用法伤。省略参数保留原无学派输入的聚合标量查询，汇总合格提供者，不用于给无学派法术加限定法伤。精确通用条件查询政策仍待国服校准。

## 两种伤害入口

普通 `Damage(kind=SPELL)`、群体及原健康准备读取同一个提供者查询。每个原伤害包获得对应法伤；同批来源被前一包消灭时保留原批次准备结果。显式普通效果伤害、战斗、技能、正常治疗继续使用既有分类和规则，不因来源卡有学派就当作法术伤害。

`RandomSplitDamage` 在原接受窗使用该查询捕获完整提供者和总额。基础 2 点加自然法伤 3 点成为 5 个单点包，每包不再次加 3。记录保留原学派、原能力完整字段、金额和完整原状态证明；来源在后续选择被沉默不重写原预算。`SplitBudgetQuote` 拒绝不匹配学派的原贡献，原恢复、RNG、包序和当前候选处理保持。

`HealthRule(..., schools=...)` 的按包数值修正仍有其原含义；它不冒充法伤提供者，也不向一次随机分配预算贡献。

## 生命周期和信息

原沉默、死亡、转控、变形、回手重放、当前/基础复制、休眠/唤醒和回合继续复用附件生命周期。原生没有期限，普通回合末不会移除；不保存第二套法伤缓存、实体字段或玩家计数。选择恢复、克隆、回放和异常回滚沿原解释器。

当前 `prototype-v201 / core-effects-v195 / schema189` 拒绝旧 1～188，观察74/命令11/replay1保持。新定义字段改变完整注册表指纹，能力字段进入严格显式快照和自动 FrameCodec；缺失/非法学派及陈旧声明明确拒绝。玩家使用原公开卡面、角色和结果视图，不能获得内部能力、贡献证明、全知状态或随机状态。

## 必要代表与规则依据

仅隔离适配 `BAR_048` 布鲁坎，4费5/4萨满传说，自然法术伤害+3。[完整原始证据](../data/support/school-spell-damage-basics.json)中 `SPELLPOWER_NATURE=1` 是标签存在值，不能把它当作+1金额。TSC_635和GDB_304只保留真实学派/后续授予来源线索，不接其主体或开发组合。

[官方贫瘠之地公告](https://hearthstone.blizzard.com/en-gb/news/23622608)描述七学派及布鲁坎印刷效果；[官方卡库](https://hearthstone.blizzard.com/en-us/cards/63074-brukan?set=forged-in-the-barrens)索引提供关键文字，直接页只动态外壳。[证据分级](../outputs/school-spell-damage-basics-20261010/official-evidence.json)不把历史公布或索引当作当前国服合法池与时序认证。原数值层、批次/随机预算接受和通用查询细节保留为 M6 待校准政策，其他真实来源与完整 U44 仍开放。
