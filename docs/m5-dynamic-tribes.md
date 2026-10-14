# 当前种族与动态修改

公共接口在 `hs_sim/engine/tribes.py`。种族是实体身份的一部分，与关键词、职业、派系和卡牌类型分别处理；把随从设为龙不会改变其职业或尸体价值。实际执行、验收证据及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约是内部原型政策，尚未国服校准。

## 修改与查询

`TribeChangeSpec(operation, tribes)` 声明有序的 `add`、`set` 或 `remove`。种族使用唯一、不可变的字符串元组；只有 `set` 可以指定空集合。`ChangeMinionTribes` 通过已捕获的 `MinionReference` 或 `CardReference` 作用于场上活跃存活随从或手牌/牌库随从，附带来源、全局回合到期和沉默保留政策。

```python
from hs_sim.engine import ChangeMinionTribes, TribeChangeSpec, has_any_tribe
from hs_sim.engine.sacrifice import MinionReference

# 在行为返回的效果中安装独立附件，不直接修改实体或卡牌定义。
target = ctx.state.entities[ctx.target_id]  # 已选定的合法随从目标
ChangeMinionTribes(
    MinionReference.capture(target),
    TribeChangeSpec("add", ("dragon",)),
    source_id=ctx.source_id,
)
has_any_tribe(registry, target, ("dragon",), basis="current")
```

`tribe_state(registry, entity, basis=...)` 返回不可变 `TribeState(members, excluded)` 或未知的 `None`，也可以读取冻结 `DeathRecord`。`printed`只读当前卡面的印刷元数据；`current`在此基础上按获得顺序应用所有种族附件。非随从对象没有当前随从种族。`has_any_tribe`查询完整种族集合；未知输入明确报错，不把未知当作空集合或忽略候选。

未知基础种族加上一个已知种族仍不足以得到完整集合；明确 `set`、`add all` 或 `remove all` 可以给出确定的完整结果，但不会补填未知印刷元数据。普通生成池、发现池、历史卡面及原有声明为印刷依据的重复匹配保持其依据。

`all`是全集标记，不从当前样本卡池枚举种族。向全集移除个别种族会保留 `excluded`；重新添加某种族会取消该排除。移除 `all`得到空集合；添加 `all`得到无排除的全集。要求 `all`的查询只匹配无排除全集，要求普通种族时尊重排除。这样未接入样本池的其他种族也有确定匹配结果。

## 生命周期

修改使用独立、纯身份 `Enchantment.tribe_change`，不得在同一附件混入数值、费用或磁力组修改。已有属性、费用和关键词缓存无需新增种族缓存。它共用附件分配器及以下生命周期：

| 操作 | 保留规则 |
| --- | --- |
| 正常出牌、抽牌和保留状态区域移动 | 保留有序种族附件 |
| 沉默 | 移除 `remove_on_silence=True` 的种族附件；印刷种族仍在，后续可重新授予 |
| 按ID移除或全局回合到期 | 仅移除指定附件，重新露出之前的有序修改 |
| 当前复制 | 复制修改并分配新附件ID，保留原来源追踪 |
| 基础复制、普通回手、洗入及显式reset | 使用当前卡面的印刷种族，不继承额外修改 |
| 变形 | 新卡面的印刷种族及新状态；旧修改清除 |
| 转控 | 修改保留，旧引用因控制者/入场身份变化失效 |
| 死亡 | 随死亡附件一起冻结；后来实体状态不能改写死亡种族 |
| 复生与基础死亡历史复活 | 新实体使用印刷身份，不复制额外种族修改 |

捕获引用保存卡面、控制者、区域/入场身份和epoch；已知旧引用可以正常跳过，不能附着到后来同ID的变形或移动结果。未知卡面、非随从引用或不存在的物理身份明确失败。选择等待中的工作也在其对应原状态中检查，复用公共事务、回放和选择恢复。

## 公共消费者与接受窗

`TargetPredicateSpec.current_tribes_any`与已有 `printed_tribes_any`可以分别或交集使用。普通根和每个BC/Combo主体沿用既有支付前候选捕获及实时 `skip_unavailable` 政策。原事实保存完整、按获得顺序排列的种族附件，重建时使用原卡面和原修改；实际后续沉默、变形或修改不能改写原候选。附件类型、独立身份、分配上界、来源和原到期时间严格校验，原来源的完整Entity仍与事实交叉核对。

`MinionScope.tribe_basis`默认 `printed`，可以明确设为 `current`；只改变其中 `PoolQuery.tribes_any`的实体匹配依据，其余元数据字段保持原依据。查询按原区域和物理顺序完整遍历，不消耗RNG，不因已有匹配候选而隐藏之后的未知种族。

磁力宿主使用当前种族；合体历史另外保留原宿主种族附件，宿主后来沉默或变形不要求重新满足旧条件。合体继承材料的属性与已声明持续能力，保持宿主身份，不把材料的种族变成宿主种族；这一组合政策仍待国服校准。

武器条件的 `friendly_tribe_present`读取所属窗口的有效种族，`combat_accept_original`和 `pre_wear_current`分别保存完整原修改及派生结果。记录恢复从原卡面和修改重算，全集排除、同批死亡及来源资格继续服从原窗口和presence政策；不会用后来仍在场的实体替换原见证。

## 玩家信息与格式

观察v58只在公开区域及自己的手牌属性视图提供 `tribes` / `tribes_excluded`，未知完整集合为null；记住对方手牌卡名不授权读取后续隐藏修改。玩家端仍不获得种族附件ID、完整修改记录、原证明或内部授权。新增字段不扩大对方暗牌目标筛选权限。

开发规则prototype-v140/core-effects-v140、快照schema137严格要求新字段；旧schema1～136及旧观察格式需使用原引擎，不自动补缺。命令9和外层replay1保持。相关条件参数继续进入注册表指纹；保存校验仅证明内部一致性，不认证未签名存档的外部来源。

本模块表达独立附魔；后续具体来源若要求持续种族光环、玩家长期身份规则或其他接受窗，仍需明确并验证其独立政策，不能从该附魔接口推定已支持。玩家观察条件已有[显式原输入契约](m5-player-target-inputs.md)；[间接战吼](m5-indirect-body-targets.md)已连接独立来源；未公开内部历史条件及其他生成/间接来源的授权仍需逐项补齐。正式版本、完整合法可达池和国服官方时序不能由本公共模块或样本测试宣称完成。

当前受益者种族的必要原生冲锋光环见[独立筛选契约](m2-tribal-keyword-aura.md)，复用has_any_tribe/current和原外部光环检查点。此扩展不改变本页旧生命周期、其他印刷依据查询或可选授予范围。

原生当前种族的持续属性光环使用同一has_any_tribe/current查询，见[独立属性筛选](m2-tribal-stat-aura.md)；原印刷依据消费者及修改生命周期保持。

原生种族费用光环由同一tribe_state_for/current查询读取原完整CostQuoteInput附魔；生成保持新卡初始身份，见[独立费用筛选](m2-tribal-cost-aura.md)。
