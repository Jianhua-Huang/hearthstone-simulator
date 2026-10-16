# 显式无限伤害的内部数值政策

本入口服务真实END_024无穷烈焰，完整卡面及显式配方见[内容数据](../data/cards/infinite-secret-effects-v1.json)。伤害、治疗、防护、吸血、死亡及历史继续复用[原健康管线](m2-health-rules.md)。实际进度、证据、差异与下一项只在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护。

## 数值依据与限制

`saturated-positive-int32-v1`将显式无限伤害请求的预算取为`2**31-1 = 2147483647`，并在本请求的法伤加入及每次数值操作后封顶。这是明确且可替换的内部建模政策，**准确国服服务器数值尚未校准**，不宣称已反编译取得完整规则。

本轮静态重新反编译本地GameUtils，程序集前后SHA一致且与既有本地枚举源一致，没有执行游戏程序集。`INFINTY_THRESHOLD=1000000`及`SwapToInfinityIfNecessary`只证明非战棋数字显示转换；不把这个显示门槛当作伤害，也不由它证明服务器上限。[2025社区解释](https://us.forums.blizzard.com/en/hearthstone/t/murozond-unbounded-card-revealed-wtf/152601)谈及32位整数边界，但不是此卡的实测或官方数值规范，其对符号的描述也不能替代上述直接显示证据。完整来源与限制见台账关联观察。

同一固定源另有END_012攻击和END_018费用的无限值需求，本页不实现其武器/附魔/原费用恢复，也不扩展全局整数类型。普通Damage、Heal和其他属性的既有整数运算保持；不能按数值恰好较大而自动将普通效果切换为本政策。

## 公共请求与目标

从`hs_sim.engine.infinite_damage`导入`InfiniteDamageMinion(minion, source_id, on_result=None)`，传原MinionReference及已分配SPELL来源。未知来源、定义或回调先报错，即使目标已失效也不能隐藏未知内容。原目标须仍为同物理生命周期、控制者及卡面的active/live普通随从；失效沿原解释器跳过，不重新绑定同名或另一形态。

并列候选用`RandomInfiniteDamageMinion(tuple(refs), source_id, on_result=None)`：每个物理随从一个权重，先按实体ID规范顺序，过滤失效原引用；空池不消耗RNG并记录原跳过，一项无RNG，多项恰抽一次。选后沿typed单目标请求继续，随机事件反应可等待；期间选中者变形/移区失效不再抽选。候选及随机政策属于内部明确范围，准确官方消费仍待校准。

## 原健康准备与结算

请求将原整数预算交给`settle_health_batch`的一次非战斗健康请求。只有此入口设置有限的`numeric_limit`，不与随机逐点split或过量partition控制混用。PreparedHealth携带的限值是同批临时数据，不写新状态账本或排入队列。

原转换、学派法伤、来源/承受数值层、重定向、圣盾、免疫、护甲、生命下限及生命损失替换继续执行。数值规则仍按原整数次序应用，加法、倍率、设值或上限结果再封顶；例如倍率1/2得到`2147483647//2`，不是数学符号无穷。防止仍归零，伤害上限仍可将其改为1，圣盾/免疫仍可完全吸收，因此不能用Destroy代替。

HealthResult及原伤害/治疗历史保存实际数值和归因。原完整预算的实际过量伤害也计入伤害单位；生命下限只计实际部分，防止结果计0。固有吸血依据原实际伤害，继承本请求的数值限值后走原治疗管线；普通吸血没有新增封顶政策。转换、回调、死亡与等待都由原解释器负责，不插入第二执行器。

core-effects-v317和机制签名保护新请求及数值语义。schema268、既有保存字段布局、观察85/命令12/replay1保持；PreparedHealth新增的临时属性不是新存档字段。玩家仅获得原允许的结果，不获得数值政策、原引用或内部待执行操作数。

## 无穷烈焰

END_024使用原SecretSpec对手自然turn_ended窗口，当前敌方active/live普通随从的**剩余生命**决定最高者；不按印刷或最大生命排序，不把休眠、将死或地标当作候选，空场不消费。原接受上下文捕获最高原引用组，之后揭示/随机等待不另选后来目标。

原公开Fire学派及SPELL来源保留。[Fyrakk一手报告](https://us.forums.blizzard.com/en/hearthstone/t/flames-of-infinity-not-working-correctly-on-portal-summons/158480)描述被触发的法术没有伤害受Fire保护的随从，说明防护不能被“无限”或消灭替代；它不单独证明完整数值或Fyrakk全卡已实现。[37.0官方修复](https://hearthstone.blizzard.com/en-us/news/24301454)说明不应始终优先触发，故复用原公共回合末排序，不加专属第一优先级。完整国服顺序、并列RNG、数值上限和源修正仍需M6。
