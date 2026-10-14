# 本地客户端逻辑检查

检查日期：2026-09-23。仅静态读取安装文件，没有启动客户端、连接对局、修改安装目录，也未读取账户、令牌或用户对局日志。

## 结论

该安装包含可直接读取的 Unity Mono 托管程序集，能提取卡牌字段、游戏标签、枚举、网络状态结构及客户端处理规则。已检查的核心路径显示：客户端将操作选项提交给连接 API，并消费服务器发回的合法选项与 PowerHistory/TagChange 结果。因此，本次没有找到可直接抽离后独立运行、覆盖完整卡牌效果的权威战斗引擎。此为已检查程序集路径的证据判断，并非对所有安装字节的穷尽证明。

无动画模拟器的可行实现是：复用本地卡牌静态数据和标签定义，自建独立规则引擎；另可按照客户端的状态事件结构实现日志重放器，但“重放已有结果”不能替代“计算任意下一步结果”。

## 安装与证据

- 核心程序集：`D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll`，22,684,672 字节。
- SHA256：`EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B`。
- 构建号证据：当前程序集 `Hearthstone.HearthstoneApplication` 初始化路径调用 `UberText.Job_LoadCachedData(...)` 时直接传入编译常量 `251952`。安装 `Data/config` 中同时找到 `build-name = 251952_36.6.0`，两者一致；程序集还包含 UTF-16 字符串 `36.6.0`，此字符串仅作旁证。安装内也残留 `242566_35.4.2` 配置，不能只取任意配置文件的版本。`Hearthstone.exe` 的 `6000.3.11` 是 Unity 运行时版本，不是炉石游戏版本。
- 同目录有 UnityEngine、Blizzard T5、网络及 Protobuf 相关程序集；不是只有图像资源的安装。
- `GameState.SendOption()`：把当前 options ID、main option、target、sub option、position 交给 `Network.Get().SendOption(...)`。
- `Network.SendOption(...)`：进一步转发 `m_connectApi.SendOption(...)`。
- `Network.GetOptions()`：通过 `m_connectApi.GetAllOptions()` 取得 `PegasusGame.AllOptions`，转换成客户端 `Network.Options`。
- `GameState.OnAllOptions(Network.Options)`：接收并保存选项列表，用于目标选择、战吼标记和高亮。`GetErrorType` 等查询依赖这份 options 数据。
- `GameState.OnPowerHistory(List<Network.PowerHistory>)`：转交 `PowerProcessor.OnPowerHistory`。
- `PowerTask.DoTask()`：按网络事件类型调用 `GameState.OnTagChange`、实体创建与元数据处理等；`DoRealTimeTask` 同样消费网络记录。
- `GameState.OnTagChange(Network.HistTagChange)`：把事件中的 Tag / Value 赋给对应实体，并触发状态/显示回调。这段路径消费计算结果，而不是自行执行卡牌规则。
- `PowerProcessor` 含 SpellController prefab、暂停、动画时序与任务队列处理，不能因为名称含 Power 就当作服务端效果解释器。
- 名为 `MockGIServer` 的类型只是返回三个消息 ID 的示例消息服务，不是对战服务器。

## 卡牌属性的正确读取入口

`CardDef` 主要是 Unity prefab 的图片、材质、模型、特效等显示引用，不应当作为完整战斗规则来源。

真正的实体静态属性加载路径：

1. `DefLoader.LoadAllEntityDefs()` 获取卡牌 ID 集合。
2. `EntityDef.LoadBatchCardEntityDefs(...)` 调用 `GameUtils.TryGetCardTagRecords(cardId, out records)`。
3. `GameUtils.TryGetCardTagRecords` 把字符串卡牌 ID 转为 DBID，转交 `GameDbf.GetIndex().TryGetCardTagRecords`。
4. `EntityDef.LoadTagFromDBF` / `LoadTagFromDBF_SetTags` 从 `CardTagDbfRecord` 设置属性。

`CardTagDbfRecord` 字段：

| 序列化字段 | 公共字段 | 用途 |
|---|---|---|
| `m_cardId` | `CardId` | 卡牌 DBID |
| `m_tagId` | `TagId` | GAME_TAG 数值 |
| `m_tagValue` | `TagValue` | 数值 |
| `m_isReferenceTag` | `IsReferenceTag` | 引用属性标记 |
| `m_isPowerKeywordTag` | `IsPowerKeywordTag` | 效果关键词标记 |

客户端合并规则：普通项调用 `SetTag`；引用项调用 `SetReferencedTag`；当引用项同时为效果关键词时，还调用 `SetTag`。提取数据时应保留这两个标记，而不是把所有记录无差别合并成单一属性字典。

## 已生成数据

`data/schema/enums.json` 从此安装的程序集反编译导出，顶层为枚举名，值为“成员名 → 整数”的对象。含 `GAME_TAG`（1,179 项，包括 MODULAR=MAGNETIC 等别名）及 24 个 `TAG_*` 枚举，包括类型、种族、职业、稀有度、区域、步骤、卡牌系列、法术派系等。

该文件不等于卡牌效果实现。比如 DEATHRATTLE 标签能说明卡牌有亡语，但无法单凭该值推导亡语做什么、触发顺序或随机目标选择。

## 方法

使用临时目录安装的 ILSpy CLI 11.1.0.9782 静态反编译特定类型；未执行游戏程序集。枚举整数由 ILSpy 输出解析导出。

可重跑 `python tools/extract_enums.py`（也支持 `--install-dir`、`--assembly`、`--ilspy`、`--output-dir`）。脚本拒绝输出到安装目录，比较提取前后的程序集 SHA256；遇到并发更新则报错且不写输出。`data/schema/enums.source.json` 保存程序集路径、大小、前后 hash、ILSpy 版本和提取时间，供数据管线检查版本一致性。
