# 冰封秘典的原实体安装与矿脉的原提交材料

[完整原始包](../data/cards/secret-original-sources-v1.json)保留ICC_086冰封秘典、WW_422艾泽里特矿脉的两条原行和四份完整中英文官网主面。它们是标准过去法师来源的实际依赖，不新增标准组牌根。名单保持完整，生产源资格和国服版本另行验收。

## 冰封秘典

InstallDeckSecrets(cast_id, cards=None, used_keys=())要求真实活跃、已开始payload且未失败的原法术CAST。首次接受保存完整原牌库奥秘CardReference，原区域、卡面、控制者和zone_epoch均由既有引用表达。已经生效的奥秘key进入本组排除，后续每一步都沿同一原有序引用集，不把后来插入的牌加入原计划。

每一步调用原secrets.area_count，容量包含奥秘、任务和占用该区域的持续效果；达到上限时停止，余牌仍在牌库。当前已生效或本组已用key不再入选，别名也按同一个SecretSpec.key去重。失效原引用跳过，不能用同名新实体或新驻留顶替。每次从当前仍合格的原物理牌中均匀抽一张，单一候选直接使用、空域不抽RNG；所以物理重复会影响容量不足时的先后权重，这是明确的本地随机政策。

选中后调用原secrets.activate移动同一原牌到奥秘区，保留普通实例分配、去重、容量、生命周期及secret_set通知。既不是新生成替代牌，也不是抽牌、手动出牌或逐张额外CAST；原冰封秘典只有自己一次施法和付款。used_keys继续保存已安装结果，即便某个奥秘在中间反应中被移除，本组也不能再装它的另一张。

每步续接保存完整原引用集和已用key。随机原候选和选择只进入带私有前缀的原事件材料，玩家观察不暴露_deck_candidates、_deck_selected、内部计划或RNG。创建/设置通知中的等待仍沿原解释器恢复、回放、失败原子性执行。原牌库冻结、物理均匀顺序、初始生效key的整组排除、揭示/新插入牌窗口均是本地政策，未冒称国服精确顺序。

## 艾泽里特矿脉

[官方卡页](https://hearthstone.blizzard.com/en-us/cards/101849-azerite-vein/)要求在对手使用本回合入手的牌时复制并设为零费。[公开脏鼠对局讨论](https://us.forums.blizzard.com/en/hearthstone/t/azerite-vain-dirty-rat-interaction/128134)显示复制已在原脏鼠战吼执行前交付；这里采用card_committed窗口，作为有公开依据的本地时点，不升级为全部国服规则确证。

条件绑定原play_id、source_id、player_id、原提交turn和hand_entry_turn，要求对手本次真实手牌提交且本次入手回合等于提交回合。不是按当前手牌扫描、同名卡第一次获得或成功完成后推断；普通本回合抽到/生成/回手再次入手都可满足。原有旧手牌或以前回合取得并一直持有不满足。奥秘与反制仍由既有顺序/实例规则协调，精确相互窗口暂列本地边缘。

CopyCommittedHandCard(play_id, player_id, source_id)从当前解释器队列寻找唯一仍生效的原付款接受证明。非Spell复用FinishPaidHandAcceptance/bind_live，Spell复用FinishSpellAcceptance原付款证明与原绑定检查；读取的是该证明payment_state中的真实HAND实体。不存在证明、借用其它play或原物理来源不符时明确报错，不能退而从后来战场、墓地或当前牌面拼出一份副本。

随后沿原CapturedCardCopyMaterial及CopyCard(current)交付，普通CostSpec(set_to=0)附加零费；全部原局部材料、固有组合和原生法术参数由既有复制生命周期处理，附件重新分配，recipient和copy_origin保持。这样递增点燃的3不会被猜成印刷2，也不会把英雄使用后承接的当前血量当作原手牌属性。未新增PlayRecord字段、全局复制账本或第二套付款/复制执行器。付款前材料的具体附魔与临时期限继承沿既有current复制政策，边缘仍待国服核对。

战吼前、揭示后或复制创建通知中的真实等待仍保留原活跃证明。完整私有证明不进入玩家接口；满手、烧牌、跨玩家、参数校验、RNG与失败回滚使用普通复制/解释器。复制请求离开原接受窗口后不可重新使用已结束的出牌证明。

core-effects-v791/schema615注册两个新Effect，无新payload或状态字段，拒旧1～614；内容constructed-cn37-preview-v693，观察/命令/回放布局保持。两个适配只使用原事件事实与上述公共请求。实际验收、剩余完整来源和下一项只在原两份台账维护；版本/热修及精确规则边缘按用户授权暂缓。
