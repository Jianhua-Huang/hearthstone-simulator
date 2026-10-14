# 上个本人回合元素条件的固有费用

实际验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本页在[原条件费用接口](m5-intrinsic-costs.md)增加固定条件，不新增机制模块或任意表达式。

```python
CardDefinition(
    "TRL_313", "灼烧", CardType.SPELL,
    cost=4, spell_school=SpellSchool.FIRE,
    intrinsic_costs=(IntrinsicCostSpec(
        set_to=1, condition="previous_owner_turn_elemental",
    ),),
    # 普通法术主体与随从目标继续由已有行为及 TargetSpec 声明。
)
```

`previous_owner_turn_elemental`固定查询报价玩家最近已关闭本人区间的 `PlayedTypeQuery(MINION, ("elemental",))`。查询对象独立于被定价牌自身的种族或学派；原默认 `previous_owner_turn_type`仍按本牌印刷种族或单学派查询，没有改为元素条件。两条件共用 `owner-turn.latest-closed-v1`及`cost.intrinsic.before-local-v1`。

## 窗口与匹配

查询沿原[本人回合和冻结提交卡面](m5-owner-turn-history.md)：保存完整所选区间和所有对应随从提交的 true/false 行，再聚合 bool。多个元素仍是一个条件；空的最近已关闭区间不会回退到更早匹配区间。场景初始、开局前和当前尚未关闭区间不冒作上个本人回合；额外本人区间和跳过调度沿原实际时钟，不按全局奇偶推断。

当前回合打出元素不能替换所查询的上个区间。报价按原完整状态接受，后续原牌身上的变形、控制转移或死亡不改变冻结印刷提交。其他玩家提交、非本人区间的内部出牌、召唤和自动 CAST不会被移入所选本人随从行。

所选区间全部候选先校验，后面未知随从种族不能被前面的 true 或零金额隐藏；未知明确报错。所选区间以外的较早未知不扩大原最近区间查询的未知范围。已知空不匹配，原 `all`对非空种族仍匹配。

最近已关闭区间和原提交接受时点是沿用的内部政策，精确国服时序仍待校准。[本地完整灼烧原行](../data/support/previous-owner-elemental-cost-basics.json)证明本牌有上回合元素费用条件及普通伤害主体；[官方卡库入口](https://hearthstone.blizzard.com/en-us/cards/50122-scorch/)本次仅返回导航，不能据此声称已取得官方文字或细窗口验证。

## 原费用与证明

条件为真时执行原 `IntrinsicCostSpec`操作，灼烧用 `set_to=1`。阶段仍先于局部及外部费用，沿原支付账户、一次付款、出牌、选择和回放管线；等待不重价，不重复付款。条件为false保留原 base，不给当前新事件补判。

完整原窗口重取原查询和操作；保留历史证明继续用原 boundary、冻结区间、完整 true/false 行和原付款。其末尾核对按 `selected.query.kind`选择原提交，而不是被定价牌的类型；旧按本牌类型的条件两者本来相同。原签名/来源边界保持，紧凑历史不是未签名存档的独立来源认证。

声明和保存阶段均拒绝不同条件混用，以及新元素条件同时搭配另一固有数量公式。只增加有限输入，未开放自由种族、任意谓词、条件矩阵或授予能力。已有同一条件的有序标准费用操作保留。

## 种族标识与代表

现有生产 `metadata_from_record`将CARDRACE18解释为小写 `elemental`；匹配本来按精确字符串进行。本页固定查询、[连续元素数量费用](m3-player-elemental-streak-costs.md)及必要CS2_118/WW_025隔离声明统一使用该已有标识。没有修改全局元数据、种族匹配、`all`规则或原raw/pin。

必要TRL_313隔离适配为4费法师稀有火焰法术，目标是场上任一合法随从，原 `Damage(..., kind=SPELL)`造成4点法术伤害，费用命中时设置1。SPELL_SCHOOL2按原生产学派表解释为FIRE，不能解释成FROST。支持文件pin为`deba86cbb9b3087114ccec023d363e6c4238fb8a82393daf21e082d4252af740`，只复用必要CS2_118普通元素，没有漏接灼烧主体或增加生产整池覆盖。

## 兼容性与私有信息

引入时prototype-v223/core-effects-v217；schema207布局、旧1～206拒绝、观察74/命令11/replay1及生产代表64/合成3保持。旧内核/效果版本明确拒绝，不能只因schema数字相同而重标旧快照。

没有新模型类型、声明/状态/存档字段、Effect、事件、动作、回合/出牌/付款执行器或计数缓存。新条件通过原严格字典和typed帧往返，原玩家接口只给允许观察的费用，不交付完整条件行、原历史或隐藏卡面。正式池、国服校准和完整基础范围继续分别维护。
