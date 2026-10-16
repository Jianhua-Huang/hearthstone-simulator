# 有限当前条件的固有费用

真实END_033先觉蜿变幼龙、TIME_022累世巨蛇和TLC_819林歌海妖分别需要当前手牌其他龙、场上存在休眠随从、当前回合本人施放过神圣与暗影法术。完整固定卡面保存在[配方](../data/cards/presence-cost-effects-v1.json)，卡牌声明不自行维护可变减费缓存。实际执行、验证与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

## 复用固有费用管线

原IntrinsicCostSpec增加三个有限condition，仍进入原intrinsic-before-local阶段：

| condition / history_profile_id | 声明与依据 |
| --- | --- |
| hand_other_dragon / hand.current-other-dragon-v1 | 一次负delta；当前本人完整手牌，当前种族，排除物理定价主体ID |
| board_dormant_minion / board.current-dormant-minion-v1 | 一次负delta；双方完整BOARD，真实随从dormancy存在 |
| turn_holy_and_shadow / cast.current-turn-holy-shadow-v1 | 一次固定set_to；原完整施法前缀，本人本全局回合已接受成功主体包含两种派系 |

只支持一个普通物理MINION条件规则，未知profile、其他形状、混合数量公式明确拒绝。本地附魔、外部修正、最终下限及原资源账户继续按公共报价与付款顺序执行。

虚拟生成预览不创建或插入实体，source_id=None；现有真实手牌仍可满足其他龙条件。物理报价只排除实际subject ID，两张同名龙互相满足，手牌之外和对方手牌不满足。本人手牌种族取当前注册卡面及原种族附魔，ALL及排除沿原tribe_state_for处理；未知后续随从种族不会被前面的真值隐藏。

休眠读取entity.dormancy，不把地标不可攻击或其他inactive状态当作休眠。双方真实BOARD逐物理槽保存，休眠随从苏醒后重新报价。该条件没有另建休眠时钟或保存第二份生命周期。

神圣/暗影使用原SpellCastRecord通过既有row_for投影，保存完整有序前缀及注册卡面派系。hand、repeat、effect、draw、history起源都按实际caster、当前全局turn、payload_started且failure=None判断；仅尝试、被反制和失败自动目标不满足。这个接受信用与反制政策是明确内部口径，精确国服仍待校准，卡文不能证明所有起源边界。

## 原事实、保存与信息

CostPresenceMatch是原condition_facts向量的一个有限typed变体，保存payer/条件/turn/action/原实体和附件分配界/物理subject，以及对应的完整hand、boards或cast_rows。各条件未使用的容器必须为空。CostPresenceRow保存原物理身份/控制者/区域/epoch/进入顺序、实际休眠和原种族附件；不从卡名或最后一个场位推断事实。

报价、合法操作和实际付款绑定同一物理subject；虚拟报价明确拒绝借用物理主体。纯验证重新计算注册类型、种族、派系和聚合；原窗口重捕获全部当前依据，因此同价也不能裁剪未匹配行。紧凑历史允许后来区域、种族和休眠状态合法变化，并验证原分配界及原施法前缀，不能拿后来施法替换已接受价格。

条件事实沿公共typed codec、JSON解码、付款前完整边界、选择恢复、克隆、回放和异常回滚处理。卡牌付款后即使另一张龙离开手牌也不重新付款。内部手牌/场面依据、完整施法前缀和附魔材料不进入玩家观察；公开当前价格沿原投影显示。

没有GameState/Player新字段或第二种费用结算器，原字段布局和已有条件变体保持schema267。新声明、typed变体与执行语义由core-effects-v311及完整注册表身份保护，旧mechanics不被静默接受；观察85、命令12、replay1和规则302保持。完整标准池、其他条件、精确国服派系/时序与热修继续按主台账推进。
