# 本局原职业出牌数量：独立历史查询与费用输入

实际执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约只定义原职业出牌数量的基础能力，不代表U53整族、正式卡池或国服规则已验收。

## 原手牌根与职业依据

`played_cards`增加可选`card_class`筛选，要求一个严格`CardClass`及已固定的注册表；无筛选的既有接口保持。纯`matches_played_class`读取完整原`FrozenPlayedFaceFact`，复用`PoolQuery(class_mode='specified', include_neutral=False)`和`matches_metadata`。筛选采用原印刷职业成员，不采用当前英雄职业、后来变形后的卡面、获取区或卡牌持有者的职业。双职业卡符合一个指定职业时贡献一次；中立卡不符合任何指定可玩职业。未知原卡面或必要职业数据明确报错。

原`PlayRecord`在实际付款完成后追加、`card_committed`发布前已经存在。查询只计实际玩家的原物理手牌出牌根，零费及替代账户同样是出牌；每次出牌计一次，同一物理卡回手再打出可以再次计数。获取定价随从前的原出牌以及此前回合均保留。普通召唤、生成、自动施法、英雄技能、交易和锻造不新增这种手牌根。

本地profile包括已付款的反制根及尚未完成的根；失败动作沿原事务回滚，后续完成/中断不会撤回已保存的原卡面。这些接受时点、反制/退款及特殊出牌来源的精确国服政策仍待M6校准。定价自身在新付款前尚未追加，不能为这一次付款给自己减费；之后原根可为下一次报价贡献数量。

## 有限声明与必要代表

普通手牌随从声明`CardDefinition.player_played_class_cost=PlayerPlayedClassCostSpec(card_class=...)`，默认None。原默认profile为`cost.player-played-class-v1`，只接受单一可玩职业；新增有限`cost.player-played-card-count-turn-v1`显式要求`card_class=None`，按本回合全部牌型计数，见[本回合出牌费用契约](m3-player-played-turn-costs.md)。未知profile、原profile的空/中立职业、新profile的职业筛选、非普通随从或另一数量公式均拒绝。单一职业参数不是职业/种族/关键词组合表达式。

只隔离适配TID_077光鳐，按[完整本地raw](../data/support/player-played-class-cost-basics.json)的9费5/5、嘲讽和圣骑士印刷职业实现；canonical pin为`2d6fe2d3ff81d7e03baa5e78fce566ca3390e84f118f92de4cb2e387f7aa8dbb`。生产代表包不扩张，其他职业仅为公共参数边界，不代表额外真实卡已适配。

[暴雪卡牌库](https://hearthstone.blizzard.com/en-gb/cards/76258-lightray/)的索引卡文支持按本局圣骑士出牌数减费；本轮直接打开的页面仍是JavaScript壳，不认证精确CN时点。[28.4补丁](https://hearthstone.blizzard.com/en-gb/news/24046221/note-della-patch-28-4/)明确修复了中立英雄雷诺错误地给光鳐减费，支持排除中立、依据印刷职业的边界。索引所示当前种族与本地单种族记录有差异，正式目标池/有效卡面仍由M0锁定；此实验固定本地证据，不以搜索摘要暗改原raw或宣称最新完整卡面。

## 公共价格与原证明

`player_played_class_costs.py`读取原出牌历史，金额`max(0, base_cost-quantity)`进入共享固有阶段，在原条件、本地附件和外部费用层前；物理、生成、玩家显示、合法操作和付款沿同一报价。没有新的出牌台账、玩家累计字段、实体缓存、玩法事件或外部动作。

`PlayerPlayedClassCostRow`保留完整原`FrozenPlayedFaceFact`、turn/action及获取身份/时钟，包含未选中的对手和其他职业行。它不重复保存会逐步完成的主体结果，也不把原提交报价递归嵌入每一行。`PlayerPlayedClassCostFact`冻结完整有限声明（原职业或当前turn全牌型）、实际payer、原报价turn/action、实体分配上界、完整原历史游标、有序卡面前缀、完整selected_ids、数量和before/after。连续物理根、严格类型、原窗口/归属/获取、注册表元数据和完整选择均须一致。

固有阶段要求显式`player_played_class`叶，为事实或None，绑定原payer/base及完整原窗口；物理来源必须早于原分配上界。原实际接受窗重新捕获输入；紧凑历史比较完整原卡面/身份前缀，允许原主体合法完成、后来新增出牌或推进回合，旧价格保持原数量。不能以总数相同为由换卡面、职业、owner区间、游标或物理来源。保存检查不提供未签名存档的来源认证。

选择恢复、clone、replay和异常回滚沿原解释器；原卡已完成后由监听者产生的待选异常回滚到该待选边界，不撤销此前已提交的付款。普通印刷复制、沉默、回手后按实际玩家历史重新报价，特殊来源/复制后置。玩家只得到最终费用，完整原卡面前缀、选择与付款证明和对手隐藏手牌保留在内部。

## 协议与未闭合范围

本项引入`prototype-v190 / core-effects-v184 / schema179`，明确拒绝旧1～178；观察74、命令11、replay1保持。默认`player_played_class_cost=None`改变注册表指纹；固有报价显式叶及冻结原卡面输入改变保存格式，不静默补旧字段。没有新GameState/Entity/Player字段。

本项没有任意条件、任意费用表达式、其他出牌来源或跨机制组合。精确接受窗、反制/退款、费用层顺序、特殊来源/复制、正式卡面/池以及国服校准继续开放。

现行共享接口为prototype-v225/core-effects-v219，schema208字段/布局及拒旧1～207保持。同一Spec的card_class类型沿CardClass | None，严格字典及typed帧只对本回合全牌型profile接受显式null，不静默默认为圣骑士；旧整局职业选择、全部字段和原数量时点保持。现有TID_077隔离声明的race18种族标识已对齐生产解析器的小写elemental，原完整raw/pin及全局匹配保持。实际验收与下一项只在两份台账维护，精确CN仍开放。
