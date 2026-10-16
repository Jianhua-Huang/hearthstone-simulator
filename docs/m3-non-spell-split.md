# 原非施法分摊与条件续接

迁徙的雷象 MEND_302 是 4 费 3/3 战吼随从；喷发火山 CATA_584 是 3 费 3 耐久地标。完整原行及四份中英文官网完整卡面见 [固定包](../data/cards/non-spell-split-v1.json)。两者均通过原伤害执行器造成非施法分摊，不创建伪造 CAST。

## 既有管线的有限扩展

`RandomSplitDamage` 保留原 SPELL 默认 profile，在末尾增加 `kind`。显式 `profile=NON_SPELL_PROFILE` 要求 `cast_id=None`，仅接收 `MINION_ABILITY` 的 MINION 来源或 `EFFECT` 的 LOCATION 来源；拒绝假 CAST、不匹配来源及其他类别。非施法原预算不包含任何 Spell Damage。原 `SplitDamage` 请求及执行函数保持不变。

两种 profile 共用现有完整候选、每实体一个权重、一次 RNG 抽样、单位普通 `Damage`、死亡/反应/待选、原证明和唯一完成尾。原法术来源及预算冻结规则保持。非施法每个单位额外记录本次交付窗口的原来源事实及关键词，复用普通逐点伤害语义：来源离场仍有分配身份；转控、同类换面或后来授予关键词由下一点读取，不重定向已接受的候选归属。

`SplitPacketReceipt.source/source_keywords` 保存单位材料，`SplitBudgetQuote.cast` 仅在有限非施法 profile 中允许 None。单位完成、挂起边界及关闭事件核对这些材料与原窗口；来源、目标、预算、RNG、结果与完整尾仍沿原校验。不增加模型字段、计数器、解释器类型或 payload 类型。持久收据结构变化采用 core386/schema309，旧 schema308 存档使用原引擎。

## 原死亡信用与真实消费者

`closed_root(state,event)` 要求真实完成事件的完整原根与当前历史相等。`killed_minions` 只返回实际 `DeathRecord` 中首个致死转移的 HealthResult 与该根原单位结果完全匹配的死亡；不以本局死亡总数、来源 ID 或后来整场变化代替。

雷象第一组三点完成后读取这一结果，有击杀时只追加一个三点根；额外组没有再次追加的回调。无关消灭和其他根的死亡不产生信用。喷发火山每次原使用读取本人本回合原手牌出牌的 FIRE 法术事实，成立时请求两组三点，否则一组；按既有 committed-play 政策包含被反制的出牌，自动施法、对手或上一回合不算。地标的安装、冷却、原支付和末次移除继续由既有生命周期处理。

这是内部原组/直接致死、逐点来源及条件接受政策，转移目标、附加击杀资格和精确国服接受窗口仍待 M6；官网卡面不证明服务器时序。原始 source 标签与正式池资格独立保存，不从这两张适配认证完整生成池。

[专项](../tests/test_non_spell_split_cards.py)覆盖真实支付/类型/非 CAST、三点或一次追加、无关消灭、法伤隔离、地标三次使用和最后伤害、原火焰出牌事实、每点原来源、坏帧、等待恢复/clone/回放/回滚与玩家隔离。实际验证结果和下一项仅在 [项目状态](project-status.md)、[机制执行清单](mechanism-backlog.md) 维护。
