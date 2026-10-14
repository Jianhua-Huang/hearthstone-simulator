# 自动生成随从的抉择分支与实际执行

**2026-10-09当前范围：**普通抉择/兼得、预选和真实历史继承保留；抉择与磁力/裂变/同一静态长期载体及独立印刷战吼/连击、根分支定价均已撤下。下方旧增量和费用/裂变组合补充仅保留历史记录，不是现行接口或必做依赖。当前扩展方式见[抉择契约](m5-choose-one.md)及[扩展指南](extensions.md)。

这是传统构筑公共机制的内部契约。实际验证和下一项在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护；四种物理历史来源的接通不代表整个抉择族、正式卡池或国服时序完成。

## 两个不同的接受窗口

`generated_choose_one.py` 连接真实 `ReplayWholeCards` 物理随从入口。以该实际 child 分配前的原局面为依据，在实体安装前接受分支，普通目标及完整战吼/连击向量仍在安装和全部入场反应结束后接受。单次、仅战吼重复、族重复、保留结果四种 profile 均沿[实际族身份及次数许可](m5-generated-single-family.md)。

分支先于目标。无合并来源时按完整声明顺序随机选择普通分支，不先删除无合法目标的分支；存在活跃合并来源时选择唯一显式合并分支。一个选项或指定分支不消耗分支 RNG。合并主体必须由 `ChooseOneSpec.combined` 完整声明，不自动拼接文本。

原合并来源来自该执行席位的原战场及活跃 choose_both 附件。新随从自身的声明不使第一次安装前接受变成合并；入场期间获得或失去合并能力不重选已接受分支。后一实际 child 从新局面接受，可以看到前一载体已经安装的来源。分支效果后续授予合并能力也不改变该 child 的重复或保留结果。

## 来源请求与目标

```python
ReplayWholeCards(player_id, source_id, query,
    physical_profile='generated_after_install_v1',
    physical_branch_id='chosen-branch',  # 可省略；省略沿当前随机/合并政策
    body_target_profile_id='generated-targets')
```

`physical_branch_id` 只用于实际物理抉择 child；必须声明物理 profile。未知分支、普通物理 child 或与原合并政策冲突明确报错并回滚。它不是内部发现选择，也不改变同一请求中的法术施放分支接口；`choices` 仍管理主体内部真实选择。

独立生成目标绑定只允许 `preserve_root`，从原选定分支取得普通目标域及规则。`body_only` 和 `explicit_root` 不得删除或覆盖抉择分支。完整各主体的原条件、目标候选、选择及连续 RNG 沿[生成主体目标契约](m5-generated-body-targets.md)。普通分支必选空池只跳过普通根，不能删除独立授予主体；旧默认共用目标路线仍按既有整体失败规则处理。

分支选择完成后，入场反应可以正常推动共享 RNG；目标接受从当时的 RNG 继续，不要求仍停留在分支随机后的状态。满场保存实际分支收据及安装失败，不制造实体、主体接受或族记录。入场沉默可以移除普通主体；此时保留原分支，但没有普通目标抽取。

## 实际执行与生命周期

公共 `engine.choose_one` 在无自己的出牌、施法或技能记录时，通过真实 `PhysicalReplayProgress` 分派选定分支。校验实际根/child、载体、执行者、running 阶段及普通主体游标；不伪造手牌支付或 PlayRecord/SpellCastRecord。已有手动出牌、技能和自动法术分派优先级保持。

各族分别接受自己的主体，仍沿各自 max、用途和 Finish。重复或保留组复用该 child 原分支及各主体原目标，不重新抽选；执行身份不会额外授予重复许可。接受后的变形、转控、回手等保留既有原主体和席位；下一 child 重新接受。未知选中主体或非法请求导致动作的实体、历史、支付、用途与 RNG 原子回滚，终局只保留实际已开始的主体。

## 原证明、恢复与信息边界

`GeneratedChooseOneReceipt` 保存实际根/child/occurrence/profile、原卡面和执行席位、turn/action/owner-turn、分配边界、原状态哈希、完整有序原战场实体 JSON、合并来源附件 ID、完整分支向量、请求及实际分支与 MT19937 前后状态。关闭校验重建所保存原实体的结构及活跃来源，并局部重演原抽样。

完整原局面只保存在活动 `GeneratedChooseOneProof.before_state`，原窗在 begin_replay_child 之前，避免保存尚未安装的无效半成品 child。原证明重新分配并核对实际 child、完整原战场/状态哈希和原请求；安装等待的 Prepare 及主体等待的 PhysicalBodyProof/Finish 均保留同一证明。恢复拒绝擦除、裁原战场或借用其他 child 的证明。

快照、clone 和独立注册表动作 replay 复用公共解释器。证明、原战场、分配及 RNG 不进入两位玩家的观察或动作端口。关闭的紧凑记录提供内部一致性，不能认证未签名存档的外部来源，也不能独立恢复全部过去资源。

## 格式和范围

开发prototype-v147/core-effects-v147、schema142，旧1～141需原引擎。既有physical_branch_id、choose_one、choose_proof、physical_branch_policy及branch_policy/inherited_branch_id、实体/复制材料配方保持；后续报价新增明确分支/基准及技能原付款证明。观察61、命令9、replay1及代表64/合成3保持，无新增正式卡适配。

必要验证复用已有战争古树与鹿盔，加测试注册表中的合成 producer。原生成分支增量只组合入场授予主体；当前印刷battlecry/Combo可与抉择普通根独立声明，沿同一真实来源接受，详见[混合声明契约](m5-printed-choose-one-bodies.md)。同定义无目标主体不借分支目标，独立完整向量保持优先。玩家长期/有限次合并见独立政策模块，实体预选及四物理profile的显式继承见来源模块。其他自动/历史间接来源、剩余来源专属继承、不同分支费用和特殊组合根仍在 M5；U14/U65、H2、M0完整池、M6国服校准及其后的M7继续保留。


## 玩家政策的原接受

生成分支新增`original_player_modifiers`、`policy_receipt_id`和活动`policy_proof`，完整pre-child窗口重算显式physical政策。接受/消费在安装及入场反应前；四个物理profile各保留自己的次数许可，后续重复不另消费。原板上附件与玩家实例分开编码，原RNG请求证明保持；详见[玩家政策契约](m5-player-choose-both.md)。

## 逐原历史记录继承

`physical_branch_policy='inherit'`按每个child自己的实际PlayRecord occurrence捕获原branch，在pre-child窗口再组合当前合并政策；不借同名实体、第一张牌或安装后的新局面。默认current继续重选，非抉择child沿原路径。紧凑记录与完整证明均绑定原历史身份、请求和分支，待选恢复保持同一收据。此政策只适用于四个显式物理profile，整牌法术路径及其他producer仍需自己的授权。详见[物理配方、继承与边界](m5-choose-branch-state.md)。

## 分支费用的来源边界

[公共分支价格](m5-choose-branch-costs.md)只改变真实手动手牌/技能付款。四物理profile不因安装抉择实体而新增费用，原pre-child分支/继承及其独立主体窗口保持。整牌法术及其他历史producer仍需U17C自己的继承授权，不能把付款公共层当作它们已完成的证据。

## 批量与整牌法术继承的当前接口

当前主工程prototype-v148/core-effects-v148、schema143严格拒旧1～142，观察61/命令9/replay1及实验包保持。[U17C公共层](m5-history-branch-replays.md)已接入RecastFromHistory.branch_policy及ReplayWholeCards.spell_branch_policy，四物理profile仍使用独立physical_branch_policy。原分支费用与真实付款、合并有限用途、目标/主体接受及已接受工作保持。上方U17A/B当时尚待补的批量历史/整牌法术范围以本接口和最新台账为准；特殊producer/技能替换和真实例外仍在M5，不关闭U17或U65整轴。
