# 成功召唤种族数量的独立费用输入

实际执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约定义一个真实需求的有限输入，不表示动态费用整族、正式池或国服校准已经完成。

## 声明和真实来源

普通物理随从通过 `CardDefinition.player_summon_count_cost=PlayerSummonCountCostSpec()` 声明，默认 None。现有两个有限 profile：`cost.player-summoned-totem-count-v1`（默认）与 `cost.player-summoned-beast-count-v1`，分别按本人本局成功召唤的图腾或野兽每次减一费，最低零。拒绝其他类型、星舰载体、未审核的任意种族表达式及同时安装多个固有数量公式。

仅使用必要 [OG_028 深渊魔物完整本地 raw/pin](../data/support/player-summon-count-cost-basics.json)：6 费 5/5 萨满稀有随从，原嘲讽，没有战吼或其他主体。隔离验证注册表只接 OG_028；CORE_OG_028 保留完整原行作为证据，没有新增生产适配。支持文件 canonical pin 为 `2d0d6538374a6d2b91cd2c47e6aff0f1d4934ab97551290f0116007cf6ffe9e8`。本地固定记录提供声明依据，不能证明当前国服合法池和精确召唤时序。

## 复用原成功历史

`player_summon_count_costs.py`直接消费 [原成功召唤事实](m3-successful-summon-history.md)。候选选择复用 `successful_summons._matching_rows`，公共查询和费用没有第二套匹配或召唤记录器。实际 payer 决定玩家范围，按有限 profile 选择 `('TOTEM',)` 或 `('BEAST',)`，读取原成功发布时的当前种族；原特殊 `all` 关系仍由既有种族查询处理，每次成功只贡献一。不是读取当前场上数量、持牌以来的数量或召唤者的当前控制权。

获取深渊魔物之前的成功同样有效；后来死亡、变形、回手和转控不重写旧记录。普通手牌出牌和原效果召唤均读取原统一成功发布点；重新入场是另一次成功。失败、初始配置场面、变形及磁力合体不凭空增加成功历史。这些语义由原事实层负责，本输入没有新的召唤执行器。

完整原前缀保留对手、非图腾和未知种族行。当前 payer 范围内未知种族不能按零处理，明确抛出 `UnsupportedDefinitionError`；范围外未知行仍保留但不妨碍本人的查询。印刷和原成功时当前种族分别保存，不能用后来 live 实体代替原身份。

## 原报价与冻结证明

`PlayerSummonCountCostFact`保存原 spec、payer、turn/action、`next_entity_id`、`next_order`、`next_successful_summon_id`、完整有序 `SuccessfulSummonRecord` 元组、selected IDs、quantity 和 before/after。原记录包括完整分配、归属、事件、印刷种族和有序当前种族声明。数量与金额按完整行重新计算；连续 ID、单调时钟/事件、物理入场唯一性和分配上界均须成立，原印刷随从和种族必须符合固定注册表。

金额 `max(0, base_cost-quantity)`进入原固有阶段，再经过原本地/外部费用层和最终下限。物理、生成、玩家显示、合法动作和一次付款共享原管线；查询不写 base_cost、分配 ID、RNG 或台账。普通沉默、回手、印刷复制和新获取复用原生命周期；新 payer 的报价重新读取该玩家历史。

`IntrinsicCostStageFact.player_summons`必须显式保存完整事实或 None，普通卡也须有 None。原报价绑定原 payer/base/turn/action 和物理主体分配边界；无声明的牌不能伪造这个费用叶。严格字典读取复用原 `SuccessfulSummonRecord` codec，typed 帧只允许已有冻结记录和两种新费用类型，不增加执行入口。

## 原窗口与后续推进

原窗口使用 `validate_intrinsic_origin`从真实状态重新捕获完整事实，不能删去非匹配尾行，即使删后金额相同也须拒绝。紧凑历史校验要求整份原记录是当前合法历史的精确前缀，原时钟及分配游标不超过当前值；后来的真实成功允许追加，不改已接受根的金额。

紧凑前缀证明只能证明保留一致性。它允许一份结构自洽的较早前缀，不能独立认证该前缀确实来自一次原报价，更不提供未签名存档的来源认证。原窗口重查、共享付款/phase 证明与紧凑保留校验各有边界，不能互相替代。

承诺及完成后的待选、恢复/clone/独立注册表回放、真正继续付款和事务回滚沿原解释器。等待期间新召唤使后续报价重新计算，先前已接受报价保持原量和一次付款。

## 协议和信息边界

引入时 `prototype-v221/core-effects-v215/schema206`，明确拒绝旧 schema1～205、未来版本、bool/非整数及旧规则/效果签名；旧保存不静默补叶。原 State 历史字段保持，新增两种冻结费用类型、一个默认 None 卡牌声明和一个显式阶段叶。观察74、命令11和 replay1、modular-v1/fabled-v2及生产代表64/合成3保持。

没有新 State/Entity/Player 字段、计数缓存、Effect、事件、外部动作或召唤/支付/生命周期执行器。玩家只取得允许公开的最终费用，不取得完整私有成功台账、原分配、游标、选择和付款证明。精确原召唤方、当前种族可见窗、费用层序、特殊来源及国服校准继续开放，当前不开发组合矩阵。

## 野兽输入与版本边界

`PlayerSummonCountCostSpec('cost.player-summoned-beast-count-v1')`复用上述完整原前缀、当前种族依据、原报价/付款、恢复与玩家隔离。声明仍只有原有的profile字符串，没有新增状态或存档字段；匹配在报价与冻结事实校验中共用同一有限profile到种族映射。默认图腾政策保持，未知profile继续拒绝。

必要隔离代表为AT_041荒野骑士，7费6/6德鲁伊稀有随从，无自身其他主体。[固定完整raw/pin](../data/support/player-summon-beast-cost-basics.json)另保留AV_291霜刃豹头领原行但未新增其执行适配。荒野骑士本局野兽召唤减费的卡文与[官方27.2更新](https://hearthstone.blizzard.com/en-us/news/23987537/27-2-patch-notes)一致；不能使用此前仅手牌内触发减费的历史行为替代这份更新定义，也不能据历史公告宣称当前国服时序或正式池已认证。

本次扩展的默认效果版本为core-effects-v287；prototype-v290/schema254、观察84/命令12/replay1及生产代表包保持。旧默认效果签名不能直接冒充当前引擎，存档结构没有增加叶或隐式迁移。实际结果、影响范围及未执行检查仍只在两份主台账维护。
