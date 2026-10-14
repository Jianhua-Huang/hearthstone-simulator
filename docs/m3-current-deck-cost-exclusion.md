# 当前牌库指定费用排除

`DeckCostCondition(cost=4, cost_basis='local', scope='current')` 是一个冻结声明，表示指定玩家当前牌库里没有保存费用为 4 的物理牌。`cost` 是明确的非负整数，不能传布尔、浮点、表达式或隐式规则；`cost_basis` 必须显式填写。目前只开放 local/current。

原 `DeckCondition(scope, predicate)` 两字段及原无重复、无中立、无随从和空牌库条件保持。新增声明也交给原 `matches_deck_condition` 和 `CheckDeckCondition`，不创建第二个分支执行器。费用声明只有 cost/cost_basis/scope 三字段，显式注册为不可变 typed payload，未知字段、依据和范围拒绝。

## 费用与物理范围

读取原 `local_cost(entity)`，以实体保存的 base_cost 和原本地附魔有序重建数值，遵守原设费、加减、最低值和生命周期。原 `PoolQuery(min_cost=cost, max_cost=cost)` 判断给定数值；每个物理实体完整查验卡牌定义后才聚合。随从、法术、武器、地标等已知牌型同样参与，重复和身份别名不去重。职业等无关元信息缺失不会妨碍已知费用判断，未知定义仍报错，不能因先找到匹配牌而跳过后续未知行。

印刷 CardDefinition.cost 与保存费用分别保留：原 4 费牌被本地设为 3 后，排除 4 条件为真、排除 3 为假。同一原型中的手牌外部费用报价可以再受玩家修正影响，这种假设报价不替代牌库保存费用；查询不消费用途、RNG、动作、历史或事件。starting、printed、external 等未审 profile 明确拒绝，不静默降级为印刷值。

仅此刻指定玩家的 DECK 参与。手牌、战场、墓地、原构筑及其他玩家不参与；普通抽出、洗入附带保存费用、销毁、换面与生命周期由原区域/费用模块负责。当前牌库为空时满足排除。原其他条件的所需元信息规则不使用这里的豁免。

## 分支、保存和必要代表

原分支轮到执行时读取当时的费用，选择一次。条件之前的费用操作已经生效；选中的分支之后改费用或暂停，不会反向改选。原解释器负责等待、恢复、克隆、独立回放、选择继续、动作/选择失败回滚和玩家隔离。没有新的生产模块、State/Player/Entity/CardDefinition 字段、动作、事件或执行器。

必要适配仅 ICC_853「瓦拉纳王子」，原 4 费 4/4 中立传说亡灵。原战吼返回 `CheckDeckCondition`，命中后用原 `GrantKeyword` 授予自身吸血及嘲讽，无身材加成、印刷关键词或特殊长期授予。其余两位王子及三个 CORE 原行只作完整证据，没有可执行适配。完整 raw/PIN 在 `data/support/current-deck-cost-exclusion-basics.json`，生产代表和正式池保持。

本批 local 是明确的内部牌库费用政策，沿用既有比费所读的保存费用和此前实际诊断；国服准确的费用依据、条件窗口和间接来源仍待校准。官方[凯雷塞斯王子卡库](https://hearthstone.blizzard.com/en-gb/cards/45340-prince-keleseth/)可确认存在费用排除要求，但卡文本身未指定费用层；[历史玩家报告](https://eu.forums.blizzard.com/en/hearthstone/t/prince-keleseth-hs/3825)只提供减费影响条件的个人观察，不作为官方验证。不能据此将 M6 或全部费用条件标成完成。

引入时 prototype-v236/core-effects-v230。新声明使用原显式帧白名单；原结构与字段保持，schema215 及旧1～214拒绝、观察74/命令11/replay1保持。处理器签名已改变，旧快照仍需原处理器；保持 schema 不自动迁移。实际执行及下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。
