# 模型下载前的低成本预判架构

## 目标

完整下载、OCCT 拆分和 Boolean 分类是最贵的步骤。新增的预判层在下载之前回答四个问题：数据大概率属于哪个制造业领域、覆盖哪些工程器件、是否像真实多零件装配、是否值得进入完整分类。

预判只形成“候选优先级”，不产生几何真值。最终准入仍要求 STEP 可读、多 Solid 和现有精确分类流程。

## 五级成本漏斗

```text
L0 DataCite/仓库检索
  → L1 页面元数据、许可、文件名、大小
    → L2 匿名目录树、BOM/parts list、压缩包目录
      → L3 最多 1 MB 头部 + 1 MB 尾部范围读取
        → L4 完整下载 + OCCT 准入
          → L5 Boolean-final 分类与人工抽检
```

只有通过上一层的候选进入下一层。大文件不会因为标题中出现 “assembly” 就自动下载。

## 预判输出

`iteration_engine.prescreen` 对每个候选输出：

- `manufacturing_sector`：增材制造、机器人自动化、机床、汽车与移动装备、航空与透平、医疗康复、流程与流体、科研仪器、机电电子或一般工业设备；
- `engineering_domains`：紧固连接、传动、运动执行、流体、结构外壳、工具加工、电控和人机接口；
- `possible_components`：螺钉/螺栓、螺母/垫圈、轴承、齿轮、轴、带轮/皮带、弹簧、密封、阀泵缸、电机、支架、外壳、电子件、轮组和刀具；
- `assembly_score` 与可解释证据，例如完整装配措辞、BOM、数量、原生装配扩展名、STEP 文件头、`PRODUCT` 和装配关系；
- `decision`：优先下载、先看元数据、人工确认装配、人工确认许可或仅保留元数据/拒绝。

领域和器件标签来自页面与 BOM 的可解释词证据。它们表示“可能包含”，不得回灌成分类器真值。

## 非 Git 自动发现

持续发现现在加入 `mendeley` 适配器：

1. 用 DataCite 按覆盖缺口查询 Mendeley DOI；
2. 读取 Mendeley 匿名目录树；
3. 只保留真实存在的 `.step`/`.stp` 文件；
4. 加入行业、器件和装配置信度；
5. 许可、大小或装配证据不足时不自动暂存。

配置的默认提供方现在是 Zenodo、Mendeley 和 GitHub。GitHub 仍是一个来源，但不再是唯一入口。

## 运行方式

只做本地元数据统计：

```bash
python scripts/prescreen_sources.py
```

对已保存直链做有限范围核验：

```bash
python scripts/prescreen_sources.py --probe
```

重新生成报告但复用已有网络探测证据：

```bash
python scripts/prescreen_sources.py --reuse-probes
```

输出包括 `research/prescreen_report.json`、`research/prescreen_report.csv` 和 `research/channel_acquisition_log.csv`。渠道总表、互补性、问题覆盖和选择审计分别保存在 `research/model_channel_catalog.csv`、`research/model_channel_complementarity.csv`、`research/channel_question_coverage.csv` 和 `research/channel_selection_audit.md`。

## 自动化边界

- 可自动：跨仓库检索、目录/BOM 信号、行业与器件初判、范围读取、格式和许可门禁、候选排序。
- 必须机器实证：OCCT 可读、多 Solid、几何重复分组、稳定性和运行成本。
- 必须人工或法务确认：未知许可、登录门户条款、页面描述与实际几何冲突、关键低置信候选。

这一边界避免两个主要误差：把大量单独标准件误当成装配语料，以及让元数据标签污染几何算法的准确率评估。
