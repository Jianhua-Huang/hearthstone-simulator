# 本局原角色攻击声明计费

普通物理法术声明 `player_character_attack_cost=PlayerCharacterAttackCostSpec()`，有限profile为 `cost.player-character-attack-declared-v1`。它复用[统一角色攻击历史](m3-character-attack-history.md)，按原声明控制者统计本局全部实际攻击窗口，每个窗口减1、最低零。当前政策包含手动英雄/随从及既有强制随从声明；后来取消或中断不撤回原声明。这是明确内部口径，精确CN的阶段/强制/取消信用仍待校准。

卡文中的“攻击过”不能被不加说明地换成伤害量、完成次数或当前攻击机会。本profile只选择原声明；来源资格、随机、交付、战斗、武器损耗、死亡与后续阶段继续由原内核负责。裸随从直接战斗伤害没有实际窗口就不造信用；没有扩展强制英雄、任意来源、特殊授予或组合。

`PlayerCharacterAttackCostFact`保存payer、原turn/action、实体/顺序/窗口分配界、完整原声明投影及数量/前后值。投影复用 `CharacterAttackRecord`原声明字段，明确清除交付/接受/终态，避免这些合法后续变化改写已接受价格；不另造历史或计数器。所有双方、未匹配和强制声明均保留，原卡面/类型在注册表验证。

原窗口重新捕获完整输入。保留历史时必须精确等于当前历史中全部 `window_id < 原next_window_id`的声明投影，不能仅取同长度前缀；这样同一动作内未参与减费的尾部也不能被裁掉。之后新声明只影响新报价，后来完成/取消/转控/变形不修改原费用事实。原物理主体不能借用未来分配，未知原卡面明确拒绝。

数量在原固有阶段写 `IntrinsicCostStageFact.player_character_attacks`私有叶。物理/生成报价、合法动作、本地/外部/最低费用层、付款和恢复/回放共享原管线。查询不分配实体或消耗随机；完整声明前缀和付款证明不提供给玩家，玩家只得到允许观察的费用和事件。原一致性证明不认证未签名存档外部来源。

[完整本地原行](../data/support/player-character-attack-cost-basics.json)只隔离适配 CATA_568穆拉丁的奋战：9费萨满稀有自然法术，主体沿已有 `Draw`抽两张牌。[官方卡库](https://hearthstone.blizzard.com/en-us/cards/122999)索引文本确认卡文及职业/派系/稀有度；不据此宣称准确来源阶段、当前CN正式池或完整校准。生产代表包和生成池保持。

无新GameState/Player/Entity字段、攻击记录、分配器、账户、战斗/支付执行器、事件、动作或组合；只新增有限费用模块、两冻结费用类型、定义默认None声明和私有费用叶。JSON和typed-frame要求显式字段及原类型，选择恢复、克隆、独立注册表回放和失败回滚共享原解释器。

定义/私有叶改变格式，引入 `prototype-v295` / `core-effects-v294` / schema259，旧1～258需原引擎；观察84、命令12、replay1保持。实际验证、差异和下一项仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护，阶段全量/完整库存与M0/M6/M7继续开放。
