# 按本局弃牌数量持续增加自身攻击力

独立基础契约 B49/U59。扩展原 `StatRelationOperand` 的 `CONTROLLER_DISCARD_COUNT`，由原 `StatRelationSpec` 声明 `ATTACK / CONDITIONAL_ATTACK / 正整数amount`。这是本体的连续数值关系；实际进度和验证只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

```python
StatRelationSpec(
    operand=StatRelationOperand.CONTROLLER_DISCARD_COUNT,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,
    amount=1,
)
```

原 `conditional_attack(state, entity)` 以当前控制者查询[不可变成功弃牌历史](m3-discard-history.md)，贡献为历史长度乘以正整数系数。计数包括原成功弃牌的各可玩类型，不按牌名或物理 ID 去重；烧牌、出牌、死亡、普通移动和复制不增加计数。没有新计数器、表达式图、统计执行器或出牌动作，不扫描宿主日志。

只接受普通、非融合随从的原生声明，附件必须是未消费、无期限、可沉默的 printed 来源；既有 `GrantStatRelation` 仍只支持原自身生命关系，不扩展新的条件授予。重复原生声明和多装同一附件明确拒绝，未知/错误类型、层、目标和数值不能静默忽略。

数值写入原 `Entity.conditional_attack` 派生整数；原 `derived_attack` 在普通数值与外部光环之后相加，随后执行零下限。刷新不写入基础攻击、永久增益或已准备伤害。无需持续持有这张牌：后来获得、抽取、召唤或重新安装原生声明会读取完整本局历史。

原事件规范化在弃牌事实提交前运行；因此原 `Resolution.emit` 在实际成功弃牌提交之后，调用同一纯数值缓存刷新，再捕获原监听。它不生成事件、分配身份或推进 RNG，不执行第二次弃牌，也不改变原死亡检查点。原始 `card_discarded` 字段和空 data 保持，普通监听和真实待选工作各自保留捕获时的数量与攻击，不能用今天的历史重算昨天的上下文。

沿原 native 活动政策，`Entity.active` 的资格不按区域限制，手牌、牌库、战场以及普通墓地实体中的原生声明均计算当前值；休眠、惰性与星舰建造期间无此贡献。此范围和当前 controller 是本地政策，精确国服显示/资格仍待 M6。死亡记录已冻结的攻击及附件不随未来弃牌变化。

沉默移除本体关系，之后弃牌不使它重新出现。当前复制保留原生关系身份并分配新附件，按接收者当前控制者重算，不烘焙源卡派生整数；沉默当前复制保持移除。基础复制、回手、变形安装与重置沿原生命周期。转控立即使用目的方历史，既有弃牌归属不改写。休眠时原基础攻击仍在，唤醒重新读当时历史。原攻击接受、准备伤害、次数、反击与关键词共享，不为数值成长退还攻击次数。

快照和捕获状态沿原实体格式，模型与 `FrameCodec` 在各自原状态域校验这个派生值，拒绝陈旧、布尔/浮点/缺失或伪造数值及不同原生声明；私有一致性不认证未签名存档来源。没有新增 GameState/Player/Entity/CardDefinition 字段、Effect、事件或外部命令。当前 `prototype-v206 / core-effects-v200 / schema194` 拒旧 schema1～193，观察74/命令11/replay1保持。玩家只看到原当前攻击与合法操作，不收到公式、弃牌历史或全知工作帧。

仅鲜血女王兰娜瑟尔 `ICC_841` 完整本地[raw/pin](../data/support/discard-count-attack-basics.json)，pin 为 `17336a1c3b3a464564fdb1694e635d0b1274999686e1b1b07f73e4d74b466cc2`；隔离实验定义保留5费1/6、术士传奇亡灵、原吸血及本体关系。生产代表包和正式池未加入这张牌。[官方卡库](https://hearthstone.blizzard.com/en-us/cards/43064-blood-queen-lanathel/)支持吸血及每张本局弃牌带来+1攻击；卡文不证明精确控制者、活动区域、刷新/死亡/准备窗口或国服热修。

完整 U59、历史返还材料、具体伤害条件、其他基础缺口、H2/M0/M6/M7仍开放；不建立任意历史条件、授予或卡牌组合矩阵。
