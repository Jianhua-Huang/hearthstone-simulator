# 原始套牌的物理实体绑定

真实构筑开局同时保存原卡面序列 `PlayerState.original_deck` 与对应物理序列 `OpeningState.original_entities`。`Game.from_decks` 的固定场景依次创建每位玩家的一个英雄、一个英雄技能和各原始牌；开局效果、洗牌、抽牌及后来生成的实体均在这段原分配之后。原始行不能从当前卡面、区域、控制者或当前英雄槽重新猜测。

`opening.original_deck_entities(setup)` 由既有 `MatchSetup` 及这段分配顺序重建两个完整有序 ID 元组。`validate_opening_boundary` 比较保存的原始物理序列，即使开局已完成或对局已结束也不跳过。英雄、技能、同玩家后来生成的牌或原行换序均不能冒充原始行；正常卡面变化、抽牌、移区和生命周期保留实际原 ID。不同套牌长度分别按真实构筑长度计算，不固定为30。

此前只检查数量、全局唯一、存在和 owner 的校验不能保护原行对应关系。`FrameCodec.deck_origin` 现在也包含这两组物理序列，挂起的 `RuleContext.state` 必须与实际对局原始事实一致；先前合法捕获中的旧卡面可保持，原始映射不能被替换。

“原始套牌没有其他随从”不需要新的内核条件类型。受信任卡牌回调已有原始 ID 与原卡面，可以先解析所有原定义，再排除指定原来源行并查询 `CardType.MINION`。这不读取当前牌库，不依显示名称或 `deck_identity` 排除；未知开局、外来或生成来源及未知定义明确报错。即使已发现不符合的随从，仍需解析后续与被排除行，避免短路隐藏未支持内容。原“起始无法术”继续使用 `DeckCondition('starting', 'no_spells')`。

完整 JAIL_800 卡文仅证明此条件需求，见[原始证据](../data/support/starting-source-type-expression.json)。本批未适配穆格／兹伊的技能或组合，验证样本使用明确的独立开局夹具；原来源排除的精确国服规则仍待校准。

修复只加强已有开局与捕获状态的身份校验，没有新字段、账本、模块、效果或组合。prototype-v302、schema265、观察84、命令12和replay1保持，解释器身份为 core-effects-v305。原生产代表与开局注册表指纹保持。它不是未签名存档的来源认证，不证明完整卡池或国服时序。

实际验证、差异与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。
