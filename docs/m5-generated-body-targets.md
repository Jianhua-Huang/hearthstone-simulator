# 自动整牌的独立主体目标与原接受窗口

这是传统构筑公共机制的内部实现契约，实际结果和下一项仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。机制优先、少量合成载体验证，不据此宣称正式卡池或国服时序完成。

## 实际连接的来源

`generated_body_targets.py` 连接 `ReplayWholeCards` 的真实物理安装入口。支持单次、仅战吼重复、族重复及保留结果四种来源（完整 profile 名称见[实际族身份](m5-generated-single-family.md)），以实际生成子实体接受主体，不借用历史出牌实体、付费根或间接战吼权限。印刷随从、武器、英雄可通过自己的完整主体声明绑定；地标可声明独立普通根，没有战吼/连击授予。

```python
registry.register_body_target_profile(BodyTargetProfile(
    'generated-targets', 'generated_whole', 'random', 'generated_acceptance'))
registry.register_generated_whole_target_binding(GeneratedWholeTargetBinding(
    'carrier', 'generated-targets', mode='body_only'))
registry.register_body_target_binding(BodyTargetBinding(
    'declaration', 'battlecry', 'generated-targets',
    carrier_card_ids=('carrier',)))

# 在来源行为中提交：物理安装和目标选择由公共解释器承担。
ReplayWholeCards(player_id, source_id, query,
    physical_profile='generated_family_repeat_after_install_v1',
    body_target_profile_id='generated-targets')
```

注册表指纹包含专属来源绑定。每个生成子项必须具有请求的来源绑定，每个印刷或授予主体须满足完整 `BodyTargetBinding` 的族、卡面、载体类型、印刷/授予范围。未选 profile、缺少任一绑定、未知规则或错误来源明确拒绝，事务回滚，不删候选或执行白板。

`BodyTargetProfile(selection='explicit')` 使用 `ReplayWholeCards.body_target_id`：同一原请求分别在每个主体自己的域中校验，可以有的成功、有的失败。随机 profile 禁止附带指定目标。普通根独立使用既有 `target_preference` 与自动随机窗口，指定主体目标不替代普通根目标。

## 普通根与完整主体向量

`GeneratedWholeTargetBinding` 的 `mode` 为 `body_only`、`preserve_root` 或 `explicit_root`。body_only 不得删除当前普通 on_play；preserve_root 沿用卡面普通目标；explicit_root 为 on_play 声明独立 TargetSpec、规则及门槛。生成随从的 Choose One 仅允许 preserve_root，从[安装前已接受分支](m5-generated-choose-one.md)取得自己的普通目标域；其他两种 mode 明确拒绝，不能删除或覆盖分支效果。

安装、召唤/装备/英雄替换及全部入场反应先结束，再接受当前 on_play、战吼和连击完整向量。入场待选时尚无主体接受收据；入场反应可正常授予或移除主体。没有当前普通主体时，preserve_root/explicit_root也不预选普通目标或消耗RNG。此后冻结向量，消费、移除、沉默、变形、死亡、转控或回手不会替换原已接受主体，晚授予不扩张向量。载体离场与原目标失效是不同边界。

公共授予只做结构授权，不运行谓词、支付报价、候选选择或 RNG。此授权只允许储存声明，不能通过复制或跨区变成手牌付费/间接权限。实际生成入口再次检查来源及完整授权；持有生成授予的付费载体仍需要自己的付费 producer。

## 条件、目标与随机

同一 after-install 窗口内，普通根首先接受自己的目标，各主体按族及物理附件顺序分别接受自己的完整目标域、目标与 RNG。战吼、连击均使用声明自己的法力渴求门槛；连击是否激活来自执行玩家在该窗口的实际已提交手牌历史。流放、压轴、快枪为 false，没有虚构手牌位置、资源支付或新的 PlayRecord。

同一窗口不会执行主体后再接受下一个主体。前一主体改变水晶或属性不重写后续原条件及原候选。条件未激活的无目标文本仍执行其无目标/false 分支，指定目标不能压制该分支。未激活连击保存显式 inactive 槽位，不创建实际 Combo。

随机非空域只选择一次，单候选也沿公共 RNG；空池及未激活目标不消耗 RNG。必选空池保存 no_target，普通根失败只跳过普通文本，不删除独立主体。每次战吼/连击实际执行前，已接受目标按当前共享保护和谓词检查；失效记录 invalid_target 并只跳过该主体，目标不重新抽取。实际失败战吼/连击仍有自己的记录及完成身份。

族重复和保留结果每次复用各物理主体自己的原选择；次数、有限政策用途、已接受结果组及原安装身份由既有公共模块负责。主体行为的后续随机可以继续推进共享 RNG，不误认为它应仍停留在接受后的状态。终局中断不伪造未开始的剩余主体。

## 原输入、恢复和玩家信息

紧凑 `GeneratedBodyTargetAcceptance` 保存专属注册来源、原源 Entity、完整结构目标事实、各主体条件、候选、选择及连续 MT19937 状态；复用不可变输入值类型，但不复用 paid 原接受证明或行动权限。完整 GameState 只在挂起的 `PhysicalBodyProof` 原边界中，不进入关闭后的紧凑记录或玩家 JSON。

恢复重建完整原目标域，核对原源/附件分配、完整有序向量、普通和各族实际 payload、自己的手牌/战场成员、真实生成激活、原水晶/出牌前缀和实际记录。活动证明另与完整真实 before-state 相比，检查全部原实体事实和原观察；既有完整解释器继续队列及 Finish 检查负责拒绝裁队列和缩次数。

显式注册的 `PlayerTargetRuleSpec` 使用玩家原 DTO 与私有物理引用映射。执行玩家可与当前回合玩家不同；DTO 值可表达该席位，生成消费者通过实际生成收据/原 owner-turn 验证。付费消费者继续要求当前行动玩家，不由这类 DTO 获得付费权限。主体开始时用当前玩家投影复查原目标，接受记录和私有证明不交给玩家。

关闭记录能重算所保存的引擎规则输入和内部一致性；后来局面不能独立认证所有过去资源/费用或未签名存档的外部来源。自定义谓词须按纯函数契约注册，并不提供 Python 沙箱。

## 格式及范围

开发规则 prototype-v145 / core-effects-v145，快照 schema140，旧 schema1～139需原引擎，不能静默补缺。`ReplayWholeCards` 包含必需序列化的 nullable body_target_profile_id/body_target_id/physical_branch_id，`PhysicalReplayProgress` 包含 nullable body_targets/choose_one；观察59/命令9/replay1与代表包64/合成包3保持。生成 Combo 的 no_target/invalid_target 不得伪装成付费 Combo。

四种物理历史整牌 profile 现均有实际族身份及生成随从的独立抉择分支；单次/仅战吼重复来源不查询或消费连击重复政策。其他自动来源、历史间接入口、完整异构来源/生命周期与分类 Hero 结束/有限触发继续保留。抉择的印刷主体混合声明等缺口仍开放。国服校准、M0正式补丁热修与完整合法可达池、H2完整阶段验收及机制/校准后的M7不由本增量关闭。
