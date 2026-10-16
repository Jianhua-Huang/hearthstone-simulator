# 亡语快照、原生依赖与区域续接

邪魔仆从CORE_YOD_026使用当前1费2/1恶魔卡面，构筑等价由明确DECK_RULE_COUNT_AS_COPY_OF_CARD_ID56112对应YOD_026。自然死亡读取冻结DeathRecord.attack，主动触发读取原接受随从的当前攻击，不能替换成印刷2攻。空友方随从池无效果/无RNG，单候选直接Buff；多候选复用RequestChoice的sample_size=1、零选择回调，按有序物理候选均匀采样一次，不建立玩家待选。选项身份私下保存明确MinionReference及原攻击操作数，回调核对控制者、卡面、驻留和入场身份，过时目标不改投同名或重入场实体；不让稍后的来源变化替换已捕获攻击力。已有沉默、复制、死亡、回放及玩家边界继续共用公共管线，精确候选/采样和零量政策仍待国服校准。

本页维护接入契约。实际进度、验收证据及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)登记。完整原行、依赖关系与配方见[death-followup数据](../data/cards/death-followup-effects-v1.json)。

卡牌只声明原生deathrattle并组合公共指令，死亡捕获、当前执行方、沉默、重复激活、生命周期、等待和回放由原内核负责。冰喉和邪能响尾蛇通过命名InvokeBehavior在主体执行时读取当前范围，交一次MINION_ABILITY DamageBatch；不把每个目标变成独立死亡批，也不继承法术伤害。冰喉只查询执行者当前物理手牌的实际dragon种族，本体死亡不是“手牌持龙”。

强能箭猪以原DeathRecord.attack固定自然死亡的整笔预算；效果触发仍存活本体亡语时读原捕获来源的攻击，没有虚构死亡事实。SplitDamage每点沿原当前敌人池及RNG选择，种类为MINION_ABILITY；零攻击不消耗随机。不能用法术分摊来添加法伤，也不在随机等待后重读并扩大预算。

紫罗兰魔翼鸦的COLLECTION_RELATED_CARD_DATABASE_ID=564明确引用EX1_277。它仍是旧系列可收藏法术依赖，不因此成为标准根卡；原完整奥术飞弹主体已存在，沿其一次SPELL总预算实现，不重写成三次独立法伤。提里奥·弗丁的同名标签=1730明确引用EX1_383t，完整武器攻击5、耐久3；源health字段在WEAPON上表示耐久，不是随从生命。当前弗丁印刷身材为8/8，不能拿历史6/6覆盖。EquipWeapon沿原装备替换与英雄攻击派生处理。

幽爪熊用原Imbue，按实际执行控制者当前英雄职业映射。梦魇龙裔在原死亡反应后读取当前hand[-1]，捕获CardReference再调用ModifyStoredCost(delta=-2)；空手跳过，选中的旧引用失效不改绑到另一张牌。踏青驼鹿用AddToDeck(position='bottom',cost=CostSpec(set_to=1))创建完整印刷新副本；保留原牌库顺序，费用由原附件维护，不回收原尸体、不复制其临死增益。

`python -B -X utf8 -m examples.card_death_followups`以玩家命令展示原主体与实际生成物，逐稳定位置独立恢复、克隆、回放。场景为混合职业30法力实验，不认证正式标准套牌。原完整数据证明卡面和两个原始标签依赖DBF引用；当前代码与测试证明内部契约。持龙/最右读取窗口、死亡材料、逐点目标选择、附加减费与牌库生成政策，以及正式卡池、热修和精确国服顺序仍待对应M0/M6证据。

## 原生伪装、剧毒、手牌减攻与条件装备

CAP_004伪装的特工声明`disguised=True`和印刷突袭，不重建出牌器。原使用者承担支付、出牌历史和owner；落位方成为controller。亡语只交`Draw(3-ctx.player_id, 2, source_id)`，按死亡或主动触发接受的控制者决定对手，后续转控不借原owner决定抽牌。满手燃烧、疲劳、公开事件、等待和失败事务沿普通抽牌管线；落位/生命期契约见[伪装基础](m3-disguised.md)。

EDR_110孢子尖牙怪声明印刷剧毒。命名InvokeBehavior在主体实际执行时重查完整当前敌方活跃存活随从，交单个`RandomDamage(..., 1, source, MINION_ABILITY)`。不是法术伤害，没有英雄候选；剧毒由原伤害包保存来源关键词及共享伤害层处理，圣盾/免疫阻止实际生命伤害时不因剧毒额外消灭。来源自然死亡后仍沿其实际来源身份；主动触发无需制造死亡记录。空池不消费RNG；非空沿原RandomDamage规则使用一次物理候选抽样，单候选也沿相同入口，不另造卡牌随机器。

EDR_495扭曲的树人依次交给实际执行控制者、另一玩家各一个`RandomBuffStoredMinion(attack=-2, source_id=...)`，各自在执行时重查自己的物理HAND随从池。同名两实体各一个权重，不抽法术、不从完整物理池删除未实现定义、不建立玩家选择；空池跳过，非空复用原采样（含单候选）。只改原实体攻击附魔，攻击显示钳制及后续入场复用原属性层，不改生命或费用。该先后顺序、候选与RNG消费属于当前内部契约，仍待精确国服校准；私有引用和对方牌面不进入玩家DTO。

END_002邪恶荒裔怪声明印刷复生，并经命名InvokeBehavior在原死亡反应/等待后检查实际执行方当前weapon_id。有武器时对同一物理武器`ModifyWeapon(attack=2)`，保留耐久和已消费攻击；无武器时`EquipWeapon('CS2_082')`。自然亡语、后续复生及第二次死亡共用原生命周期；沉默同时移除原亡语与复生。官网[卡牌目录](https://hearthstone.blizzard.com/en-gb/cards/121057-wicked-blightspawn/)给出两张Wicked Knife关联，冻结的[国服完整目录原行](../outputs/card-integration-20261014/k37-native-death-followups-preaudit.json)明确child_ids为485、46054，固定37.0源分别解析为CS2_082和CS2_082_H1，均为1费1攻2耐无主体武器。前者复用既有定义，后者作为完整关联定义注册；默认装备选择原CS2_082，不按中文名猜依赖。具体外观映射及国服装备窗口不由目录关联证明，继续保留M6边界。

`python -B -X utf8 -m examples.card_native_deathrattles`通过玩家可见合法命令演示四种效果，各稳定位置使用独立注册表恢复、clone和回放。它使用短牌库、显式法力及混合职业实验配置；实际测试范围、结果与剩余项仅在两份台账维护。

## 抽到的龙、牌库顶部与对手手牌

EDR_572受难的恐翼巨龙交两次`DrawMatchingWithCostReduction(..., reduction=1, query=PoolQuery(kinds=(MINION,), tribes_any=('dragon',)))`，第二次重查实际牌库。筛选采用原印刷/全部种族元数据；从完整物理匹配池采样，保留同名实体权重，不取牌库顶的近似对象。每次减费绑定该次实际抽取的hand到达引用，额外抽牌不改投目标，离区再返回的旧引用失效；燃烧/未成功到手没有减费，空匹配不疲劳。公共入口和恢复边界见[原抽牌续接契约](m3-spell-sequences.md)。

TLC_621固执的守护者声明印刷嘲讽，并在命名InvokeBehavior执行时捕获当前本人deck[:3]的完整CardReference，交一次`DestroyDeckBatch`。先按原批次迁出最多三张，再发布原销毁反应；不抽牌、不弃牌，不给被销毁的随从执行战吼、场上亡语或复生。空/短牌库只处理实际存在对象，不产生疲劳。该批次边界和实际读取窗口仍是内部政策，待精确国服校准。

TLC_244好奇的探险者按执行控制者的对手交`RandomBuffStoredMinion(cost=CostSpec(delta=-2))`，复用完整当前HAND随从候选、原物理权重与费用附魔；不增加攻击/生命，不让行动者选择隐藏手牌，不修改对方其他牌型。空池无RNG，非空沿既有一次随机入口。后续转控、重复主动触发、最低费用和实际付款继续由共享层处理。

`python -B -X utf8 -m examples.card_zone_death_followups`演示真实龙牌抽取/减费/付款、牌库顶批量销毁后抽取剩余原牌，以及对手使用原减费手牌。源行和内部执行证据不认证正式合法池或国服一致性。JAIL_733的固定JAIL_732引用同时由原DISPLAY_CARD_ON_MOUSEOVER和国服目录child_ids证明；虚空灵魂自身涉及持续升级及完整恶魔生成池，其[完整候选依赖调查](../outputs/card-integration-20261014/k38-void-soul-dependency-audit.json)保留全部候选和未实现定义，未裁剪成可运行子池。两张牌的具体接入、验证与下一项仍只由两份台账登记。

## 原生亡语资格、复活与同一主体的复制

EDR_891贪婪的地狱猎犬用DeathQuery的原印刷费用≤4及显式deathrattle_basis='printed'；EDR_892残暴的魔蝠用原印刷费用≥5、相同原生亡语资格，以及PoolQuery.exclude_source排除死亡来源的同一卡牌身份，不只排除本次尸体。友方按死亡时controller，变形按实际死亡卡面，原生亡语被沉默仍有资格；普通白板仅被授予亡语不因该授予进入池。[公共资格/官方依据](m5-resurrection-followups.md)与旧at_death默认语义分别保留。

两者均交一次Resurrect(count=1, distinct='death', source_id=实际亡语载体, cause=SummonCause.capture(ctx))，保留每次物理死亡的权重，空池和满场沿原接受政策。复活返回原基础卡面与组件，不继承死亡前普通属性增益，不执行战吼；成功续接绑定真实新实体。回调经primary_resurrected_body确认原首主体后交一次带真实cause的CopyMinion(mode='current')，因此原召唤反应后的有效增益进入复制，额外召唤或战场末尾的无关随从不会替换目标。目标在召唤反应中死亡、转控、离区再回或变形时沿原续接失效检查跳过。

“复活后复制”两个请求分别沿原数量生产者处理，额外复活体不为第二句再发一份复制请求；当前真实卡德加的内部契约为两复活体、两复制体。原复活与复制间的接受窗口、数量来源变化、首次主体失败和精确服务器口径仍待M6，不能凭内部数量用例认证官方一致。`python -B -X utf8 -m examples.card_demon_dependencies`以真实命令展示这两张和两张结束恶魔，各稳定位置独立恢复、clone和回放；实验牌组不是正式标准构筑证书。
