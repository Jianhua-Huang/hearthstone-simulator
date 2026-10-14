# 生成预选与技能分支继承

**2026-10-09当前范围：**普通抉择/兼得、预选和真实历史继承保留；抉择与磁力/裂变/同一静态长期载体及独立印刷战吼/连击、根分支定价均已撤下。下方旧增量和费用/裂变组合补充仅保留历史记录，不是现行接口或必做依赖。当前扩展方式见[抉择契约](m5-choose-one.md)及[扩展指南](extensions.md)。

本公共层为U17D，沿[物理预选](m5-choose-branch-state.md)、[分支费用](m5-choose-branch-costs.md)和[历史重演继承](m5-history-branch-replays.md)增加生成/安装的明确声明。当前开发prototype-v149/core-effects-v149、schema144严格拒旧1～143，观察61/命令9/replay1及代表64/合成3保持。契约是内部原型政策，尚未国服校准；实际执行与下一项只见[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。

## 首个事件前的完整配方

`AddToHand`、`AddToDeck`、`AddHeroPower`、`ReplaceHeroPower`接受可空`choose_branch: ChooseBranchSelection`。字段追加在原参数之后，老的默认调用保持没有预选的新印刷实例；不借用同名卡或其他物理实体。声明必须与新card_id一致，卡面本身有ChooseOne、分支存在、来源适用当前卡牌种类、组合策略合法。

[card_creation.py](../hs_sim/engine/card_creation.py)复用创建候选/源/费用/重复验证，在新实体完整分配后、card_created/card_added_to_hand或烧牌事件前设置实体选择；技能由[hero_powers.py](../hs_sim/engine/hero_powers.py)在费用安装后、hero_power_added/replaced之前设置。第一个反应已看到完整配方和费用/重复，没有中间SetChooseBranch事件。满手烧牌仍保留实际新实体及声明，牌库保持私有。

创建配方是卡牌作者显式声明，不是一次抉择激活。它不消费玩家合并用途、不选择目标、推动RNG或制造付款。当前复制/移动、重置/变形、沉默、回溯和已经接受的主体沿物理预选原契约。

## 实时保存状态与冻结原激活

`ReplaceHeroPower(..., branch_policy='clear'|'inherit', branch_map=None)`默认clear。inherit在实际替换被选安装时读取旧实体choose_branch，仅转移选择配方；原实体没有配方时新实例也没有，不能查最近一次PowerRecord猜分支。空动态主位没有继承来源，明确报错；有效但过时的引用仍跳过，不借新主技能或同名新实体。

以下纯查询允许卡牌明确要求“该次已接受激活”而不是实时保存状态：

```python
accepted = capture_power_choose_branch(ctx.state, registry, ctx.power.id)
recipe = transfer_choose_branch(registry, accepted, upgraded_card_id, branch_map)
return (ReplaceHeroPower(ctx.player_id, upgraded_card_id,
    power=HeroPowerReference.capture(ctx.source), choose_branch=recipe),)
```

`capture_power_choose_branch(state, registry, record_id, origins=('power_manual','power_effect'), combination='override')`只读指定真实PowerRecord的card_id/branch_id，忽略当前实体后来保存了什么。普通无抉择技能返回None，无效ID/来源/组合仍报错。原combined可与物理保存的普通分支不同。冻结之后的typed literal随待选效果保存，执行时不再根据新局面捕获原分支。它是明确作者声明；对外部未签名配方不提供来源真实性认证。

`transfer_choose_branch(registry, selection, target_card_id, branch_map=None)`只转移一份不可变配方，不改状态、RNG、用途、费用或实例身份。inherit与literal不能同时提供；literal与branch_map不能混用。升级实例创建新的实体/能力、费用和用途；原激活/重复/回溯的来源ID和已接受branch保持原记录。

## 完整映射

old与new必须同卡牌类型且都有ChooseOne。省略映射只支持原全部branch ID在目标上仍同角色；显式映射是不可变有序元组，严格覆盖原所有普通分支，再combined，每个目标只出现一次。普通分支映到目标普通分支，combined映到combined；目标可以增加其他普通分支。目标的效果、目标需求、身材和费用可以变化，不要求整个ChooseOneSpec相同。

```python
branch_map = (('left','low'), ('right','high'), ('both','all'))
ReplaceHeroPower(player_id, 'upgraded_power', power=captured,
                branch_policy='inherit', branch_map=branch_map)
```

来源范围、strict/override完整保留，新实际激活使用目标定义自己的主体及价格。明确映射即使当前旧实体没有保存配方也必须有效，过时引用不绕过未知目标或错误映射。定向额外技能保留原位置，默认费用/使用次数重置和累计历史保持原安装协议。

## 历史发现

`DiscoverSpellHistory(..., branch_policy='current'|'inherit')`默认current，生成未预选基础手牌。inherit使用真正offer对应原分组的canonical首个Cast，冻结其card_id/branch_id为hand-only ChooseBranchSelection。distinct=cast可给同卡名的不同分支各自offer；card/identity去重不会把发生次数当权重或借后来分支。

冻结配方进入RequestChoice中的AddToHand，真正选中后原子装入。它只生成手牌，没有history CAST、原目标、原付款或新的分支RNG；发现offer取样仍沿既有随机政策。之后真正手动出牌仍提交明确branch，读取当前合并来源及费用，只消费当次合格根自己的用途。

## 恢复和信息边界

解释器保存所有新增字段，schema144不自动修补旧缺字段。创建声明与技能映射复用已有card_creation帧遍历；恢复递归检查新卡面、种类、适用来源/分支及完整映射，错误嵌套声明不能藏在等待选择的分支内。实际执行仍检查源/引用/费用时限，失效和异常走公共事务。

原技能主体和重复、技能真实重试及保留多结果继续原窗口，只支付一次原接受；替换不会重定向旧根。未授权power_effect时，间接根按原automatic_branch随机选分支，effect.choices只控制主体内选择，不能假定为玩家分支选择。

玩家DTO继续只投影原choose_selection的branch/origins/combination。敌方隐藏手牌和牌库不显示配方，实体ID/引用/映射、原宿主状态、完整队列和RNG不进入玩家端口。语义校验保证声明与状态内部一致，不能认证未签名外部存档的所有历史。

真实预选/合并/支付例外及未核查producer仍须各自契约与国服证据。特殊混合根、其他开放机制、完整H2、M0正式补丁/热修/完整合法可达池、M6国服校准和机制/校准后的M7继续保留，不以几个新增参数认定整个抉择族或正式卡池完整。

## 后续裂变配方

生成到手牌的根typed配方先完整装入，再由裂变家族显式clear/inherit；生成到牌库则保留到真实入手后才拆分，直接存储CAST不入手、不裂变。配方转换发生在新私有拆分/重组事件前。见[公共契约](m5-shatter-choose-roots.md)，实际验证、差异和下一项以两份主台账为准。
