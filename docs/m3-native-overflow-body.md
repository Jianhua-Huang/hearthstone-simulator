# 溢出卡牌的原生被摧毁主体

本增量接通既有存储、创建和失败交付的溢出路径，复用[存储销毁的原生主体](m3-stored-card-destruction.md)。实际进度和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

原card_burned通知保持，内部新增不可变burn_destruction封套，保存原SourceAllocationFact、profile、实际接收者和turn。Event继续保存实际sequence/action/source。CardDestructionRecord.card可为原CardReference或SourceAllocationFact；player_id统一表示主体执行方，after_epoch表示本次完成退役后的修订。context.destruction仍是同一个纯查询，无新状态账本。

| profile | 原前态 | 完成条件 |
| --- | --- | --- |
| explicit | HAND/DECK捕获引用 | 原显式销毁，epoch推进1 |
| stored_overflow | HAND/DECK原物理分配 | 满手交付失败，保owner、按目的接收者更新controller，epoch推进1 |
| created_overflow | 原新建GRAVEYARD分配 | 原epoch0、原最后分配ID，保持epoch0，不伪造此前手牌或牌库驻留 |
| setaside_overflow | 原SETASIDE驻留 | 获取或原手恢复失败，epoch推进1 |
| graveyard_delivery_overflow | 原GRAVEYARD材料 | 既有材料返回失败，新的退役epoch推进1，不伪造第二次弃牌或场上死亡 |

共享emit_burn核对原分配、当前完成后的墓地实体、接收者及真实手牌容量；已有生产函数提供各自实际前态。它不负责重新创建或移区。牌库抽取、手牌转移、生成、当前/印刷复制、衍生、发掘、裂变碎片、临时创建、虚空获取、原手恢复与弃牌材料失败返回都沿各自原流程，在完成失败交付后发布收据。

Resolution.emit在原burn监听之后接受本牌on_destroyed，复用原捕获上下文和解释器。执行者为完成退役的物理卡和接收者，不继承交付者的cast/play/draw/discard根。普通抽取/创建/获取记录保留；本次溢出自身不产生额外弃牌、出牌/施法、DeathRecord、亡语或残骸。主体Draw等后续效果仍产生各自真实事实，包含进一步溢出、独立原生主体及普通疲劳，受原结算预算约束。

未分类、没有原始收据的native burn继续明确报错，防止漏执行。场上随从满手回手保持[B152普通死亡](m2-full-hand-return-death.md)，不接入上述存储主体；未有真实需求的场上on_destroyed声明不在本域。显式存储销毁保持原入口。当前和印刷复制保留各自既有来源与独立附件政策，没有动态授予或“机制＋机制”矩阵。

收据解析严格检查声明字段、类型、区域、分配边界、owner/牌型/接收者与epoch。原生上下文校验完整退役身份、原印刷能力、独立根和实际事件；同一保留物理退役不能发布两次。等待、事务回滚、独立注册表恢复、clone和replay使用原管线。玩家观察和事件不提供burn_destruction、分配计数或完整规则状态。结构校验不认证未签名存档来源。

prototype-v282/core-effects-v276、schema247拒旧1～246。公开事件种类和形状保持player-view-v82、命令12、replay1；默认注册表指纹保持，无新运行模块或持久字段。

必要新代表仅[固定WW_441锅炉燃料](../data/support/native-overflow-body-basics.json)，使用既有完整Draw(2)主体。相关原生声明、主体与源卡范围保持隔离；没有新增WW_044t伤害、SC_408条件或源卡组合。过抽触发具有历史社区观察线索；其他溢出主体归属、事件窗口和源类别按本地公共政策实现，准确国服语义仍须M6校准，不能据绿测宣称官方全生命周期一致。

[专项](../tests/test_native_overflow_body_basics.py)覆盖过抽、创建、接收归属、复制、临时创建、连续本牌溢出、暂存获取/原手恢复、墓地旧材料、两类等待、回滚、分配封套篡改、重复退役、未分类来源及玩家隔离。原[B150边界专项](../tests/test_stored_destruction_basics.py)将已实现来源的旧拒绝断言更新为实际抽取与正常续行，其他检查保留。实际结果和首次失败记录见[本批证据](../outputs/native-overflow-body-basics-20261012/verification.json)；其他旧检查及阶段全量未执行。
