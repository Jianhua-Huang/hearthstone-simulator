# 手动法术费用条件与支付来源契约

本页描述 `prototype-v111` / `core-effects-v111`、snapshot schema108 的开发接口。实际执行、内部验收与下一项只在 [项目状态](project-status.md) 和 [机制工作清单](mechanism-backlog.md) 维护。本文不证明整个费用增量已通过，也不证明当前国服时序或完整卡池。

本能力扩展 [法术原两接受窗口](m5-spell-match.md) 的公共匹配条件。仍在原提交窗口接受玩家重复政策，在较晚主体窗口接受场上重复来源；支付前证明用于认证付款，不新增重复接受窗口。

## 1. 费用条件是交集

`RepeatMatchSpec.recipient_cost` 可为空，或为不可变 `RepeatCostFilter`。费用条件与既有职业、学派和来源资格条件取交集，不替代其中任何一项。

| 字段 | 契约 |
| --- | --- |
| `basis` | `printed`、`local`、`submitted_quote` 或 `window_quote` |
| `minimum` / `maximum` | 可选的非负真整数，包含端点；至少一个边界，最小值不能大于最大值；布尔值不是整数 |
| `quote_profile_id` | 只有 `window_quote` 必须指定已注册profile；其它依据不得携带profile |

`printed` 是已接受卡面的定义费用。`local` 是该接受窗口中物理实体的基础费用及有序本地附魔结果，尚未应用外部层和最终手牌下限。`submitted_quote` 是原手牌付款采用的完整报价。`window_quote` 是指定接受窗口的完整查询结果。

报价数值不是实际资源余额差。临时法力、护甲支付、生命损失替换和尸体账户都不能用法力差来判定费用。`actual_payment` 暂不支持；不能将它悄悄转换成报价条件。

静态声明、profile及所需完整事实先验证，再判断条件真伪。职业或学派不匹配、费用不匹配、来源资格不成立，都不能绕过未知声明或必需事实错误。

## 2. 显式费用查询profile

默认 `CostQueryProfile('repeat.cost.accepted_hand')` 的固定政策为：

- 主体是原已接受的手动付费手牌法术。
- 使用接受卡面及当窗物理实体的基础值、完整本地附魔和能力结构。
- 使用该窗口的玩家费用政策，以及双方场上/武器的有效费用光环；按现有作用域、关系、存活和消费规则筛选。
- 最终最低费用取原提交手牌输入，即使较晚窗口中实体已经进入墓地。

不把墓地实体临时移回手牌，不创建虚拟实体，不篡改局面以查询费用。profile进入注册表指纹；只允许实际实现的政策组合，不允许换一个profile名字表达尚未实现的查询语义。

上述接受手牌下限与查询时点属于本地暂定政策 R-157。历史国服公告和冻结卡文只用于发现费用需求，不能代替当前国服规则校准。

## 3. 完整报价事实

`CostQuoteInput` 保存物理source、payer、card、kind、base cost、完整有序附魔、完整能力结构及明确minimum。报价计算复用出牌校验、合法操作与实际付款使用的公共公式。

先按本地列表顺序计算加减/设值与各层最低值；再按全球附件ID顺序计算合格玩家修正和费用光环；最后应用原手牌最低值。set操作和逐层minimum不得被无序加总替代。

`CostContribution` 分别保存本地附魔、玩家 `CostModifier`、实体费用光环 `AbilityInstance` 的完整typed值，以及payer/物理carrier身份。`CostQuoteFact` 保存输入、local数值/账户、完整数值/账户、有序贡献、全部外部ID及有限用途ID，不只有最终整数或ID列表。

这些字段可供冻结事实的代数与身份校验。历史 compact 收据不会根据当前局面重新判定旧价格，也不宣称未签名快照具有外部来源认证。

## 4. 提交与较晚窗口分别捕获

`PlayRecord.submitted_cost` 是原付款报价的 `HandPlayCostReceipt`，包含取得身份、区域epoch、quote origin及完整报价；报价数值/账户必须与 `PlayRecord.cost/payment` 一致。

`SpellSubmissionReceipt.cost_facts` 和 `SpellPayloadReceipt.cost_facts` 分别保存原两窗口要求的 `SpellCostFacts`。先从本窗完整声明集合收集所需profile，再查询，每个所需profile一份事实。没有相关费用声明时允许没有费用事实；有声明时不允许缺事实或改用另一窗口事实。

付款会先消费有限次减费。因此原submitted quote可为1，而付款后的提交window quote和较晚window quote均为3。付款事件的反应稍后实际执行，还可以使较晚报价再次变化。

玩家重复用途依据已保存的提交匹配集合消费，不进行第三次费用匹配。原完整max计划同时保留单位根、空主体、全部合格来源和未贡献max的较低来源。额外执行、挂起选择和保留结果不重新报价、支付或消费已接受用途；下一真实出牌根再捕获新事实。

## 5. 支付前证明与分阶段投影

当前真实顺序是报价、准备PlayRecord、付款、安装PlayRecord、接受提交政策、移动和反制/目标窗口、接受较晚主体。`HandPlayCostProof` 在付款前捕获完整原局面与准备记录，不从付款后的局面倒推原折扣。

认证首先重算原完整报价，然后用共享纯支付投影检查付款到提交局面的全部变化。投影不调用真实付款、事件捕获、行为回调或随机数，也不插入检查点。

MANA仍先消费临时法力；HEALTH仍先确定支付替换资格，再扣护甲及处理剩余生命损失。替换产生的生命上限增长、新附件与分配ID进入投影。生命替换/增长事件的原捕获发生在有限费用用途消费之前，账户spent事件发生在其后；准备记录在这些付款捕获时尚未安装。

每次真实emit的死亡归因与手牌关键词光环归一化复用纯计算。不能将最终提交局面作为所有早期事件的原窗口，不能宽泛忽略缓存、死亡归因或附件差异。

## 6. 共享费用用途与全球身份

`GameState.cost_use_history` 保存有序 `CostUseReceipt`。每个真实付款入口保存全部已报价玩家来源、原剩余用途及实际有限消费集合，按完整值认证剩余次数的精确变化。

随从/法术/武器/英雄/地标付款和适用英雄技能共用既有CARD范围。免费效果星舰发射消费独立STARSHIP_LAUNCH范围，origin为 `effect_launch`，不因此新增资源扣款。交易/锻造固定费用不会消费CARD修正。合法开局行为的action为0，不能被收据构造器误拒。

活动原证明保存双方完整来源目录，包括全false来源和其它附件族。后续用途链必须保留原历史前缀、owner、physical carrier、family和完整声明；有限用途不能仅以“次数不增加”放行。即使最后一次用途使来源消失、后续子Finish已经关闭，原活动父窗口仍要校验这条精确链。亡语、英雄技能和结束主体的原证明复用共享费用用途桥。

## 7. 真实Rewind来源

普通手牌根使用当前付款前局面。只有真实同一物理手牌根的重试使用其实际 `RewindSession.before` 原报价；另一个子手牌根不能借用外层Rewind checkpoint。

`HandSpellRewindAnchor` 绑定真实action、before、attempt和event_start。恢复认证允许原内核的分配计数高水位、实际重试日志和注册合法卡面转换，保留原取得身份与所有其它恢复字段，拒绝任意“结构合法”的旧局面。

`HandPlayCostProof.rewind_session` 保存真实同根session，包括初次attempt0；`rewind_anchor` 只在attempt大于0时认证原重试报价。两者必须与实际session一致，不能将初次会话伪装成重试，不能删除真实会话以降级成普通出牌证明。

合法两面拥有相同底层定义和印刷费用，但按原card ID限定的折扣可只命中原面。重试采用原报价1，而新面window quote为10，是不同依据的合法事实。当前资源/用途随checkpoint恢复，丢弃尝试不能继续积累成本用途；日志中的多个尝试事件与当前唯一有效历史分别处理。

## 8. 解释器与玩家边界

完整支付/接受证明仅存在活动 `FinishSpellAcceptance` 和相应typed帧中，历史保存compact事实。选择等待、工作弹出、Finish关闭和终局丢弃队列前，都要验证原接受义务；反制只保留已经到达的窗口，不能补造未到达的成功payload。

真实session的原before局面独立认证retention资格。每个已分配并启动主体的cast都须保留原结果计划、完整来源、总次数及执行身份；结果完成状态与原完整控制跨度一致。不能同步降低计划和队列次数，也不能将全部结果及控制删除后据此声称没有保留义务。这不新增费用查询或重复接受窗口。

晚typed子窗口须绑定原父已接受的完整费用事实与false来源；付款时更早的普通callback不需要未来尚未安装的父记录，不能把这两种时点混同。

snapshot schema108严格解码全部typed字段，拒绝旧schema1～107。公共观察 `player-view-v55` 只公开费用条件参数basis/bounds/profile；原付款局面、原费用来源、完整贡献和证明均不得出现在玩家DTO、动作和过滤日志中。命令仍v7，外层replay仍schema1；全知快照不能交给行动方。

## 9. 独立剩余工作

固有动态费用及所需历史、自动/抽取/历史CAST条件与替换、其它重复族费用轴、actual_payment谓词、正式合法池和国服校准各有独立范围。本公共手牌费用匹配不自动完成Quickdraw、Kindred、巨人或海上船歌等具体卡，也不为无PlayRecord的施法补造手牌付款记录。

实际测试、差异、已知限制与后续项见 [项目状态](project-status.md)。依据与必要场景设计分别见 [公共设计](../outputs/v115-cost-matching-public-contract-design-candidate.md) 和 [必要场景矩阵](../outputs/v115-cost-matching-necessary-scenario-matrix-v2.md)；设计不是执行证据。

## 已接受分支的报价

当前prototype-v147/core-effects-v147/schema142的[分支费用层](m5-choose-branch-costs.md)使local在原intrinsic及所选branch操作之后读取本地结果；printed保持印刷，submitted_quote绑定原activation和实际branch，window_quote沿该已接受branch在自己的接受窗报价。原不支持actual_payment的限制保持。unselected事实不能借入已接受Spell；上方schema108原批格式和验收范围保留为历史。
