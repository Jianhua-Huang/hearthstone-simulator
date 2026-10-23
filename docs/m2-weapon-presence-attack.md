# 装备武器时自身持续增加攻击力

独立基础契约 B36/U22。扩展原 `StatRelationSpec`、[属性查询](../hs_sim/engine/stats.py)和[属性关系模块](../hs_sim/engine/stat_relations.py)，复用[装备谓词](../hs_sim/engine/equipment.py)及原事件、战斗和生命周期。实际执行和下一项只维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。

## 声明与数值层

```python
from hs_sim.engine import StatRelationSpec, StatRelationOperand, StatRelationLayer

while_equipped = StatRelationSpec(
    operand=StatRelationOperand.CONTROLLER_HAS_WEAPON,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,
    amount=2,
)
# 普通随从 CardDefinition(..., stat_relations=(while_equipped,))
```

这个闭合操作数只表示当前控制者装备武器时，本体拥有声明的额外攻击力。攻击目标、条件层和严格正整数 amount 必须完整；错误类型、未知操作数或错误层明确拒绝。既有受伤加攻与最终自身生命关系保持原语义，没有任意条件表达式图。

仅可沉默的印刷普通非融合随从：原生附件须有来源、未消费、无期限、无磁力归属，并与原卡面完整声明及数量匹配；重复原生附件拒绝。`GrantStatRelation` 仍只开放原自身生命关系，不新增武器条件授予。

当前控制者的当前武器槽通过原 `equipped_weapon` 判断：耐久大于零且未标记销毁。零攻击武器仍满足，敌方武器不满足，条件不依赖当前行动玩家。来源 ID 只作身份记录，复制和转控后不读取原来源的装备。

新增 `Entity.conditional_attack` 派生整数，由纯 `conditional_attack(state, entity)` 计算 GameState 依赖。它与原印刷/有序数值附魔、外部属性光环及本地受伤条件分别保存；在原条件攻击层加入数值，再执行零下限。没有永久 Buff、反复叠加、玩家累计量或另一套属性执行器。原最终自身生命层仍优先；本项不扩展组合矩阵。

例如原1攻击的蹩脚海盗有武器时为3，失去武器回到1。普通攻击设为1后仍为3；普通攻击被减到-1时，有武器为1、失去武器为0。原属性交换先保存旧攻击和生命再设值，持续贡献随后仍按当前装备计算；不会把它变成新的永久附魔。

## 刷新、战斗和生命周期

原完整光环刷新在生命光环钳制后计算自身贡献；原事件前规范化只更新这个自身缓存，不提前重选旧外部来源。装备、损坏、替换、沉默、换形和转控的冻结上下文可以读取当时攻击力，没有新事件、随机或分配。

来源活跃资格沿用 `active_abilities`，休眠和非活跃建造状态不生效，唤醒按当前装备重算。手牌、牌库和墓地本体显示沿用既有区域/活跃政策；国服精确显示仍待核对。死亡记录保存原窗口最后攻击及完整附件，不用今天的武器重新定价历史死亡。

沉默撤销原生贡献。当前复制保留原印刷来源并分配新附件 ID，按目标控制者装备重算；沉默当前复制不恢复能力。基础复制、回手和变形复用原重置，转控立即改读新控制者装备。手动出牌与召唤安装同一声明，此数值条件不授予冲锋，新随从继续受召唤限制。

武器的最后耐久磨损、替换和销毁复用原装备/死亡管线；反复失去和装备不会退还随从已用攻击次数。原攻击声明待选结束后、伤害准备前读取当前攻击；已经完成或准备的伤害包沿原政策保持。本项不修改攻击执行器、磨损或战斗窗口。

## 保存和玩家边界

派生整数进入实体、快照及冻结工作上下文的完整格式。缺失、布尔/浮点/负量或陈旧数值、非原生声明和重复附件明确拒绝。模型与 FrameCodec 在每个捕获状态自己的装备域校验缓存，不能用当前装备覆盖原上下文；该检查不认证未签名历史的来源。

当前 `prototype-v201 / core-effects-v195 / schema189` 拒绝旧 schema1～188；观察74、命令11、回放1保持。没有新 CardDefinition/StatRelationSpec 字段、GameState/Player 字段、事件或外部动作。原普通47定义及指纹保持，Entity 新派生值明确改变保存格式。

玩家只看到当前攻击和合法操作，不返回 `conditional_attack`、公式、附件或全知工作帧。选择恢复、clone、独立注册表回放与异常回滚复用共享管线。

## 必要代表和证据

仅 `CFM_325` 蹩脚海盗完整本地 raw/pin [证据包](../data/support/weapon-presence-attack-basics.json)，pin 为 `4b31bff8448b2b17fd07773f1e3709edd6d1a1494971bf9ac22c0c1fd506ea7d`。1费1/2、中立稀有海盗，仅隔离实验适配；WON/CORE_WON 同文卡面只作静态证据，不据名称判断当前国服正式身份或合法性，生产代表包未改。

[官方卡库索引](https://hearthstone.blizzard.com/en-us/cards/127089-small-time-buccaneer/)支持装备期间自身+2攻击，直接页面仍是动态壳。[2018-11-05官方修复说明](https://hearthstone.blizzard.com/en-us/news/22596834/11-6)支持属性交换后仍有这项增益；只验证原 SwapStats 数值原语，没有额外接入虚空撕裂者或展开卡牌组合。历史说明不代替目标补丁的国服校准。

精确装备/事件/死亡/攻击接受与准备窗口、数值层及非活动显示仍待M6；其他条件、特殊授予/融合、U22整族、其他基础缺口、H2、M0正式池、M7批量接卡与整个基础目标继续开放。

原生种族受益筛选见[独立冲锋光环契约](m2-tribal-keyword-aura.md)；本页既有自身条件和数值政策保持，新选择器不扩展本页条件授予范围。

原生当前种族的持续属性筛选见[独立属性光环契约](m2-tribal-stat-aura.md)。本页既有条件和生命周期政策保持，未扩展授予或条件组合。

原生当前种族的持续费用筛选见[独立费用光环契约](m2-tribal-cost-aura.md)。本页既有数值/关键词和生命周期政策保持，未扩展授予或条件组合。


## 控制机械时自身持续加攻

真实GVG_013使用原StatRelationSpec，新增闭合CONTROLLER_HAS_MECH操作数，配合CONDITIONAL_ATTACK和正整数amount。原MinionScope的BOARD/current纯查询检查当前控制方活跃存活的当前机械；当前变为机械的自身可满足，多机械只给一次声明量，敌方/休眠不满足，未知当前种族明拒。没有任意条件/种族表达式或新的Buff执行器。

只开放普通非融合随从的原生声明，原面、数量、重复附件和缓存校验沿旧路径；GrantStatRelation不开放这项授予。沉默、变形、休眠/唤醒、复制/转控与攻击待选后的准备窗口共用原生命周期/属性刷新；复制按接收者机械状态重算，普通数值设值不消除条件层。

无新State/Entity/Spec字段或帧类型，conditional_attack和完整StatRelationSpec原布局保持schema547；新语义由core-effects-v686与注册表/机制签名保护。玩家只见最终攻击，不返回公式、缓存或私有帧。旧关系保持，精确国服存在/接受窗口继续M6核定；实际验证与下一项只在原两台账维护。
