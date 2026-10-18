# 威拉诺兹：起始费用条件与牌库属性均分

CATA_213的6费6/6中立元素原生战吼复用DeckMinionCostSumCondition(100, printed)。条件读取真实构筑开局的原始随从印刷费用之和；不是剩余牌库费用，也不从当前报价或任意Scenario补造起始事实。完整源、双语官方主面和两条仅作证据的原附魔行见[data/cards/deck-stat-distribution-v1.json](../data/cards/deck-stat-distribution-v1.json)。未知起始事实仍明确报错。

原始问答明确说明[成对均分](https://www.reddit.com/r/hearthstone/comments/1rew1ai/comment/o7giwai/)及[随机余数](https://www.reddit.com/r/hearthstone/comments/1rew1ai/comment/o7j3il3/)。因此总量100是50攻击加50生命：2个随从各+25/+25；7个随从中6个+7/+7、另1个+8/+8。不是每牌+100/+100，也不是100次独立随机增益。原帖说明数值分配，不证明国服37.0的精确随机流或微观事件顺序。

DistributeDeckStatPairs(player_id, pairs, source_id)只处理当前本人牌库中的物理随从。每个实体占一个位置，同名牌不合并，非随从和对手区域不参与；按当前物理控制者归属。一次接受完整有序候选，先给每牌floor(pairs/n)对，再用同一随机源无放回选pairs%n个原实体各多给一对。空池或可整除不消耗RNG；卡牌使用pairs=50。

属性与附件仍由原BuffStoredCard、attachment_id及refresh_entity处理。有限内部通知缓冲使整组普通增益全部应用后才发出第一个stored_card_buffed通知；不实现第二套属性层。每个正增益原实体获得一份普通附件及一次合并攻血通知。后续反应中抽出、转交或新添卡不重新分配已接受预算；重复战吼各自重查当前牌库。通知粒度与接受窗仍是待M6核对的内部政策。

普通抽牌和current复制保留原材料，复制附件有独立ID，区域/变形等继续依已有生命周期规则。来源在通知反应中死亡不撤销已完成的增益。事务异常回滚及选择暂停由原解释器负责；不新增游戏状态、实体、卡牌声明或存档字段。

私人deck_stat_pairs_distributed记录原完整分配事实：物理候选、余数选择、实际附件ID、RNG前后状态及普通增益通知的相对位置。局部重演校验均分、余数及RNG；实际通知须对应同一来源、玩家、目标和数值，不得重复借用。允许后续正常操作推动RNG，记录的历史物理材料不要求始终留在原牌库。完整候选及RNG事实不投影给玩家。该内部收据用于检查保留历史的一致性，不提供未签名外部存档的来源认证。

引入core501/内容preview-v319。保存布局schema412、观察95/命令12/replay1保持，原引擎身份校验区分新效果。M0正式补丁/热修/合法池、精确国服校准、全部可达及发布仍单独开放，实际验证及下一项只在原两份台账维护。
