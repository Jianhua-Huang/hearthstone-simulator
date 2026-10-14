# 练习、教程与本地规则候选路径的反编译检查

检查时间：2026-09-23。目标安装：`D:\游戏\Hearthstone`。仅使用 ILSpy 11.1.0.9782 静态反编译，没有加载执行游戏程序集、启动游戏、读取账号/对局日志、连接服务器或改动安装。反编译证据在 `reports/decompiled/local-rules/`，此目录已由项目 `.gitignore` 排除。

## 判断

这份安装中的传统炉石练习与教程启动路径都会请求 Battle.net 建立对局。教程类确实有本地分支、输入限制、事件处理及表现控制，但已检查到的实现不是能计算伤害、死亡、卡牌触发连锁和任意下一步状态的独立规则引擎。AI 调试界面的评分也来自游戏网络数据包，而非界面本地运行搜索决策。

此结论由具体方法调用支持；不应简化成“客户端没有任何逻辑”，也不能当成“每一个原生代码字节和资源文件都已穷尽证明不存在规则代码”。

## 1. 练习和教程共用联网建局路径

下列行号均指此次保存的 ILSpy C# 输出。

| 入口/阶段 | 代码证据 | 行号 |
|---|---|---|
| 练习按下开始 | `PracticePickerTrayDisplay.PlayGameButtonRelease` 读取所选牌组和任务 ID，调用 `GameMgr.FindGame(GameType.GT_VS_AI, FormatType.FT_WILD, ...)`；普通与模板牌组两个分支相同 | `local-rules/PracticePickerTrayDisplay.cs:301`，调用在 327、337 |
| 传统教程入口 | `Box.StartTraditionalTutorial` 注册找局回调并调用 `GameMgr.FindGame(GameType.GT_TUTORIAL, ...)` | `local-rules/Box.cs:3266`，调用在 3272 |
| 教程进度界面 | `TutorialProgressScreen.OnPlayButton` 同样调用 `FindGame(GT_TUTORIAL, ...)` | `local-rules/TutorialProgressScreen.cs:256`，调用在 262 |
| 通用任务入口 | `MissionLauncher.HandleClick` 将任务的英雄及牌组 ID 交给 `FindGameWithHero` | `local-rules/MissionLauncher.cs:20`，调用在 23 |
| 建局参数转发 | `GameMgr.FindGame` 调用 `FindGameInternal`，后者直接调用 `Network.FindGame`，包含 `aiDeck`、任务、恢复快照等参数 | `local-rules/GameMgr.cs:497`、510、514、516 |
| 请求对局 | `Network.FindGame` 创建 `BnetMatchmakingPlayer`，包括 `type`、`scenario`、`aideck` 等属性，最终调用 `BattleNet.QueueMatchmaking` | `network/Network.cs:9355`、9376、9490 |
| 恢复局面 | 同一方法把 `snapshot` 和 `load_game` 加入请求属性，再送往 `QueueMatchmaking`；不是在此反序列化后本地继续计算 | `network/Network.cs:9478`、9484、9490 |
| 接收对局地址 | `GameMgr.OnGameToJoinNotification` 读取 `GameToConnectNotification.Info` 并调用 `ConnectToGame`；后者从通知取 `Address`、`Port`、游戏句柄、场景并推进连接状态 | `local-rules/GameMgr.cs:3292`、391、412 |

`TutorialPreviewController.StartSelectedTutorial` 容易误判：该方法只等待预览动画结束并调用确认回调（`local-rules/TutorialPreviewController.cs:302`、316）。实际传统教程回调是上述 `Box.StartTraditionalTutorial`。

## 2. 教程类中的本地代码究竟做什么

`GameMgr.CreateGameEntity` 根据任务 ID 创建 `Tutorial_Fight_001/002/003`，但入口接受的本身就是网络 `PowerHistory` 列表与 `HistCreateGame`（`local-rules/GameMgr.cs:694`、704）。类名有 Fight 并不说明它是结算器。

已完整反编译并检查 `Tutorial_Fight_001`、`Tutorial_MissionEntity`、`MissionEntity` 和 `GameEntity`：

- `MissionEntity.OnTagChanged` 在收到 `MISSION_EVENT` 的新值时调用 `HandleMissionEvent`，后者启动语音及任务事件协程（`local-rules/MissionEntity.cs:136`、429、434）。
- `Tutorial_Fight_001.HandleMissionEventWithTiming` 根据事件编号选择语音、指示箭头、手牌/随从提示等（`local-rules/Tutorial_Fight_001.cs:902`）。`HandleStartOfTurnWithTiming` 在特定回合播放引导及等待（985）。
- 也有实质的本地输入门控。例如 `NotifyOfBattlefieldCardClicked` 第一次点教程中的暴龙王时播放“攻击英雄”的引导，改变 `m_canTargetKingKrush`，返回是否允许继续（401—412）。这不是扣血或执行该卡规则。
- `NotifyOfEndTurnButtonPushed` 读取 `GameState.GetOptionsPacket().HasValidOption()` 判断是否可结束教程引导，再清除提示（372—382）。合法选项列表是现有网络状态的一部分。

因此可复用的是任务表现/引导的客户端语义；这些代码不足以单独运行传统炉石战斗。

## 3. AI 调试评分是接收后展示

完整调用链为：

1. `Gameplay` 注册 `AIDebugInformation.PacketID.ID` 的网络处理器（`local-rules/Gameplay.cs:249`）。
2. `Gameplay.OnAIDebugInformation` 通过 `Network.Get().GetAIDebugInformation()` 取数据，再交给 `AIDebugDisplay`（787—790）。
3. `Network.GetAIDebugInformation` 转发给连接 API（`network/Network.cs:9997`）。
4. `ConnectAPI.GetAIDebugInformation` 调用 `UnpackNextGamePacket<AIDebugInformation>(6)`（`network/ConnectAPI.cs:911`）。
5. `AIDebugDisplay.OnAIDebugInformation` 保存收到的按回合/步数/搜索深度分组的数据（`local-rules/AIDebugDisplay.cs:335`）。`GetOverallScore` 仅把已有的 `BaseScore + BonusScore + ContextualScore + EdgeCount` 相加，用于界面排序（139、206）；`UpdateDisplay` 画出评分文字（144、332）。

这条链不能提取出 AI 的真实评分函数、树搜索或模拟结算代码。

## 4. 看似本地服务器/独立引擎的候选

| 候选 | 实際检查结果 |
|---|---|
| `MockGIServer` | 完整类只有固定的三个个性化消息 ID，等待 0.1 秒后回调；不是游戏服务器。`local-rules/MockGIServer.cs:9`、14。 |
| `Networking.FakeUtilHandler` | 完整实现只为账户资料、牌组、收藏、外观等请求制造客户端假响应，调用 `Network.FakeHandleType`。没有出牌、攻击或战斗结算接口。`local-rules/Networking.FakeUtilHandler.cs:9`、38、61。 |
| `Networking.DebugConnectionManager` | 当前发布程序集是空实现；`AllowDebugConnections` / `HaveDebugPackets` / `IsActive` / `TryConnectDebugConsole` 返回 false，取包返回 null。`local-rules/Networking.DebugConnectionManager.cs:7` 起。 |
| `OfflineDataCache` | 缓存原始/本地牌组、收藏和外观，生成修改差异；`OfflineData` 的字段可以直接确认范围。`local-rules/OfflineDataCache.cs:14` 起。不是离线战斗快照及执行器。 |
| `Blizzard.T5.Game.dll` | 全程序集反编译。包含 GameLayer、SpellFacing、SpellLocation、SpellType 等枚举及 `SpellBase : MonoBehaviour`；其字段是位置、朝向、Transform、GameObject，状态接口是 Activate/Deactivate 等。`local-rules/Blizzard.T5.Game.decompiled.cs:577`、747。没有伤害和触发结算器。 |
| `Blizzard.T5.Network-Core.dll` | 全程序集反编译。`DefaultSocket`、`RpcController`、`TcpController` 负责套接字、编解码、TCP 收发。具体 `ConnectAsync` 创建 Socket/端点并建立连接，`Send` / `SendAsync` 发字节。`local-rules/Blizzard.T5.Network-Core.decompiled.cs:141`、378、687、742。 |
| `Blizzard.T5.PlayMakerCustomActions.Runtime.dll` | 全程序集反编译。材质、粒子、音频、动画、Timeline、MathExpression、PlayerPrefs 等 Unity/PlayMaker 动作。`ParticleSimulateAction` 的 Simulate 是 `ParticleSystem.Simulate`，并非卡牌模拟。`local-rules/Blizzard.T5.PlayMakerCustomActions.Runtime.decompiled.cs:4522`、4552。 |
| `Blizzard.T5.NativeApis.dll` | 全程序集反编译。原生调用为内存/磁盘等系统信息；所见导入是 `GetProcessMemoryInfo`、`GlobalMemoryStatusEx`、`GetDiskFreeSpaceEx`。`local-rules/Blizzard.T5.NativeApis.decompiled.cs:300` 起。 |

## 5. 原生转发、搜索范围与不确定性

对 `Assembly-CSharp.dll` 和 `Assembly-CSharp-firstpass.dll` 导出了完整 ECMA-335 `ImplMap` 原生导入表，前者还导出了 `ModuleRef`。文件保存在 `local-rules/*.ImplMap.txt` 和 `Assembly-CSharp.ModuleRef.txt`。

- 主程序集共 14 条显式 P/Invoke 导入，指向 `commerce_http_client`、`user32.dll` 和 `__Internal`，用途为 HTTP 客户端、窗口操作、IL2CPP 句柄/调用栈；没有看见直接委派到本地战斗 DLL 的显式导入。
- firstpass 的 20 条导入属于 tracert 和 AntiCheatSDK 包装；只查看元数据，未研究或操作反作弊功能。
- 四个上述 T5 候选程序集的嵌入资源列表未返回嵌入资源。
- 搜索了主程序集完整类目录（包括 Practice/Tutorial/AI/Offline/Mock/Simulation/Power/Rule/Server 等候选）及 firstpass 类目录；候选不是仅凭名称排除，上表核心候选都进一步读取了方法体。
- 安装的 `Hearthstone_Data/Plugins/x86_64` 文件名及大小已盘点，但没有对所有原生 DLL 逐一做机器码反汇编。
- 本报告没有穷尽 CASC 包和全部 Unity 资源，也没有全量逐方法检查主程序集；不能排除未到达的代码路径、动态加载、下载资源或测试设施。但已追踪的练习/教程建局、输入和 AI 展示路径均不提供独立权威战斗引擎。

检查源程序集大小、SHA-256 和反编译器版本记录在 `local-rules/source-inventory.json`。主程序集 SHA-256 为 `EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B`。

## 6. 主程序集全文检索后的交叉检查

另一条检查路径生成了 `reports/decompiled/full/Assembly-CSharp.decompiled.cs`。对全文检索发现的以下三个特别容易误判的命中，进一步读了整个方法或类型：

- **LuaLogs 不是 Lua 解释器。** 完整类型在全文 773301—773431，单独提取为 `local-rules/LuaLogs.cs`。`Initialize` 注册 GameSetup 网络事件（67），`EnableListeningOnGameServer` 先检查 `IsConnectedToGameServer()`，然后构造监听 quest/achieve/task 的调试指令交给 `CheatMgr.RunCheatInternally`（125—134）。后者解析命令再调用已注册的 callback（全文 767914）；`cheat` callback 注册在 676196，实际 `OnProcessCheat_cheat` 在 681510 再查联网状态，681515 调用 `Network.SendDebugConsoleCommand(rawArgs)`。这里是向服务端请求调试输出，并无脚本加载或执行步骤。所有这些调用只作静态阅读，没有执行。
- **直接 SetTag(DAMAGE, tagValue) 是终结特效预览。** 全文 681889 的 `OnProcessCheat_PlayFinisher` 在 681933 明确要求酒馆战棋/战棋教程；681983 开始手工构造 ATTACK 历史块和两个 TagChange，将 ATK 与 DAMAGE 都赋值为根据 small/large 参数选择的 1 或 999（681994—681997），再在 682002 交给 `PerformTaskListOnCurrentGameState` 播放。没有基于攻防、护甲、免疫等计算伤害，更不属于传统炉石规则。
- **另一个 DAMAGE=0 是隐藏实体清理。** 全文 `Entity.OnHideEntity`（702961）用 EntityDef 恢复 ATK/HEALTH/COST，DAMAGE 置 0（702968），再 `SetCardId(null)`。这在处理网络 HistHideEntity 时清理可见属性，不是治疗或伤害结算。

全文关键字检索扩展了候选覆盖范围，但仍不等于逐方法语义审计；上节关于原生代码和资源覆盖边界仍然适用。
