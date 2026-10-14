# M5-13d-02m-01-B1：持续来源条件与另一物理实体

2026-10-04，已内部验收，未国服校准。运行规则/效果105、snapshot schema102；玩家观察52、动作7、外层replay1和代表内容64保持。没有新增真实卡，305完整记录/306定义/14条choice-only保持。当前事实与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。

本增量扩展已有[法术双窗口](m5-spell-match.md)，R-151为待国服校准的公共内部契约，不证明任一正式卡池或条件重复整族完整。A2的[既有验收](../outputs/v109-verification.json)不能当作B1通过。

## 声明与见证资格

`RepeatMatchSpec.source_eligibility` 可引用不可变 `RepeatSourceEligibility(profile_id, tribes_any=(), exclude_carrier=False)`。本批仅允许有实际场上随从载体的 `spell_repeat`；玩家政策、物理 `card_spell_repeat` 和没有载体上下文的静态 matcher 明确拒绝该条件。

```python
SpellRepeatSpec(casts=2, class_mode='any', match=RepeatMatchSpec(
    recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)),
    source_eligibility=RepeatSourceEligibility(
        'repeat.witness.controlled', tribes_any=('dragon',), exclude_carrier=True)))
```

见证是该窗口载体控制者战场上的物理随从。`exclude_carrier` 排除实际载体ID，不能排除同卡名的所有副本、能力授予者或来源卡面。空 `tribes_any` 表示任意合格随从；非空列表为OR，复用纯印刷元数据谓词，支持多种族及all语义。卡面依据固定为 `current_face_printed`，变形后使用当前注册卡面；不把印刷种族和当前属性混为一谈。

注册表保存完整 `RepeatWitnessProfile` 并将参数加入指纹。默认两种政策分别是：

| profile | 休眠 | 建造星舰 | 已标记死亡 | 必须正生命 |
| --- | --- | --- | --- | --- |
| repeat.witness.controlled | 包含 | 排除 | 包含 | 否 |
| repeat.witness.active_live | 排除 | 排除 | 排除 | 是 |

其他政策必须显式注册。上述政策是R-151本地选择，未校准；并非所有正式卡牌统一采用同一presence。见证资格独立于载体贡献资格：载体仍遵循既有活跃、存活、未消费的场上来源契约。

`qualifying_repeat_witnesses` 只返回完整、有序的物理ID元组，不产生效果、事件、用途消费或随机变化。声明及profile先验证；每个活跃来源在较晚接受窗先完整查询全部结构合格见证，再与接收法术的学派/职业相交。已知第一项匹配不能隐藏后项必需元数据缺失，接收法术不匹配也不绕过该来源的完整查询。被排除载体、敌方、地标及不符合presence的实体不要求无关元数据；空种族查询不要求未使用的种族字段。查询不是玩家观察或合法动作枚举的一部分。

## 接受窗口与后续变化

付费手牌法术继续使用既有提交窗和关闭目标/反制后的场上窗口，不新增时序或用途消费。来源条件、完整贡献集合及max总次数在较晚窗口同时接受。全部条件为假仍保存明确的单位接受收据与活动完整证明；空主体、反制及FinishPlay后续待选保持原接受义务。反制不执行场上见证查询。

当前根接受后，见证或载体被沉默、变形、转控、回手、死亡或新增时不重新分类。新的真实付费手牌根重新查询；普通回溯重建窗口，保留多结果沿用其已接受计划。原本无贡献的来源后来变真，不能补入当前根；原本贡献的来源后来变假，不能减少当前根次数。

`spell_repeats.execution_count` 仅读取已经接受的payload次数。没有payload时明确拒绝，不能因尚未建立action window而猜测窗口已闭，或提前进行来源查询。

## 身份、恢复与信息

恢复从两个原全状态窗口重算来源真值、完整贡献和计划；见证ID仅是临时查询结果，不另存到紧凑历史，不以live见证重判历史。活动证明还对全部原 `spell_repeat` 附件进行双向身份绑定，包括false和非贡献来源：提交到较晚窗口、两个原窗口到当前状态都校验存续ID、物理载体及完整静态声明。允许后续消费、合法移除和新ID分配，拒绝原证明删去存续来源、同ID改声明、逆转消费及跨载体/跨族冒充。不提供未签名存档的外部来源认证。

完整 `source_eligibility` 私有wire必须显式存在或为null；缺字段不是默认无条件。注册、授予、所有区域附件、死亡历史、原上下文、回溯状态和FrameCodec均验证声明与已注册profile。旧schema1～101需相应原引擎。

玩家观察v52与已有四类玩家政策事件仍采用仅 `recipient_metadata` 的公开match形状。场上条件、内部实体/附件ID、见证、完整证明和接受收据不加入玩家DTO；公开政策解析器拒绝board-only条件。合法操作与回放继续使用公共玩家入口。

## 验证范围与保留工作

必要合成专项验证种族OR/all/空、物理another、显式presence、完整未知元数据、双窗变化、false→true与true→false、低等高max来源、生命周期、嵌套根、选择/保存/克隆/独立注册表回放、普通与保留回溯、重定向/反制、异常回滚/预算/终局及玩家隔离。[原生合成示例](../examples/repeat_source_conditions.py)和全量回归已获得本批实际终态；完整验证结果与证据入口见[项目状态](project-status.md)。

仅开放场上法术重复的持续来源子集。逐族匹配B2、费用依据、逐主体次数、周期计数、额外一次、Whenever CAST、动态主体和特殊来源仍保留M5。M0正式池与热修、M6国服校准、M7批量接卡及完整目标均未完成。
