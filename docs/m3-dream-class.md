# 梦境印刷类别与可用英雄职业

五张真实梦境卡在固定源中使用`CLASS=11`。解析为独立`CardClass.DREAM`，保留完整类别、种族、学派、稀有度及可收藏性，不改成中立，也不作为未知类别绕过。完整五行和十份官网卡面保存在[固定测试材料](../data/support/dream-class-metadata.json)；[HearthSim原始枚举](https://github.com/HearthSim/python-hearthstone/blob/master/hearthstone/enums.py)的`DREAM=11`与`NEUTRAL=12`作为公开类别命名证据，实际读取全文另有固定SHA。

卡牌类别和可用英雄职业分开：`PLAYABLE_CARD_CLASSES`仍只有原来的十一项。`DeckSpec`拒绝Dream职业，实际玩家的英雄/初始牌组类别也不接受Dream；祈愿和发掘的可用职业集合复用这份明确集合。原未知13、非法布尔和未知位仍拒绝。

已有印刷类别筛选、另一职业条件、费用与施法重复按真实Dream类别查询；它既不是中立，也不是当前法师职业。保存、复制、玩家卡面和原出牌材料使用已有类别编码，等待恢复和回放保留该枚举。没有新增英雄角色、卡牌定义、效果、载荷或状态字段。

core393/schema316拒旧格式；默认311指纹和原构筑完整定义保持。此处只补真实类别表达，不代表梦境卡主体或完整五项随机池已接通，也不确认未解码4392标签的含义。实际验证与下一项只在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护；正式池及国服精确时序继续单列。
