# 传统炉石模拟器：客户端规则反编译研究

目标已明确为**传统炉石战斗机制，无需动画**。已完整反编译本机 `D:\游戏\Hearthstone` 的主程序集，追踪出牌、攻击、伤害、死亡、亡语及练习/教程路径。结论：能提取真实局部规则计算，未找到可直接独立运行的完整对局引擎。

先读 [反编译总报告](../reports/traditional-combat-reverse-engineering.md)，其中包含实际调用链、精确源码位置和可复用部分。已将原法伤与文本数值方法体抽出，补最小依赖桩离线编译，**9 项验证通过**；复现见 [局部规则验证工具](../tools/client_rule_probe/README.md)。这不代表完整战斗引擎已实现。

下方保留第一轮的数据提取工具说明；卡牌数据只是辅助材料。

## 直接查询已提取的数据

在本项目目录执行：

```powershell
python -m hs_sim search 火球术 --limit 5
python -m hs_sim card CS2_171
```

实测 `CS2_029` 火球术：4 费，描述“造成$6点伤害。”；`CS2_171` 石牙野猪：1 费、1/1、`CHARGE=1`。描述中的 `$`、`[x]`、HTML 标记等保留原样，不能直接当作效果代码。

## 从客户端重新提取

需要 Python 3.11+；本机验证环境为 Python 3.12 与 UnityPy 1.25.0。安装目录仅作读取，输出写入本项目。

```powershell
python -m pip install -r requirements.txt
python tools/extract_client.py 'D:\游戏\Hearthstone'
```

Unity 版本自动读取 `UnityPlayer.dll`。本机资源去除了内置版本字符串，使用从该 DLL 读到的 `6000.3.11f1` 作为解析版本。遇到无法自动识别时可显式加 `--unity-version 6000.3.11f1`；应使用实际安装的版本。

提取器验证枚举与本地 `Assembly-CSharp.dll` 的 SHA256 是否相符。客户端更新后，先重新导出枚举（需要 .NET 与 ILSpy CLI）：

```powershell
dotnet tool install ilspycmd --tool-path .tools/ilspy
python tools/extract_enums.py --install-dir 'D:\游戏\Hearthstone' --ilspy .tools/ilspy/ilspycmd.exe
python tools/extract_client.py 'D:\游戏\Hearthstone'
```

`--output` 可更换数据输出目录；`--locale` 可选择本地化语言；`--raw` 可额外导出选定 DBF 表的完整原始记录，文件较大。当前仅支持安装中已展开的 `Data/Win/dbf.unity3d`，没有实现 CASC 解析。

## 结果文件

| 文件 | 内容 |
| --- | --- |
| `data/extracted/cards.json` | 36,022 条卡牌记录；中文/英文名与描述、属性、普通/引用/关键词标签 |
| `data/extracted/manifest.json` | 来源路径、SHA256、工具与 Unity 版本、表结构及记录数量 |
| `data/schema/enums.json` | 从此客户端导出的 25 个枚举，含 1,179 个 `GAME_TAG` 成员 |
| `data/schema/enums.source.json` | 枚举来源程序集指纹与提取方法 |
| `reports/client-code-inspection.md` | 本地程序集检查证据及服务端边界 |
| `reports/extraction-results.md` | 提取统计、样例与下一步实现范围 |

提取输出包含历史版本、衍生物、英雄皮肤、测试及佣兵等其他模式记录；**36,022 不代表当前可用卡牌数**。本地数据不包含服务器即时热修或当前活动开关。未知的数字标签完整保留，不猜测含义。缺失的数值保持 `null`，不把“缺少字段”改写为零。自动生成的大型数据文件已加入 `.gitignore`，本地文件仍可直接使用。

普通属性的合并分支按已检查客户端的 `EntityDef.LoadTagFromDBF_SetTags` 实现：引用标签另存；若它也是效果关键词，则同时进入普通标签。单有 `DEATHRATTLE=1` 并不能知道亡语的具体效果。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试覆盖中文/英文/ID 查询、文件错误、缺失值/零值、未知标签保留、引用关键词合并及重复/冲突记录。真实资源的读取和样例牌查询另已实际执行。


