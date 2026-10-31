# 引擎性能诊断工具

本工具只新增诊断输出，不修改模拟器、注册表或前端，不连接正在运行的对局。
当前用户已授权按固定基准逐项优化；范围与行为保全见[性能契约](../docs/engine-performance-plan.md)，实际进度及下一项只维护在原两份项目台账。

## 运行

在项目根目录使用全新输出目录：

```powershell
python -B -X utf8 tools/engine_performance_baseline.py --output outputs/perf-new-run --samples 5 --regressions
```

默认测 Demo 使用的 representative 注册表。新补卡的构筑注册表可另开一批：

```powershell
python -B -X utf8 tools/engine_performance_baseline.py --output outputs/perf-constructed-new-run --registry constructed --samples 5
```

每批先复制 hs_sim、测试、数据及原测试运行器，核对复制前后和副本逐文件 SHA；捕获过程中发生修改则拒绝执行，保留失败输出。此后只从副本导入代码。因此其他会话继续接卡不会混入该批测试。副本不是当前补卡批次的验收快照；源码和数据版本以 source-manifest.json 为准。

11 类操作包括火球、暗影视界单/三候选、选择确认、攻击、结束回合、满场十张目标法术的引擎/玩家合法动作枚举、玩家观察、待选快照及恢复。另跑两场连续五次暗影视界，记录每次出牌/选择耗时、实体数和历史长度。跨职业、短牌库与初始法力仅为显式实验夹具。

每类预热一次，轮流采样，报告原始墙钟/进程 CPU 时间和中位数、范围；不宣称小样本 p95。初始化、克隆、动作构造、为构造动作读取公开 state 副本和断言不在动作计时窗内；正常垃圾回收保留。性能剖析在计时完成后另跑，保留 pstats、累计和自身耗时；嵌套累计耗时不能相加。机器上其他任务的 CPU 竞争仍会影响计时，优化前后正式比较应尽量在低负载时执行相同命令。

## 行为保护

每类首样本检查完整快照、独立注册表恢复、克隆、回放和双方观察一致。待选样本额外检查非法选择不改变状态、克隆执行不污染原局、恢复后选择结果一致且不重复扣费。重复样本必须具有完全相同的状态和返回结果摘要。快照/帧摘要仅保存在本地诊断输出，不进入玩家接口。

`--regressions` 使用原测试运行器运行四个完整模块；精确测试清单、逐方法结果和源码守卫由原运行器保存。包括选择后异常回滚、随机选择回放、嵌套选择、死亡/攻击/结束回合续接、单次支付、重算外层哈希后仍拒绝篡改证明，以及玩家信息隔离。变更费用/目标枚举时追加的模块见 engine_performance_regressions.json；最终范围仍按实际代码差异确定。

冻结副本捕获hs_sim/tests/tools的Python、全部data及data显式引用的已存在outputs证据。追加模块若依赖examples或其他未捕获目录，需另行冻结并记录这些依赖，或在源码稳定的工作区执行；不能把模块加载失败计为通过。计划清单中的模块不是全部已执行的验收声明。

## 后续比较

```powershell
python -B -X utf8 tools/engine_performance_baseline.py --output outputs/perf-after-new-run --samples 5 --regressions --compare outputs/perf-new-run/report.json
```

比较器要求夹具初始快照、schema/注册表身份、工具 SHA、Python 和平台一致。兼容时逐操作状态/返回值必须相同，否则失败；耗时比只提供观察，不设置容易受机器负载影响的硬毫秒门槛。版本或卡池变更导致不兼容时，需要在补卡完成后的同一语义基线上分别测优化前后，不能把两个不同卡池版本的比值当作性能收益。

## 热点判读与优化边界

- 选择挂起：检查 resolver → FrameCodec、稳定边界校验、state_hash 三段；关注完整状态编解码、同一证明重复摘要和反复不变量验证。不要合并不同历史时间点的状态。
- 历史增长：检查 intrinsic_costs 的前缀重建及 payment_projection；记录实际拷贝/验证次数，不将多个嵌套累计时间相加。五次出牌同时增加实体和历史，不能据此单独断言历史的渐进复杂度。
- 目标枚举：满场十张法术提供压力用例；比较 targeting、RuleContext 构造、deepcopy 和费用验证。压力用例不是普通手牌的平均延迟。
- 固定类型元信息：get_type_hints 可作为次级候选；收益以自身耗时为准。

开始优化前需要当前补卡批次稳定，并重新生成基线。禁止用全局可变对象 ID 缓存结果、关闭校验或删除回滚快照来换取提速。此工具准备工作不代表已经实施任何优化，也不代替规则或官方国服验收。


## 2026-10-31 性能优化基准

当前用户已授权优化，范围、顺序和硬性行为保全见docs/engine-performance-plan.md；旧暂缓指示属于历史。本工具现冻结hs_sim/tests/tools的Python及全部data，同时捕获data显式引用的已存在outputs证据文件，避免新构筑源依赖缺失。原文件不改写；输出目录仍必须全新。

增加--standard顺序执行完整CN37本地宿主及固定30张牌整局，逐动作比较完整快照、原命令、全部合法动作/玩家返回和另一座位视图摘要。--compare先解析绝对路径，兼容输入不匹配或任何摘要差异都直接失败。固定实验格式不作为正式标准合法性认证。原始计时、CPU、pstats和源码守卫均保留。

--case可重复指定微测，省略历史压力及完整宿主；阶段收尾仍运行不带--case的--standard完整对照。阶段相关模块在engine_performance_regressions.json的phase_modules中规划，最终再选全部明确受影响完整模块；清单存在不表示已经执行。实际证据仍只在两份原台账登记。


完整收尾使用tools/engine_performance_compare.py对两个report.json追加严格核对：--full要求11类、历史及整局全部一致，定时父/子工具SHA一致，全部卡牌源和data不变；只有用--allow-engine-change逐个声明的已审引擎文件可以变化。它输出独立verification.json，不改写原报告；--output仍须新目录。该工具同时报告前后毫秒、百分比与倍率，且对任何语义或工具差异明确失败。

单项出现明显退步须保留原数据并复核。混合核心或负载波动时，可以用相同外部进程启动器固定两个冻结版本的CPU亲和性，再顺序运行本工具或engine_performance_standard.py；不改定时函数，记录掩码、来源及完整语义对照。不同亲和性结果分别报告。2026-11-01的掩码1启动器及原始异常/复测记录见outputs/engine-optimization-final-20261101/final-review.json，汇总解释见同目录findings.md。
