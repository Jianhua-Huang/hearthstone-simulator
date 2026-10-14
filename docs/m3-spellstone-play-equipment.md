# 法术石的出牌和装备资格

四个独立条件分别复用已存在的不可变PlayRecord、接受时卡面和weapon_equipped事实，不增加内核模块、事件、字段或组合规则。运行身份保持`prototype-v167` / `core-effects-v167`、schema162（拒旧1～161）、观察71/命令10/replay1。实际执行、结果和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 分别读取真实发生的事实

红宝石、翡翠与黑曜石（英文Onyx，早期台账称缟玛瑙）监听普通card_played。资格通过事件play_id读取completed的原PlayRecord，并核对原来源及出牌玩家；不使用来源后来在场上的控制权、种族或能力。card_played目前在主体完成后发出；被反制但完成的付费手牌也产生该事实。这里明确采用这一内部窗口，精确官方先后、获取时机和所有特殊来源仍待M6。

| 独立条件 | 每级门槛 | 资格与排除 |
| --- | --- | --- |
| 红宝石 | 打出2个元素 | 原MINION卡面匹配elemental；召唤与非随从法术不计，未知随从种族仍报错 |
| 翡翠 | 打出1个奥秘 | 原卡面具有SecretSpec；SetSecret及普通法术不计，被反制的真实奥秘手牌按当前窗口计入 |
| 秘银 | 装备1次武器 | 本人实际weapon_equipped，手牌或效果装备均计；初始场景武器、属性修改不补次数，替换是另一次装备 |
| 黑曜石 | 打出3张亡语牌 | 原卡面具有印刷亡语声明；死亡次数、亡语执行与召唤不计，不误写为击杀3个随从 |

秘银只用已经发生的装备事实。普通反应随后移除武器不抹除这次装备，不要求来源在进度处理时仍占武器槽。三个出牌条件同样不受普通反应随后变形影响。这里没有扩展特殊手牌授予、任意载体或跨机制计数。

每个真实事件提供一个单位见证；同一物理出牌的card_committed、入场/装备和card_played不被混为多次合格行为。原手牌进度负责去重、连续形态和完成后停止监听，见[进度契约](m5-hand-progress.md)与[升级契约](m3-spellstone-progress.md)。

## 必要代表与明确缺口

[二十条完整raw/pin](../data/support/spellstone-play-equipment.json)保存十二个形态及火羽精灵/烈焰元素、麦田傀儡/损坏的傀儡、法术反制、炽炎战斧、狼和秘银魔像。PIN为`a6502a776924dfef1f85a03169a7de7847b4dc0d60c4a2fe938ff49546351342`。狼为本地LOOT_077t的3/3野兽，秘银魔像为LOOT_203t4的5/5；准确来源关联仍待正式可达池核对。

代表适配仅存在于隔离专项注册表，生产代表64/合成3保持。火羽精灵的真实战吼给烈焰元素；麦田傀儡的真实亡语给损坏的傀儡；法术反制和战斧走已有奥秘/装备流程。翡翠召唤2/3/4个狼，秘银召唤1/2/3个魔像；黑曜石以公共RandomDestroy选择1/至多2/至多3个原敌方候选，空/不足候选、随机与回放由既有处理器执行。精确随机接受窗和来源政策待M6。

红宝石的资格及形态可验证，但其完整随机法师法术主体需要M0正式目标池。本实验的三形态主体明确抛出ResolutionError并整动作回滚；没有缩小池、剔除未知牌或使用白板主体。随机生成公共能力已存在，完整Ruby主体和正式池仍开放，不能借资格通过宣称整张牌或U32整族完成。

本地完整行确认主体、门槛与元信息。官方[红宝石](https://hearthstone.blizzard.com/en-us/cards/43414-lesser-ruby-spellstone)、[翡翠](https://hearthstone.blizzard.com/en-us/cards/43363-lesser-emerald-spellstone)、[黑曜石](https://hearthstone.blizzard.com/en-us/cards/46296-lesser-onyx-spellstone)及[秘银](https://hearthstone.blizzard.com/en-us/cards/46063-mithril-spellstone/)此次抓取只返回目录布局，不作为完整国服窗口证明。场景不证明混合职业卡组合法。

## 生命周期与隔离

后获得不补过去次数；非手牌区暂停，返回保持部分进度。current复制保留原见证，base复制清空进度。普通升级保留物理/进度链身份，clear_local是明确的实验费用政策；最后一级停止监听。回合边界不重置Ruby的未完成次数。

等待探针使用普通装备进度的on_complete；独立注册表恢复、clone、选择继续和回放复用一次装备及见证，不给真实秘银编造选择。坏资格返回在实际支付/装备后报错，整个动作回滚。玩家只见现有进度摘要，对手隐藏手牌及原记录/见证不泄漏。冻结事实与结构一致性不认证未签名存档来源。

可审计输入见[证据](../outputs/spellstone-play-equipment-20261010/verification.json)及[逐方法接受来源](../outputs/spellstone-play-equipment-20261010/accepted-evidence.json)。未执行的既有回归不作本次通过声明。完整来源、类别/生成池、H2、M0/M6/M7及全部基础目标保持开放。
