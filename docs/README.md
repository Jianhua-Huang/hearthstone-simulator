# 文档导航

第一次使用请先读[项目首页](../README.md)，启动与操作细节见[网页界面说明](web-ui.md)。

| 需要了解什么 | 文档 |
| --- | --- |
| 当前交付与下一步 | [项目状态](project-status.md) |
| 尚未完成的规则与支持范围 | [机制清单](mechanism-backlog.md) |
| 长期目标和阶段顺序 | [路线图](roadmap.md) |
| 引擎结构和结算约定 | [架构](architecture.md) |
| 如何接入卡牌和机制 | [扩展指南](extensions.md)、[补卡流程](card-integration-plan.md) |
| 自动对战与问题定位 | [审计工具](duel-audit.md)、[界面诊断](web-ui-diagnostics.md) |
| 性能与运行模式 | [性能契约](engine-performance-plan.md) |
| 需要正式环境核实的边界 | [待验证规则](pending-rule-boundaries.md) |

`m1-` 至 `m5-` 开头的文件是按功能拆分的实现契约，供修改对应代码时参考。单篇描述的是其明确范围；实时版本与完成状态以项目状态为准。

逐批机器收据、重复测试输出和完整开发流水账保留在本地忽略的输出目录及 Git 历史中，不随正常仓库检出。必要运行数据位于 `data/reference/`，必要测试证据位于 `tests/fixtures/`。旧契约中的历史本地证据链接只用于查出处。
