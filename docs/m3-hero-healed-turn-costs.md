# 本回合英雄被治疗的有限固有费用

```python
CardDefinition(
    "ICC_700", "开心的食尸鬼", CardType.MINION,
    cost=3, attack=3, health=3,
    # 完整原始元数据另行提供，不省略种族、职业和稀有度。
    intrinsic_costs=(IntrinsicCostSpec(
        set_to=0, condition="hero_healed_this_turn",
        history_profile_id="healing.hero-this-turn-v1",
    ),),
)
```

条件只读[实际治疗历史](m3-healing-history.md)，按原报价玩家、目标英雄、当前全局回合及 `healed > 0` 判断。治疗来源可以是另一玩家或未知来源；随从治疗、另一玩家英雄、满血零恢复、被阻止、治疗转伤害和属性增加不满足。伤害转换为实际治疗及吸血沿原最终治疗结果判断。已接受的过去回合报价不随新回合重价。

`HeroHealedTurnMatch`保存原 player、turn、action、next_healing_id、完整全部冻结治疗行和聚合 bool，包括不匹配行及零行。它进入原 `IntrinsicCostStageFact.condition_facts` 的有限类型分支；原 Stage 字段布局保持，没有第二历史、状态缓存、卡牌字段或费用执行器。未知 condition/profile、不同条件混用、其他固有数量公式及未审查类型/融合声明明确拒绝。新条件目前接受普通物理随从；其他真实类型按需要审查。

原 `cost.intrinsic.before-local-v1` 阶段及有序 `set_to` / `delta` / `minimum` 操作、局部和外部费用、付款账户、选择、复制、移区及普通实体生命周期共享。完整原窗口重新捕获全部治疗行；保留历史要求原有序前缀一致，并允许同动作的后来治疗和后续回合推进。早于报价动作的缺失行明确拒绝；紧凑前缀不提供未签名存档的来源真实性认证，原支付/接受状态另作完整原窗绑定。

付款之后发生治疗时，本次已接受金额保持，下一次报价使用新事实。真实待选的冻结阶段通过原 typed 帧、严格字典、独立注册表恢复、clone 和回放继续执行；失败动作/选择沿原事务边界回滚。

[必要完整原行及 PIN](../data/support/hero-healed-turn-cost-basics.json)同时保存ICC_700和CORE_ICC_700证据；仅ICC_700在隔离实验注册表接入完整3费3/3中立稀有亡灵及费用条件，无遗漏的额外主体。CORE行未接可执行适配，正式生成池未扩充。实验30槽构筑不代表最新正式标准/狂野合法池。

引入时 `prototype-v230` / `core-effects-v224` / schema213，旧1～212需原引擎。观察74、命令11、replay1和生产代表包保持；完整原历史及条件事实只供宿主规则，不给玩家。实际目标玩家/全局回合、转换/吸血和英雄更换资格、接受窗口及费用层顺序仍属待国服校准的本地政策。

实际验证、已知差异和下一项只维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。
