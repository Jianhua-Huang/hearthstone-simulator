# 死亡费用筛选与复活后的实体续接

M5-12b-02a 公共子集；`prototype-v75` / `core-effects-v75`、snapshot schema 74、representative-m5-v38。旧 1～71 快照拒绝；player-view-v44、player-actions-v7、外层 replay 1 保持。实现见 [summon_sources.py](../hs_sim/engine/summon_sources.py) 和 [sacrifice.py](../hs_sim/engine/sacrifice.py)，[51 项专项](../tests/test_m5_resurrection_followups.py)已通过，全量结果由[项目状态](project-status.md)统一登记。

## 费用筛选

`DeathQuery(cost_extreme='highest' | 'lowest', cost_basis='printed' | 'local_at_death')` 先应用职业、种族、回合、来源、费用区间等原有过滤，再留下费用最高或最低的全部并列记录。默认 `cost_extreme=None` 保持原查询范围；默认费用依据为印刷费用。

`printed` 读取死亡时卡牌身份的注册定义，变形后的身份按新定义计算。`local_at_death` 使用不可变死亡记录中的基础费用和有序费用附魔，复用 `local_cost` 的设值、加减与下限规则；费用区间过滤和极值比较使用同一依据。它不代表当初支付金额、死亡时手牌光环报价或当前墓地实体费用。后续墓地实体变化不能改写既有候选成本。

筛选保留所有并列死亡，再由 `Resurrect` 的 `distinct='death' | 'card'` 与随机/历史顺序策略决定选择。批量调用冻结这一次的极值候选，并不在复活一个最高费用随从后自动降到下一费用档。后续反应产生的新死亡不混入冻结候选。空候选、零次或满场不消耗抽样随机数。

## 成功复活与续接

`Resurrect(..., on_summon='behavior')` 和 `ResurrectMinion(..., on_summon='behavior')` 可声明成功后的注册行为。即使没有候选、零次或满场，也先确认行为已实现；未知行为不能悄悄成为无效果操作。

复活时记录新主体的实体、原始入场顺序和区域修订号。完成通常入场、巨型附肢及召唤反应后，续接检查该主体是否仍是原来的活跃入场实例，再构造 `RuleContext`：`target_id` 为本次主体，`death` 为原死亡记录，`player_id` 为复活接收者，`source_id` 为原效果来源，无来源时使用接收者英雄。它不通过战场最后一张牌或最后一条复活历史猜测对象，因此嵌套复活与附肢不会替换目标。

来源离场不撤销已安排的续接。主体死亡、回手、再次入场、变形、转控或进入休眠时跳过；转控后转回也属于新入场身份。单纯沉默不改变物理入场，续接仍可按当前状态继续。终局停止剩余工作。

行为可读取当前主体和死亡记录，返回普通公共效果。跨多个效果保持“仍是该实例”语义时，应使用 `MinionReference.capture(...)`、`BuffCapturedMinion` 及新增 `GrantCapturedKeyword`。后者复用普通关键词授予、独立能力实例、来源、到期、沉默和复制语义，每次执行前重新检查引用；不能借此裸授予泰坦等需要专用实例的复杂能力。

```python
Resurrect(player_id, query=DeathQuery(cost_extreme='highest'),
          source_id=source_id, on_summon='enhance_resurrected')

def enhance_resurrected(ctx):
    ref = MinionReference.capture(ctx.state.entities[ctx.target_id])
    return [BuffCapturedMinion(ref, 2, 2, ctx.source_id),
            GrantCapturedKeyword(ref, Keyword.REBORN, ctx.source_id),
            GrantCapturedKeyword(ref, Keyword.LIFESTEAL, ctx.source_id)]
```

这段行为需要注册后使用。单次效果可能引发反应，因此三项增益并非不可分割的事务窗口；若第一项增益引发变形，后续关键词跳过原引用。整个外部操作发生异常时仍统一回滚；已经提交选择的早期结果保持既有选择事务边界。

## 恢复与验证

`ResurrectionRecord` 新增原始 `entered_order` 和 `zone_epoch`；入场顺序不取随从的后续当前值，否则正常转控会被误当作损坏历史。加载时校验待执行续接的成功记录、新实体、死亡卡牌身份及原始入场引用；未知行为、错误记录和不匹配主体明确拒绝。悬挂选择保存带类型的续接，恢复后保持随机、候选和目标身份。

专项覆盖最高/最低费用、并列/去重、死亡时减费、双方历史、满场、嵌套复活、巨型、源与目标生命周期、关键词到期/沉默/复制/复生、自动施法、回溯、选择恢复、错误回滚、终局及玩家信息。公开复活事件沿用既有格式，不公开内部死亡 ID、复活 ID 或续接对象。

## 必要代表、R-096 与下一步

仅新增艾泽里特鼠 `WW_001t26` 的实验适配。冻结本地卡文明确要求复活最高费用随从并给予 +2/+2、复生和吸血，原始文本保存在[宝藏快照](../data/support/excavation-inventory.json)。官方卡库有[对应记录](https://hearthstone.blizzard.com/en-us/cards/102069/)，但本次页面抽取没有提供足以证明费用基准和精确触发窗口的内容，不把它当作这些边界的证据。

死亡骑士第四次发掘现在能获得可执行的鼠；法师鹰与战士牛已在[特殊生成与发现交付](m5-discovery-delivery.md)中实验适配，龙/鱼人已在[跨区契约](m5-cross-zone.md)中实验适配，术士蛇已在[生命转移契约](m5-health-transfer.md)中实验适配。其余低阶宝藏仍为明确的实验样本池，未扩大为完整正式奖励池。

**R-096 暂定契约：** 鼠使用印刷费用、并列死亡等权；续接安排在入场与召唤反应后，原目标身份改变时跳过，三个增益之间保留正常反应窗口。死亡时本地费用仅作为显式公共查询选项。不同来源、休眠、巨型、变形/转控及费用修正的精确国服行为仍需校准，51 项内部测试不认证官方一致性。

运行 `python -m examples.resurrect_highest`，通过玩家接口让雪人和灰熊死亡，打出鼠复活并强化雪人，再用对手法术触发复生；验证新实体为基础 4/1 且不继承额外关键词，共 8 动作、50 事件，保存恢复与回放一致。[示例源码](../examples/resurrect_highest.py)。

多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。发掘整类、正式池与国服集中校准尚未完成。

v73复验：resurrect_highest.py 为 8 动作/52 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为resurrect_highest.py：8动作/54事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
