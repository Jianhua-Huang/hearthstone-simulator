# 条件法术：手牌边缘、传说载体与原伤害结果

本接口由固定卡面的CORE_CS2_072、CORE_BT_801、CORE_BAR_311、CATA_203、CATA_303、CATA_308实际需求推动。完整源行与审核配方在`data/cards/conditional-health-effects-v1.json`，仍只组合原伤害、生命、支付、交易、随机分摊与死亡流程。

## 固有费用

`IntrinsicCostSpec(condition='hand_edge', set_to=1, history_profile_id='hand.current-edge-v1')`保存本人完整有序物理手牌和原来源。原来源位于首位或末位时成立，单张手牌也成立；虚拟生成报价没有物理位置，不借用手中另一张同名牌。付款前按原窗口捕获，之后移区或取得新手牌不重算已接受金额。

`IntrinsicCostSpec(condition='controlled_legendary', set_to=1, history_profile_id='controlled.current-legendary-v1')`检查本人实际控制的在场卡面。现有`CostPresenceMatch.boards`在这个条件下保存两座位的在场载体清单，只有付款方座位非空：英雄、英雄技能、随从/地标场位、武器、奥秘和任务。每行明确保存真实Zone，不能拿手牌、牌库、墓地、待用法术或墓地来源的独立玩家效果充数。其他既有presence条件仍严格使用原HAND/BOARD域。

控制条件比较当前卡面定义的印刷稀有度，沉默不改变稀有度，休眠仍由本人控制；控制者、离区、变形与移除由原物理区域决定。原完整行、分配前缀及true/false事实进入唯一固有阶段，不设第二个费用缓存。所有相关载体先验证再聚合，不能找到一个传说后跳过后面的未知数据。固定费用先于本地及外部修正，因此准备等原修正仍可把1费降到0。两个新增条件仅供普通手牌法术使用；不顺便放宽其他载体或混合公式。

社区对局报告明确观察到场上的任务使麦迪文的胜利维持1费，支持不能只查传说随从。[任务实际报告](https://us.forums.blizzard.com/en/hearthstone/t/the-changes-will-not-fix-priest/159225) 其余统一载体、休眠及虚拟报价政策沿本地属性/区域模型表达，尚不等于国服精确证据，仍待M6校准。

## 印刷稀有度与无稀有度

`TargetPredicateSpec(printed_rarities=(Rarity.LEGENDARY,))`供CATA_203选择真实传说随从；目标域与可选中保护仍由原TargetSpec负责。条件读取已保留卡面ID对应的注册定义，属于可恢复的内核筛选，不调用全知自定义规则。

`Rarity.NONE`表示完整审核源行已确认的“没有RARITY标签”，与仍然未知的`metadata=None`或`metadata.rarity=None`分开。构筑包解码已知非收藏无标签记录，并以本批79份完整当前原行，对默认代表包中对应无标签实体做明确的可选细化；所有定义与池声明使用同一个解码器。默认历史代表包不传这项名单，其完整指纹保持。没有源证据的未知元信息仍报错，不静默当作普通随从。

新增筛选为空时不进入旧注册表指纹材料；非空声明进入指纹。没有新增CardMetadata字段或保存布局，旧声明和原未知值语义保持。无稀有度不是“免费”稀有度，也不能据此宣称整个正式卡池已审核。

## 原结果的下一结算阶段

`hs_sim.engine.health_followups.InvokeHealthResult(behavior_id, event)`接受一个真实、带来源的health_resolved事件。执行时核对事件完整内容与当前游戏原事件位置，保留原HealthResult及来源，在当前状态上调用纯主体；不存在或伪造事件报错。数据进入原类型化工作队列与FrameCodec，不藏在可变闭包中。

CATA_303先执行SPELL伤害，通过该入口在普通死亡/反应之后读取原事件。内部政策要求原选择对象实际成为本段伤害或剧毒的死亡记录，完整DeathCause.result与原HealthResult相等；重定向到其他对象不冒充原目标死亡。原死亡之后的复生新体不撤销已经成立的死亡。非致死、圣盾或失效目标不恢复敌方英雄；恢复仍是普通SPELL治疗，走原治疗规则。该具体死亡因果窗口及交互仍待国服校准，不能把单纯血量归零当作已经发生死亡。

CORE_BAR_311直接复用`RandomSplitDamage`，只把scope设为敌方MINION，并保留原吸血声明；原一次法伤预算、逐段单位伤害、空池停止、随机、反应与等待保持。CORE_BT_801同时声明真实OUTCAST关键词与手牌边缘费用，不能只补价格而遗漏可查询关键词。CATA_203的可交易复用原HandActionSpec，不造重复关键词。

core319保护新语义及效果类型，schema268、玩家观察/命令布局保持；原时序与官方池完整性仍独立验收。实际进度、测试和下一项仅维护在两份执行台账。
