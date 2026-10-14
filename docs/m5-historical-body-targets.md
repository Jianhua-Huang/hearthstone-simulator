# 历史战吼的独立来源与逐次接受

这是传统构筑的内部公共机制契约。当前实际验证和下一项在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护；原历史筛选政策及国服校准范围保持，不由此关闭整个 U14/U65。

## 专属注册与实际入口

```python
registry.register_body_target_profile(BodyTargetProfile(
    'my.history', 'historical_battlecry', 'random', 'historical_invocation'))
registry.register_historical_battlecry_binding(HistoricalBattlecryBinding(
    'my.carrier', 'my.history', declaration_card_ids=('my.first', 'my.second')))

RepeatPlayedBattlecrySequence(player_id, source_id, limit=30,
    profile_id='my.history', choices='player')
```

`HistoricalBattlecryBinding` 明确载体卡、来源 profile、完整允许声明卡范围，以及 history/played_history 来源范围。声明卡必须具有实际注册战吼和可重建的目标规则。注册只检查结构，不执行目标谓词、选择、支付或 RNG；绑定和 profile 进入注册表指纹。

历史能力已不一定存在于当前载体，不能伪造 `BodyTargetReference` 或把旧附件当成当前物理授予。这类绑定也不能授权手牌付费、生成整牌、当前随从主动触发或连击。历史记录的成功/完成/归属、出牌声明及原 payload 身份仍由既有历史公共模块验证。

五个实际入口均增加 nullable `profile_id`：`RepeatBattlecry`、`RepeatBattlecries`、`RepeatPlayedBattlecry`、`RepeatPlayedBattlecries` 和 `RepeatPlayedBattlecrySequence`。两个单项接口保留 random/explicit 请求；三个集合/序列接口保留原 random 目标政策。显式 profile 与请求策略不匹配时报错，不自动修改策略。

历史候选、去重、first/last、排序、上限、排除、反制资格及载体生命周期政策保持。授权不会筛掉已选中的未绑定声明：缺少来源、越过声明范围、错误历史归属或未知主体导致整个动作回滚。已有历史绑定的载体不能省略 profile 退回旧目标路线；其他未声明新绑定的旧来源保持原契约。

## 每次实际调用的原窗口

每条历史主体真正开始之前，分别接受自己的声明条件、完整目标域、原选择和 MT19937 前后状态。法力渴求使用本次执行席位的最大水晶及该声明自己的门槛；combo 读取本次席位此前已提交的同回合出牌前缀。流放、压轴、快枪为 false，没有旧手牌位置、旧支付或新的 PlayRecord。

`BodyPlayReference` 的 historical_body_id 只对应这一次真实 BattlecryRecord；`IfBodyCondition` 读取该接受结果。开始监听改变水晶、主体真实待选或后续转控不会重算已经接受的条件；下一次调用从新局面接受。历史原声明的目标条件未激活时仍可执行其无目标/false 主体，不被指定目标压制。

目标关系使用本次执行席位，目标域和规则来自原历史声明。随机非空域抽一次，单候选也抽；必选空池记 no_target，空域不消费 RNG。指定目标分别在本次域校验，非法目标只令相应实际记录失败，不更换其余主体。序列 exclude_source_target 保留自己的原排除政策。主体后续随机继续推进共享 RNG，不要求停留在接受时状态。

本模块不查询或消费手动重复政策，不扩大原次数或序列上限。外层重复重新产生实际历史调用，各自接受新窗口；主体内部真实选择仍由 choices 管理。未知文本、异常和工程预算失败沿整动作事务回滚，不留下额外支付、历史或随机消耗。

## 载体、历史归属与有界序列

原能力声明、原历史玩家和当前执行载体是三个不同身份。当前载体可以是随从、武器或英雄；不会复制原卡亡语/其他能力，也不会复用原付费激活。已接受原主体不被后续沉默、变形、死亡、回手或转控替换。

有界序列继续沿原 captured/in_play/same_incarnation、controller=captured/current 和 stop_on_silence 政策。captured 的原卡名不因为第一次主体变形而被替换；current 控制者政策重新确定下一次执行席位，但保持旧历史归属。in_play 来源离场后停止尚未尝试的主体，不伪造后续记录。

`HistoricalBodyProof.sequence` 保留该调用的真实 `ContinueBattlecrySequence`，从原完整候选、游标、来源政策与父身份重建其唯一 Begin 请求；自己的 Finish 必须先于原 FinishSequenceAttempt 和父战吼完成。不能借用过去同名卡或已结束的序列去授权新的历史主体。实际 BattlecryRecord 及 Begin/Resolve/Finish 检查点沿旧公共解释器，历史证明完成标记属于诊断控制，不增加玩法死亡检查点。

## 原证明、恢复与玩家信息

紧凑 `HistoricalBodyReceipt` 保存实际调用/战吼 ID、完整原请求、原载体规范 JSON、分配界限、原 turn/action/owner-turn、完整出牌前缀、声明条件、完整目标 partition/选择/RNG、必要玩家 DTO 及完成/中断状态。关闭校验核对历史 provenance、源分配、声明门槛、前缀、策略和实际记录，局部重演随机。

完整 before-state 和 Ruleset 只由活动 `HistoricalBodyProof` 保存，贯穿开始、主体、完成监听的真实等待。恢复从原局面重算条件、完整域及玩家原观察，并核对唯一 Finish、实际完成及完整外层序列继续。clone 和独立注册表动作 replay 共用这些校验。终局保留已开始记录，中断其尚未完成的证明义务，不制造未开始调用。

显式 `PlayerTargetRuleSpec` 沿[原玩家输入契约](m5-player-target-inputs.md)，读取本次执行席位的原可见 DTO；执行者可非当前回合玩家，完整原投影与关闭收据仍分别校验自己的 viewer/turn、原物理引用范围，不借用另一席位观察；全知回调和旧 visibility 标记不授予该输入权限。所有历史收据、原实体、物理引用和 RNG 只供可信宿主，不进入双方观察/动作端口。

关闭的紧凑目标记录不保存全部过去目标属性/资源，不能仅靠后续局面独立重算完整旧域，也不能认证未签名存档的外部来源。活动证明或可信动作 replay 提供完整原窗口验证。注册回调仍须遵守纯函数契约，不提供 Python 沙箱。

## 格式与保留范围

当前 prototype-v145 / core-effects-v145、schema140，旧1～139需原引擎。历史请求增加 nullable profile_id；BeginIndirectBattlecry 增加 nullable historical_profile_id/historical_body_id，BattlecryRecord 与 BodyPlayReference 增加 nullable historical_body_id，GameState 增加必需 historical_body_invocations。活动证明另保留 nullable 原序列。观察59、命令9、replay1及代表64/合成3保持，无新增正式卡牌适配。

这是上述显式注册历史来源的子集，不自动迁移所有旧卡行为或所有自动 producer。分类 Hero 结束/有限触发、其余来源和完整生命周期组合、抉择长期/下一次/特殊组合等已知缺口仍开放；H2完整阶段、M0正式补丁/热修/合法可达池、M6国服校准和机制/校准后的M7保持。
