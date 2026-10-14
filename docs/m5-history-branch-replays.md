# 批量历史与整牌法术的分支继承

**2026-10-09当前范围：**普通抉择/兼得、预选和真实历史继承保留；抉择与磁力/裂变/同一静态长期载体及独立印刷战吼/连击、根分支定价均已撤下。下方旧增量和费用/裂变组合补充仅保留历史记录，不是现行接口或必做依赖。当前扩展方式见[抉择契约](m5-choose-one.md)及[扩展指南](extensions.md)。

U17C沿[预选](m5-choose-branch-state.md)、[合并政策](m5-player-choose-both.md)和[分支费用](m5-choose-branch-costs.md)增加两个实际producer的明确继承能力。开发prototype-v148/core-effects-v148、schema143严格拒旧1～142，观察61/命令9/replay1，代表64及合成3保持。本契约是内部原型政策，未国服校准；实际验收与下一项只见[项目状态](project-status.md)、[机制清单](mechanism-backlog.md)。

## 逐次来源授权

`RecastFromHistory(..., branch_policy='current'|'inherit')`在每次抽选之后把实际原Cast ID与声明传给RecastSpell。current用当次新窗口重选，inherit用该原Cast.branch_id作为本次配方。相同卡名的不同实际Cast仍各有分支；distinct合并、oldest/newest/random和replacement只决定实际记录，不能按卡名借另一个分支。原冻结候选和截止不会纳入新产生的历史，主体/触发/选择完成后再选下一项。

`ReplayWholeCards(..., spell_branch_policy='current'|'inherit')`声明整牌法术来源；其physical_branch_policy继续单独控制四物理profile。inherit从实际child的原Play occurrence读取分支，CAST仍为原effect来源，root所属执行者与原提交者可以不同。真正原retry的最终提交卡面沿既有历史政策，不能猜首次卡面或伪造另一历史来源。无抉择的卡正常执行并没有分支收据；未知声明或非法原分支报错。

## 每次真实窗口

整牌选择的根级RNG先沿既有历史政策执行。实际child分配后，法术创建自己的基础载体；临时继承配方只参与自己的CAST。当前场上与明确cast_effect玩家政策决定完整分支选项，再先选分支、后选择该分支的完整合法目标。继承或combined只有一个选项时不消耗分支RNG；目标单例、空池和偏好仍沿公共目标模块。

combined按既有override政策可以覆盖普通继承分支，原combined在没有当前合并来源时仍可继承。有限用途每个合格新根一次，前一个主体/选择授予的政策进入下一次实际窗口，不能重写已接受分支。拥有分支费用不会让自动历史变成手牌付款。真正父回溯重试/保留结果分别产生自己的新调用，父付款仍一次，生成/主体许可不扩大。

临时配方在接受后从新实体清除，原target proof保存完整当窗事实。它不会作为后续复制或再次使用的永久预选授予。主体使用实际cast.branch_id进入公共Choose One dispatcher，目标失效不换分支或删候选，终局和异常沿公共解释器。

## 持久化与原完成义务

[history_branch_replays.py](../hs_sim/engine/history_branch_replays.py)的SpellReplayBranchReceipt保存root/child/occurrence/实际cast、卡面和执行者、current/inherit、原继承分支、完整有序选项、实际分支及MT19937前后状态。root保留独立spell_branch_policy，child保留自己的紧凑收据；禁止借用其他调用、擦除收据、扩选项、乱顺序或改变分支→目标RNG的连续性。

活动ReplaySpellProof沿原AutomaticTargetProof保存完整CAST窗口。在该窗口重新计算选项、原临时实体配方及唯一预cast child，再连接已接受CAST、完整主体和各自Finish。历史批次的ContinueHistoryCasts完整spec、剩余候选/次数/截止与原真实选择边界work相同，待选存档不能只修改branch_policy。schema143严格要求新字段，旧档案不自动补出其没有保存的授权。

关闭收据可核对实际原记录、政策、分支、声明范围和局部随机重演；完整过去候选局面保存在活动证明中。关闭收据不能认证未签名外部存档或全部过去局面，玩家端口不获得原状态、收据、来源ID及RNG。

## 验证与剩余范围

[本批证据](../outputs/v276-history-branch-replays-20261009/verification.json)绑定34新增+229相关共263唯一方法、12模块、3进程249.692秒内部通过，全量0、正式卡0。[实际选择及排除原因](../outputs/v276-history-branch-replays-20261009/validation-plan.json)保留；全历史示例/CLI、完整H2和国服验收没有执行。必要合成载体验证同名相反分支、放回/去重、两来源当前合并、原目标/空池、混合四物理profile、执行者、真实待选独立恢复/clone/replay、父retry/保留、例外/终局及隐私。

特殊producer、技能替换与真实预选/合并/支付例外仍须自己的具名授权和校准，不能借本层参数冒作所有来源完整。U17、U18、U14/U64/U65整轴、其他已知机制、H2、M0正式补丁/热修/完整合法可达池、M6国服校准和机制/校准后的M7继续保留，完整目标active、最近完整阶段仍H1。

## 生成及技能继承的接口衔接

本页原阶段格式与尚待补条目保留当时范围；当前主工程prototype-v149/core-effects-v149、schema144严格拒旧1～143，观察61/命令9/replay1及实验包保持。[生成及技能公共层](m5-choose-branch-producers.md)提供事件前原子配方、实时旧技能状态继承、真实原激活显式冻结、完整有序分支映射和历史发现继承。原费用、已接受主体、有限合并用途及恢复/玩家边界沿原模块。真实来源例外、U17/U18及其他开放轴仍以两份最新台账为准，不借本接口认定国服或所有特殊来源完整。
