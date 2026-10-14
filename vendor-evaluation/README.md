# fireplaceAharaLab 独立评估

评估日期：2026-09-23。对象是传统炉石构筑逻辑，不评估酒馆战棋或 AI 棋力。

上游：<https://github.com/aharalabMeiji/fireplaceAharaLab>，锁定提交 `da7bcd6acd634c76446071171d9ca39235a8e107`。克隆保留在 `fireplaceAharaLab/`，未修改上游受版本控制的源文件。上游最近一次提交是 2025-08-13 的 README 更新；应用目录最近一次提交为 2023-05-07。

## 文件

- `REPORT.md`：最终评估结论、覆盖表、测试结果与已知缺陷。
- `audit.py`：卡池盘点、隔离运行上游预置测试、随机对局。
- `probes.py`：独立的确定性牌效及构筑入口检查。
- `summarize.py`：汇总原始结果。
- `requirements-lock.txt`：实际使用的 Python 3.10 环境依赖。
- `results/`：原始 JSON、每个场景的日志、启动失败与测试收集日志。

## 复现

以下命令从主项目根目录执行。运行时使用独立 Python 3.10.21 环境，`hearthstone==5.73.0` 与 `hearthstone-data==163976.1` 按上游 README 固定。

```powershell
vendor-evaluation/.venv310/Scripts/python vendor-evaluation/audit.py inventory
vendor-evaluation/.venv310/Scripts/python vendor-evaluation/audit.py batch
vendor-evaluation/.venv310/Scripts/python vendor-evaluation/probes.py
vendor-evaluation/.venv310/Scripts/python vendor-evaluation/summarize.py
```

单个上游场景可重跑：

```powershell
vendor-evaluation/.venv310/Scripts/python vendor-evaluation/audit.py worker card_test.t_lich_deathknight pp_RLK_035a 0
```

## 口径

- 上游默认 `HEARTHSTONE=3` 是酒馆模式。评估脚本在进程内设为 `1`，加载传统构筑卡池，不写回上游配置文件。
- 上游 `HEARTHSTONE=4` 的测试入口存在卡池选择问题，原样运行的错误另存 `results/original-mode4.log`。批量测试直接调用 `PresetGame`，保留场景及断言代码。
- 批量选择 `t_lich_*`、`t_arthas_*`、`t_rev_*` 模块中直接继承 `Preset_Play` 的 400 个场景类，逐个独立进程、种子 0、`testNr=1`；这不是全部历史测试或全部分支。
- 22 局使用上游 `StandardRandom` 与 `random_draft`，11 个职业均出现，种子 0–21；卡组随结果保存。上游随机卡组不校验死亡骑士符文，故仅为运行稳定性烟雾测试。
- 每项子进程上限 60 秒、并发 6。超时不当作平局或通过。
- `completed` 仅表示未抛异常；没有断言的场景不能当作规则通过。有断言也可能沿用了错误预期，独立检查用于揭示这类问题。
- `assertion_calls` 是对上游 `assertion`/`asserting` 方法的计数包装，不改变其求值或断言；AST 另记录直接 `assert`。
- 注册数量只证明卡 ID 进入运行池及存在脚本，不代表牌效与官方一致。分母来自指定旧数据包，不代表 2026 年卡池。
- 所有运行均启用 Python 断言（未使用 `-O`）。未修改牌效以使测试通过。
