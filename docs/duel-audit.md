# 自动组卡与对战审计工具

从仓库根目录运行，无额外 Python 依赖：

```powershell
python -B -X utf8 tools/duel_audit.py audit --batch outputs/duel-audit-新批次
```

默认筛选此前对战未覆盖的卡，构筑法师／猎人、牧师／潜行者、萨满／术士六套各30张不同卡的测试牌组。每组两种固定种子、交换双方席位，共12局，串行执行。牌表用于扩大效果覆盖，不代表天梯强度。每批目录必须全新，失败证据也保留。

## 流程与证据

1. 增量导入已有牌表、对战日志及本工具历史，排除已出现的ID、CORE别名和当前目录中同名印刷卡。这里的“未测”仅指已导入的对战记录，不能代表从未有专项测试。历史保存在 `outputs/duel-audit-history.json`；可用 `--history` 指定独立历史。
2. 记录Git身份、工作区状态、全部依赖文件哈希，冻结源码／数据／必要外部输入。子进程只加载该冻结源，结果检查其文件未变。未经提交的工具文件不会冒充Git提交内容。
3. 原生构筑校验通过后才建局。不改变生成池、牌效、规则或支付。自动单卡构筑器将要求额外备牌／完整传说套件／特殊牌库大小的来源列入 `plan.json` 的限制清单；这些卡可用显式牌表覆盖。死亡骑士需要显式符文配置。
4. 双方机器人只读各自玩家DTO；选择随机数独立于引擎。每回合最多24个普通操作、64次选择，默认80回合／600步。触发上限记为未完成，不能算通过。原生拒绝、异常或资源失败停止该局，继续其他局；不重抽、不跳过错误后续接假局。
5. 分别测量合法操作查询和提交的墙钟／线程CPU耗时；快照、日志和检查耗时在计时外。成功操作单阶段严格超过500ms即进入性能交接；阈值可配置。失败动作进入功能／资源问题，不能当成优化后的快速成功。
6. 保留完整压缩前后快照及引擎RNG、命令和完整返回、策略RNG、事件、异常链和按局原生replay。`fixtures` 是可复现输入；私有状态只存磁盘，不通过HTTP提供。自然演进缓存，不将不同场景的耗时冒充优化前后对比。
7. 检查明确触发的描述片段，生成 `analysis.json`、`report.md`、未出牌覆盖清单和两类交接包。当前内置抽牌（含烧牌）、护甲和固有关键词的保守片段检查；`--decks` 可为具体卡提供相同类型的 `checks`。复杂效果、反制／等待选择、空牌库和未触发部分保持未验证，打出卡牌不等于整卡正确，也不是官方国服校准。

默认每个计划／执行子进程超时1800秒；`--timeout-seconds` 可调整。超时保留正在执行的命令和阶段，状态为未完成，提交完成情况未知，不伪造成功或耗时。CPU默认绑定Windows第3个逻辑核（`--cpu-mask 4`），同机后台负载仍会影响结果。

## 常用入口

已有 Firestone 匿名样本元数据时，复用本地缓存离线导入，不下载全部 XML：

```powershell
python -B -X utf8 tools/firestone_decks.py --metadata outputs/样本/metadata-original.json --output outputs/新的导入目录
python -B -X utf8 tools/duel_audit.py audit --batch outputs/新的对战目录 --decks outputs/新的导入目录/selected-decks.json --seeds 2026110401 --cpu-mask 1
python -B -X utf8 tools/firestone_decks.py --verify-batch outputs/新的对战目录 --compatibility outputs/新的导入目录/compatibility.json --output outputs/新的导入回放核验目录
```

`compatibility.json` 保留原卡组代码、DBF ID、张数、备牌及来源对局版本，逐套执行当前原生构筑验证。记录方卡组互相配对为新对局，不能当作原 XML 对局重演或原胜率复现。源版本与本地固定目标分别记录；当前禁用卡不替换、不放宽合法池。代码没有符文字段，仅唯一受卡牌要求约束的配置可自动确定，剩余符文有歧义的牌表保持待确认。没有卡组代码的源记录明确列出。

默认导出六个指定职业中各自样本次数最多的可用原牌表；空缺不拼造新卡组。原牌表可能共享中立卡，因此显式输入可设置布尔值 `allow_shared_cards: true`；默认仍要求两侧卡牌 ID 不重复。此开关只解除宿主的选牌偏好，所有原生职业、数量、符文、备牌与合法性检查仍执行。

`--verify-batch` 用批次自己的冻结引擎逐套核对原代码的 DBF 身份、张数、备牌及构筑字段，严格恢复每局初始和最终完整快照（含 RNG），读取实际保存的原生回放并比较最终完整状态；核对冻结源码 SHA。它不等于恢复全部中间边界，不是 Firestone XML 动作翻译器。

有限版本交付可用 `duel_audit_release_check.py --fixtures-only`，只执行指定真实动作、完整after/RNG与v2保存读取，不自动加入旧v1或混合模式额外场景；模式/回放专项另按实际改动选择。原完整检查入口仍要求旧回放及对应after参数。

HTTP参考签名必须同时匹配资源环境。`duel_audit_bench.py` 按**自身脚本路径**选择同根的 `web_ui/static`；从主树执行和从不含静态图像的冻结树执行，`card_art`映射可能不同。不得删除此字段或扩大规范化来通过完整响应比较；对齐原实际资源上下文，并另用正常卡图检查真实页面，保留最初失败证据。`duel_audit_views.py`现导出真实actor的before/after玩家投影，浏览器可核对没有scene.turn附注的旧夹具；随从出牌检查实际点击原命令指定的位置。

```powershell
# 先生成并审阅牌表，然后执行同一冻结版本
python -B -X utf8 tools/duel_audit.py plan --batch outputs/duel-audit-新批次 --classes warrior paladin --seed 101 --seeds 101 102
python -B -X utf8 tools/duel_audit.py run --batch outputs/duel-audit-新批次

# 执行中读取完整日志行，不将批次标为完成
python -B -X utf8 tools/duel_audit.py analyze --batch outputs/duel-audit-新批次 --partial

# 从完整before恢复、重新查询和提交，核对完整after（包括RNG）
python -B -X utf8 tools/duel_audit.py reproduce --batch outputs/duel-audit-新批次 --fixture outputs/duel-audit-新批次/fixtures/具体操作.json --output outputs/新的复现目录

# 对完成批次的全部initial/after快照逐个严格恢复，核对完整状态及RNG
python -B -X utf8 tools/duel_audit.py restore-check --batch outputs/duel-audit-新批次 --output outputs/该批恢复检查-新目录
```

`restore-check` 使用批次自己的冻结引擎，保留每个边界的哈希、完整相等结果和异常栈；不修改版本头或删去证明。核验器可晚于冻结执行器添加，其独立源码路径／SHA及冻结引擎身份均写入summary。检查耗时包含读取／严格校验／完整导出，不作为出牌性能数据；一处失败后仍继续其余边界。任何失败都需连同summary和原快照按功能问题交接，不能仅凭原对局接受而认定保存恢复正确。

执行返回码：0表示所有局正常结束且未发现功能待核实项；2表示存在问题、达到预算或超时，不是工具自动修复成功。慢操作即使不影响结束状态也列入性能报告。`plan-worker.log`／`run-worker.log`、`run-status.json` 保留子进程诊断；原生setup失败也有夹具。

显式牌表 `--decks 文件.json` 使用以下结构，原生构筑约束照常执行。两套对战牌表不得共享卡牌ID；缺省时按牌表顺序两两配对：

```json
{
  "decks": {
    "a": {
      "card_class": "death_knight",
      "hero_card_id": "HERO_11",
      "hero_power_card_id": "HERO_11bp",
      "runes": {"blood": 1, "frost": 1, "unholy": 1},
      "sideboards": [],
      "cards": ["这里填写完整且合法的牌表"]
    },
    "b": {"card_class": "mage", "hero_card_id": "HERO_08", "hero_power_card_id": "HERO_08bp", "cards": ["完整合法牌表"]}
  },
  "pairs": [["a", "b"]],
  "checks": {"具体卡牌ID": [{"type": "draw_min", "amount": 2}]}
}
```

## 将问题交给修复会话

CLI不持有Codex凭据，不直接发消息。调用本工具的代理必须复核报告，并在用户已授权的范围内继续完成交接：

1. 运行 `handoff --batch 批次 --kind functionality` 或 `performance`，得到 `send_message_to_thread` 的完整参数；无新问题返回 `pending:false`。
2. 用Codex连接器实际发送。默认功能会话 `01a0ce20-8605-74d1-a6df-5e9bb259108b`，性能会话 `01a19572-6358-7031-80de-83d70dc1b134`；新建批次可覆盖对应参数。保留连接器成功结果。
3. 成功后写入收据JSON，包含 `confirmed:true`、`thread_id` 及实际返回证据，再运行：

```powershell
python -B -X utf8 tools/duel_audit.py ack --batch outputs/duel-audit-新批次 --kind performance --receipt outputs/实际发送收据.json
```

收据记录路径和哈希；同一引擎内容／目标／卡牌／操作／异常分组去重。`ack` 仅是实际发送后的登记，不能提前执行或用虚构收据代替发送。引擎修复后使用新批次重测，保留原批次和失败证据。可按 `analyze` 重新生成最终报告和待交接数。

## 优化版本的独立比较与测试台

同一规则版本的新引擎应复用原批次完整牌表、种子和CPU配置，以新目录运行。用下列通用入口比较，无需从旧outputs复制脚本：

```powershell
python -B -X utf8 tools/duel_audit_compare.py --before outputs/原基线 --after outputs/优化批次 --output outputs/优化批次/新比较目录
python -B -X utf8 tools/duel_audit_matrix.py --before outputs/原基线 --after outputs/优化批次 --fixtures outputs/真实夹具索引.json --output outputs/优化批次/新冷热目录 --samples 3 --cpu-mask 1
```

比较器逐条核对命令、完整reply、策略RNG及全部完整私有initial/after快照。基线没有记录的完整legal query或独立双方输出不能声称已做逐步比较；固定夹具矩阵另行核对完整初始query、reply、双方输出和状态/RNG。宿主`checks[*].evidence.keywords`来自集合，可只对该诊断字段排序并保留类型、成员、重数及原前后值收据；其他列表和完整API/快照/RNG严格比较，原失败目录保留。

夹具索引为`{"场景名":"绝对fixture.json路径"}`。矩阵串行交替源顺序，保留每次普通和实际HTTP样本及不利值；代码/注册表已加载，冷态在query及submit前分别清材料缓存、候选缓存和每局frame编码缓存，暖态自然重复，GC保持启用，无Profiler混入。HTTP走生产Handler/Host授权及路由；比较完整响应时只剔除每次随机生成的宿主opponent ticket，范围显式记录。小样本不能推断P95，快照/断言/恢复/IO不算native提交。

可给优化批次启动独立端口，继续使用现有HTML。`ui-fixtures.json`格式为`{"场景名":{"label":"显示名","fixture":"绝对fixture路径"}}`；基础三组或更多牌组由批次plan直接读取：

```powershell
python -B -X utf8 tools/duel_audit_ui.py --batch outputs/优化批次 --fixtures outputs/ui-fixtures.json --output outputs/优化批次/新UI目录 --port 8797
python -B -X utf8 tools/duel_audit_views.py --source outputs/优化批次/frozen-source --fixtures outputs/真实夹具索引.json --output outputs/优化批次/新UI预期.json
node tools/duel_audit_browser.mjs --server outputs/优化批次/新UI目录/server.json --views outputs/优化批次/新UI预期.json --output outputs/优化批次/新浏览器目录
```

UI adapter只替换注册表/开局/真实夹具和菜单，出牌权限、投影、操作与AI仍走生产Host；不操作旧服务。浏览器脚本核对开局/AI换牌、10费、对手回合、宽窄布局、卡图解码和已提供的无目标出牌／单项选择／拼装／结束回合。目标/站位等额外手势须按实际场景扩展，不能冒称覆盖。派生生命/攻击通过冻结引擎的真实玩家投影比较，不从原始序列化字段臆算；武器耐久也不当生命。截图必须人工实际查看，JSON和控制台/资源错误均保留。

## 发布模式变更的有限复核

R17起release动作不自动计算整局state_hash与每步events_hash；返回及历史摘要为None是声明的诊断契约变化，玩法动作记录、完整快照/API/RNG仍须严格核对。显式导出使用replay schema2计算最终完整状态及全部事件摘要，debug动作保留实际逐步摘要，旧v1仍须原样严格读取。不能删除快照/API/RNG字段或改旧版本头来通过比较。

已有完整对照样本时，有限复核只跑新源，复用旧完整语义签名：

```powershell
python -B -X utf8 tools/duel_audit_matrix.py --before outputs/原环境 --after outputs/新计划 --fixtures outputs/真实夹具索引.json --reference-results outputs/原环境/paired-matrix --output outputs/新计划/有限复核 --samples 1 --cpu-mask 1
python -B -X utf8 tools/duel_audit_release_check.py --batch outputs/新计划 --fixtures outputs/真实夹具索引.json --legacy-replay 原v1.json --legacy-after 原最终快照.json.gz --output outputs/新计划/新回放复核目录
```

reference模式只验证完整语义并保留新样本，`paired_timing_comparison=false`，不把旧三样本中位数与新单点当配对性能收益。release-check核验真实场景摘要None、v2保存/读取、旧真实v1和篡改拒绝、release/debug混合回放；仍对完整快照直接比较。新UI可传`--title "炉石测试台 · R17"`，浏览器可用`--pairs pair-1`缩小开局范围。有限计划不等于已经运行12局；报告必须列明实际范围及未执行内容。
