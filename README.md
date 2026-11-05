# 炉石对战模拟器

一个用 Python 编写的炉石传统对战模拟器。它在本地执行出牌、攻击和卡牌效果，不需要启动炉石客户端，也不需要登录战网。战斗引擎不依赖动画，附带一个方便手动试牌的网页界面。

你可以用它验证卡牌互动、重现特定局面，或为自动对战、策略实验提供规则执行环境。

**项目仍在开发，当前以标准模式为主。** 已接入大量真实卡牌和战斗机制，但部分生成卡依赖、特殊卡池和规则边界仍待完善或核实。目前不能视为最新国服全部卡牌、全部规则的完整复刻。

## 先运行起来

需要 Python 3.11 或更新版本，推荐使用项目当前验证的 Python 3.12。引擎和网页演示只使用 Python 标准库，无需先安装 `requirements.txt`。

```powershell
git clone https://github.com/Jianhua-Huang/hearthstone-simulator.git
cd hearthstone-simulator
python -B -X utf8 -m web_ui.server --port 8765
```

浏览器打开 **[http://127.0.0.1:8765/](http://127.0.0.1:8765/)**，终端保持运行。按 `Ctrl+C` 停止；端口被占用时，把命令和浏览器地址中的 `8765` 换成其他端口。

### 在网页里试牌

1. 选择“测试场 · 即刻出牌”或“构筑开局 · 含换牌”，创建对局。
2. 拖动手牌出牌、拖动随从攻击，也可以点击卡牌后选择高亮目标。
3. 选择“电脑托管”让对手自动操作，或使用“双人手动”交接座位。
4. 用“选牌测试”搜索已接入的卡牌并加入手牌，配合“设为 10 费”验证效果。
5. 用页面的导出功能保存测试记录；需要检查细节时展开调试面板。

这个入口使用固定的代表卡演示预设，适合快速体验和验证机制。选牌目录不是完整官方收藏库；加入手牌也不会自动满足卡牌所需的资源和触发条件。更多操作见[网页界面说明](docs/web-ui.md)。

## 不打开网页也能运行

在项目根目录执行。以下示例会把回放写入本地 `outputs/` 目录。

```powershell
# 跑一场小型机制演示，并保存回放
python -B -X utf8 -m hs_sim demo --seed 7 --replay-out outputs/demo-replay.json

# 重新执行回放，检查最终结果
python -B -X utf8 -m hs_sim replay outputs/demo-replay.json

# 按预设局面和操作顺序，观察复生、沉默等真实卡牌效果
python -B -X utf8 -m hs_sim simulate examples/scenarios/reborn.json --actions examples/actions/reborn.json --card-set representative --events --replay-out outputs/reborn-replay.json

# 重放真实代表卡示例时，选择相同的卡牌包
python -B -X utf8 -m hs_sim replay outputs/reborn-replay.json --card-set representative
```

`demo` 使用合成测试牌，主要展示引擎如何运转；`--card-set representative` 使用真实代表卡实验包。更多可运行局面在 [examples/](examples/)，命令参数可用 `python -m hs_sim --help` 查看。

## 可以做什么

| 能力 | 用途 |
| --- | --- |
| 双方对局 | 处理换牌、回合、法力、攻击、英雄技能和胜负 |
| 卡牌效果 | 执行伤害、治疗、战吼、亡语、发现、变形、复制等效果 |
| 特殊机制 | 已有复生、磁力、巨型、泰坦、星舰、灌注、兆示等机制的实现 |
| 局面与回放 | 保存和恢复局面，使用固定随机种子复现过程 |
| 程序接口 | 获取某位玩家可见的局面、合法操作，并提交动作 |
| 网页试牌 | 手动操作、电脑托管、添加测试手牌和查看结算记录 |

机制已实现不代表所有相关卡牌都已完整验证；具体卡牌还可能依赖专用生成池或额外规则。

## 接入自己的程序

下面从附带的构筑预设创建对局，读取玩家 1 的局面和可执行操作：

```python
import json
from pathlib import Path

from hs_sim.engine import Game, MatchSetup
from hs_sim.engine.representative import build_registry

setup = MatchSetup.from_dict(
    json.loads(Path("examples/matches/constructed.json").read_text(encoding="utf-8"))
)
game = Game.from_decks(setup, build_registry())
player = game.for_player(1)

print(player.observe())
print(player.legal_actions())
```

开发自动对战策略时，通过 `game.for_player(...)` 读取该玩家可见的信息和操作。完整快照用于可信宿主保存、恢复对局，不应直接作为玩家或策略的输入。完整示例见 [examples/play_as_players.py](examples/play_as_players.py)。

## 当前需要了解的限制

- **标准优先，狂野后置。** 标准卡实际会生成的旧卡仍需逐项支持，不能仅凭其所属系列判断是否可用。
- **标准宿主与演示预设分开。** 完整本地标准入口是 `hs_sim.local_pool_format.build_cn37_local_pool_format()`；所需固定数据已随仓库提供。上面的网页演示和代表卡示例使用独立预设。
- **部分规则采用已记录的本地近似。** 官方 AI、个别专用卡池及难以复现的互动仍有待核实；已有数据和内部测试不等于官方规则认证。
- **网页托管是简单测试策略。** 它用于推动对局和验证效果，不代表竞技水平。
- **旧存档可能不兼容新版本。** 复现问题时，请一起保留代码版本、卡组、随机种子和回放文件。

日常运行默认使用 `release`。排查结算问题可加 `--mode debug` 开启更详细的检查与日志；正常试牌通常不需要。

## 项目文件怎么找

| 路径 | 内容 |
| --- | --- |
| [hs_sim/engine/](hs_sim/engine/) | 对局规则与结算引擎 |
| [hs_sim/cards/](hs_sim/cards/) | 真实卡牌效果实现 |
| [data/](data/) | 卡牌定义、固定卡池和来源数据 |
| [web_ui/](web_ui/) | 本地网页演示 |
| [examples/](examples/) | 可运行的局面、牌组和程序示例 |
| [tests/](tests/) | 机制和卡牌测试 |
| [tools/](tools/) | 数据提取、验证和开发辅助工具 |
| [docs/](docs/) | 使用说明、设计文档与开发记录 |
| [data/reference/](data/reference/) | 运行时需要的固定来源数据 |
| [tests/fixtures/](tests/fixtures/) | 回归测试需要的存档和证据 |
| `outputs/` | 本地回放、日志和测试产物，不纳入 Git |

运行模拟器不需要客户端提取或反编译。`requirements.txt` 中的 UnityPy 供可选的客户端资源研究工具使用。

## 参与开发或反馈问题

反馈时尽量提供卡牌名称或 ID、预期效果、实际结果、复现操作，以及对应的回放或日志。完整快照可能包含双方隐藏信息，分享前请确认内容。

开发文档可以按需要阅读：[架构说明](docs/architecture.md)、[扩展指南](docs/extensions.md)、[长期计划](docs/roadmap.md)。详细进展保存在[项目状态](docs/project-status.md)和[机制清单](docs/mechanism-backlog.md)中，历史条目按当时版本记录。
