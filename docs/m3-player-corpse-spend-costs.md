# 本局实际尸体消耗的独立费用输入

实际执行、内部验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本契约描述一个有限费用输入；完整动态费用范围、正式卡池和国服校准仍需分别验收。

## 声明与必要来源

普通物理随从通过 `CardDefinition.player_corpse_spend_cost=PlayerCorpseSpendCostSpec()` 声明，默认 None。唯一 profile 为 `cost.player-corpse-spent-v1`：实际付款者本局每成功消耗一单位尸体，固有费用减一，最低零。拒绝未知 profile、非随从、选择专用定义、星舰载体及同时声明另一固有公式；没有新增组合机制。

必要来源是 [RLK_744 缝合巨人完整本地 raw/pin](../data/support/player-corpse-spend-cost-basics.json)：9 费 8/8 死亡骑士史诗亡灵，需一个邪恶符文，没有战吼、亡语或其他主体。canonical pin 为 `c81544e818e5590d43b8c91952963017f5d87e7c7f7e523fba7b17f2a15eebe2`。适配只在隔离验证注册表；生产代表包保持原范围。本地卡文给出需求，不证明当前国服合法池或精确费用窗口。

## 原事实与纯查询

`player_corpse_spend_costs.py`消费[原实际消耗记录](m3-corpse-spend-history.md)，直接调用原 `spent_corpses` State 查询。固定 `SpendResource`、上限 `SpendUpToResource` 和原 CORPSES 费用账户共享同一成功前缀。累计的是实际单位，不是操作次数、请求上限、当前余额或事件日志。成功零消耗保留零行；增益、略过与失败不计，退款不抹掉过去的成功单位。

完整前缀包括另一玩家和零量行。获取缝合巨人之前的消耗及跨回合消耗均保留；实际 payer 决定当前查询玩家。原资源、付款、选择、异常回滚及回溯执行器负责事实的发布和撤销，本输入没有第二份账本或可变数量缓存。

## 冻结报价与费用层

`PlayerCorpseSpendCostFact` 保存 spec、player_id、turn/action、next_entity_id、next_resource_operation_id、corpse_spend_history_length、完整不可变 CorpseSpendRecord 元组、quantity 和 before/after。连续记录 ID、单调时钟、原物理分配上界、上限 operation_id 的严格递增及原来源卡面都须有效；真实回溯产生的 operation_id 间隙允许保留。数量从全部本人行重新求和，`after=max(0,before-quantity)`。

`IntrinsicCostStageFact.player_corpses` 是显式 nullable 叶。无此声明的普通牌也须保存 None，不能静默缺项。叶绑定原 payer、base cost、turn/action；物理报价另外绑定原 source_id 小于原分配游标。原固有阶段之后才应用原本地/外部费用层和最终下限，生成报价也沿同一纯阶段。报价不改 base_cost、RNG、账户或分配游标。

若本牌随后以尸体账户付款，原接受费用先使用付款前的累计量，再由原付款一次扣款并发布新记录；该新单位影响未来报价，不回改已付金额。普通复制在新 payer 下重新计算，变形按当前卡面选择声明；沉默、回手和再次获取沿原生命周期处理，不重写玩家历史。

## 原窗口、保留与恢复

原窗口由 `validate_intrinsic_origin` 对真实状态重新捕获整份事实，不能只比较相同金额或删除非匹配行。紧凑保留由 `validate_prefix` 要求完整原元组等于当前合法历史的精确前缀，原时钟和分配游标不超过当前值。后来的真实扣款允许追加，已接受根保留原数量与金额。

紧凑前缀只证明保留一致性，不能独立证明一份较早自洽前缀实际来自某次报价，也不认证未签名存档来源。原窗口重查、原支付/phase 证明及保留校验各自承担已有边界。

字典解码复用原 CorpseSpendRecord 严格完整字段，并将 records 转回不可变元组；typed 帧通过原冻结模型类型发现纳入两个新费用类型，没有专用执行入口。真正承诺/完成后待选、独立注册表恢复、clone、回放、继续选择和异常回滚沿原解释器。

## 协议与玩家边界

引入时 `prototype-v227/core-effects-v221/schema210`，明确拒绝旧 schema1～209、未来值、bool/非整数及旧规则/效果签名；旧保存不自动补叶。新增两个冻结费用类型、一个默认 None 卡牌声明和一个阶段叶；原 GameState/PlayerState/Entity、CorpseSpendRecord、资源/上限/付款执行器及原 FrameCodec 源码保持。

观察74、命令11、replay1及生产代表64/合成3保持。玩家只能取得已有 DTO 中允许显示的最终费用，不取得完整消费台账、原分配、冻结报价、私有事件包或付款证明。精确消费发布/接受/反制、来源资格和费用层顺序仍待国服校准，当前不扩展特殊授予或组合矩阵。
