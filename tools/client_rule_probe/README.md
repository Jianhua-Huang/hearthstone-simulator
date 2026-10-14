# 客户端局部规则片段验证

此工具证明客户端有可离线执行的局部数值公式。它从反编译输出中抽取原方法体，提供最小依赖桩后编译；不加载、注入或执行整个游戏客户端，不是完整战斗模拟器。

前置条件：PowerShell 7（支持 `Add-Type`、当前 .NET 的 `SHA256.HashData`）与 ILSpy CLI `11.1.0.9782`。本次被检查 DLL 的 SHA-256：`EB88E1C6E6833BDDC3198BADC043959302942D64AA8EC716656AB3A65D8C746B`。

在仓库根目录运行以下命令。反编译结果保留在已忽略的本地目录：

```powershell
New-Item -ItemType Directory -Force -Path reports\decompiled\entity | Out-Null
& "$env:TEMP\hs-inspect-tools\ilspycmd.exe" -t Player 'D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll' > reports\decompiled\entity\Player.cs
& "$env:TEMP\hs-inspect-tools\ilspycmd.exe" -t TextUtils 'D:\游戏\Hearthstone\Hearthstone_Data\Managed\Assembly-CSharp.dll' > reports\decompiled\entity\TextUtils.cs
pwsh -NoProfile -File tools\client_rule_probe\verify_formula_fragments.ps1
```

已有本次反编译输出时，仅需最后一条命令。每次用新的 PowerShell 进程运行，避免 C# 类型重复加载。可以用 `-DecompiledDirectory <目录>` 指定另一个输出目录。

保留验证结果：

```powershell
pwsh -NoProfile -File tools\client_rule_probe\verify_formula_fragments.ps1 > reports\decompiled\entity\formula-verification.json
```

提取方法：

- `Player.TotalSpellpower`：`Player.cs:275–321`。
- `TextUtils.TransformCardTextImpl`：`TextUtils.cs:288–391`。
- `TextUtils.SafeAddInt`：`TextUtils.cs:393–404`。
- `TransformCardTextParams`：`TextUtils.cs:7–20`，仅属性容器。

方法体不改写。桩包含 `GAME_TAG/TAG_SPELL_SCHOOL` 枚举、一个以字典实现的实体标签容器以及 `StringBuilder` 缓存。枚举值仅为局部测试方便自动分配，不能拿来当游戏协议编号。`GetTag` 默认值 0、`HasTag` 等价于 `GetTag > 0`；不会计算法伤光环或执行任何游戏效果。

JSON 输出包含每个方法片段的起止行、SHA-256 与 9 个实际结果。片段哈希规范是：`Get-Content` 去除原换行，各行以 LF 拼接，无末尾额外 LF，以无 BOM UTF-8 编码后 SHA-256。源码布局检查防止误用另一版反编译文件；客户端升级后应重新检查方法和提取区间。

9 个案例覆盖普通/奥秘/符咒/无派系法伤，伤害先加后翻倍、负伤害下限、整数溢出饱和、治疗翻倍以及治疗显示分支没有负值下限。完整证据与局限见 [分析报告](../../reports/entity-rules-analysis.md)。
