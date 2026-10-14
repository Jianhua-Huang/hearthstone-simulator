# 小鬼与雏龙的印刷分类

`CardMetadata.subtypes` 在既有元信息末尾保存已审核的 `imp` 或 `whelp` 印刷分类。`()` 表示已知无分类，`None` 表示尚不明确，查询未知分类会报错。分类不是普通种族、派系、关键词或名称匹配；“全部种族”不赋予小鬼或雏龙资格。当前仅审核这两个分类，不据此宣称全部分类已穷尽。

`metadata_from_record` 读取完整原始行中的 `IMP` / `WHELP`：仅接受严格整数0/1，缺失为没有该标记。正值仅允许随从；未知值和错误类型拒绝。生产代表及池元信息获得此字段，不自动接入原始数据库的全部卡牌。完整记录和来源钉选见[必要材料](../data/support/minion-subtype-basics.json)。

公共 `has_any_subtype(registry, entity, subtypes)` 读取实体当前卡面的印刷分类，不根据来源 ID、名称或增益猜测。沉默、转控、回手、普通复制不修改卡面分类；变形后查新卡面。已死亡或休眠实体仍可以查询分类，是否为活跃目标由调用方或既有区域候选负责。改变普通种族不授予或移除该分类。

`PoolQuery.subtypes_any` 追加在原参数末尾，过滤随从印刷分类并与已有条件相交。原 `matches_metadata`、生成/发现池和物理区域引用查询复用此条件；非随从不匹配，未知分类明确失败。分类进入 `PoolCard.filter_signature`，不能把分类不同但声明同一生成身份的行错误合并。缺少可执行实现的合法匹配项仍报错，不能从候选池偷偷删去。

卡牌主体沿原公共操作组合。本轮仅完整隔离适配 REV_245 灾祸降临和两个必要白板衍生物 EX1_598 小鬼、ds1_whelptoken 雏龙。灾祸降临从原接受局面捕获本人活跃、正生命、非待消灭的小鬼数量，普通 `Draw(1 + count)` 执行基本抽牌和各次追加抽牌；仅一次原法力支付。具体原接受窗、特殊抽牌过程中分类变化及准确国服行为仍待校准。

官方[奥妮克希亚的巢穴公告](https://hearthstone.blizzard.com/en-us/news/23763644)明确存在雏龙条件；[拉法姆官方卡牌页](https://hearthstone.blizzard.com/en-gb/cards/78363-imp-king-rafaam?set=murder-at-castle-nathria)的检索卡文包含小鬼条件，直接页面正文为脚本容器。二者仅支持存在这种分类需求，不认证完整成员表或国服时序。ONY_004、REV_835、GIL_681及CS2_065仅原始依据，未适配这些完整主体。

分类是定义元信息，不增加 Entity/Player/GameState 字段、分类计数缓存、授予效果或新模块。冻结出牌卡面保存新字段，JSON解码恢复 tuple；待选帧、回放、clone、回滚、信息隔离继续原流程。结构使用 prototype-v302/core-effects-v304/schema265，旧1～264明确拒绝；观察84、命令12、replay1保持。实际进度、证据、已知差异和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。
