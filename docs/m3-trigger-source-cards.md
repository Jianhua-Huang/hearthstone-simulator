# 原施法、抽牌与失盾触发来源

本页维护接入与扩展契约；实际进度、验证和下一项仅在[项目状态](project-status.md)与[机制台账](mechanism-backlog.md)。完整原行、显式配方及身份依据见[固定数据](../data/cards/trigger-source-effects-v1.json)，适配见[trigger_source_cards.py](../hs_sim/cards/trigger_source_cards.py)。衍生物入侵的魔蝠由艾瑞达欺诈者命名的COLLECTION_RELATED_CARD_DATABASE_ID=101499锁定，完整1/1、突袭、恶魔身份随卡交付。

| 来源 | 原事件与资格 | 公共执行 |
| --- | --- | --- |
| 游学者周卓 | 双方手动法术开始；origin=hand，含反制，额外及代施法不另计 | 从原物理法术保存复制材料，向另一方交付base副本 |
| 死亡寒冰 | 本人SPELL出牌整次完成、未反制 | 当前敌方角色中选至多两个不同目标，单个MINION_ABILITY DamageBatch各1伤害 |
| 阿拉巴斯特 | 对手原card_drawn及DrawRecord；hand或cast，不含烧牌/疲劳 | 原手牌current材料或抽到时施放的base材料，复制件创建前设费1 |
| 弗塔根 | 友方随从实际shield_lost，含本体正常失盾 | RandomBuffStoredMinion在执行时随机选本人当前手牌随从+5/+5 |
| 艾瑞达欺诈者 | 本人每次实际card_drawn，含抽到时施放 | SummonByCard带实际本体SummonCause，召唤完整魔蝠；满场仍保留原抽牌 |
| 活化月亮井 | 本人法术整次完成、未反制 | 原PlayRecord.cost决定原来源增攻，不重读后来卡面或用法术伤害代替费用 |

个人施法资格与通用逐次施法事实分开，沿[原生触发契约](m3-reactive-growth-cards.md)。公共持续法强不增加这些随从能力伤害；普通支付、随机、生命周期及死亡仍由既有内核负责。具体费用依据、复制材料政策与前后窗口尚须国服校准。

## 保存原复制材料

CapturedCardCopyMaterial保存SourceAllocationFact、CopyLocalState、组件、武器耐久、预备状态、兆示/青玉材料与原时钟/附件分配上界；不保存另一份GameState或读取后来同名牌。HAND/DECK允许current复制，GRAVEYARD仅允许base。来源离区或换面后，已接受的原材料仍用于新副本；未来时钟、附件/来源编号、未知引用和非法形状在执行及私有帧解码中拒绝。

CopyCard接收该不可变材料并复用原copy_physical_card、copy_current_stored_state、copy_attachments及创建/溢出通知。复制件的完整属性和设费先安装，随后发布创建与入手/烧毁；对方原牌保持。原接口字段布局不变，已有CopyEntryMaterial/CopyLocalState保持；新的私有载体和RandomDamageBatch由受信任mechanics显式注册。

所有经过copy_current_stored_state的普通current复制/变形，都会把原生且原来指向自身的能力来源改绑到接收实体。外部授予的来源保持原归因；原牌与原附件不修改。该规则同时覆盖原CardReference、原MinionReference、保留接收者身份的复制/变形及新材料入口，不能只给某张牌修一个特例。实际卡德加来源的签名和数量规则继续由原模块校验。

现有defining_hand_source等尚无复制生命周期政策的内容继续明确报错；原抽牌事件归一化导致卡面变动时，不猜测复制哪一面。完整实际可达材料仍须逐项接通，不能把普通材料支持宣称为全部复制族完成。

## 不同随机目标与失盾

RandomDamageBatch先筛选当前存活可交互角色，再一次选取不重复目标，交给一个DamageBatch。候选多于要求数量时sample；全部候选均应命中时保留其稳定顺序，不消耗选择RNG；空池保留跳过事实且不抽样。接受后的伤害沿原同时健康/死亡路径，不能把主体改成多次可重复命中的RandomDamage。该抽样与顺序是明确内部政策，官方随机及精确顺序仍待M6。

Silence比较刷新前后的有效圣盾，只在圣盾确实消失时发布一次既有shield_lost。持续贡献仍使圣盾存在时不伪造失去。通知采用沉默后的当前资格；自身/群体沉默的接受先后、光环撤销及自然到期的全部真实来源仍须国服和来源核对。历史[玩家报告](https://www.hearthpwn.com/cards/pt/615012-highlord-fordragon)提供沉默相关线索，不能替代当前国服证据。

## 版本与边界

规则由core-effects-v333保护，schema270及GameState字段布局保持，旧机制身份不能自动认证为新语义。原材料、完整历史、分配上界和待执行工作留在私有帧，玩家只接收原DTO。等待恢复、回滚、clone和回放共用原解释器。

`python -B -X utf8 -m examples.card_trigger_sources`用真实卡牌及玩家命令展示六类来源，并经原心灵咒术师→复制卡德加→鱼人猎潮者路径展示公共复制。实验场景不认证正式套牌或全标准池。年度[核心名单](https://bnetcmsus-a.akamaihd.net/cms/page_media/4w/4W8XOJQ2WAIZ1770082535464.pdf)和[国服轮换说明](https://hs.blizzard.cn/news/24267727/index.html)用于独立核对合法资格；仍需结合固定补丁的有效ID、活动池及后续热修。
