# STEP 几何无监督分组工作流

这是一个无训练、可解释的 STEP/B-Rep 分组系统。它先用几何—拓扑描述符快速生成候选组，再通过刚体对齐和 OCCT 双向布尔差进行独立精确复核，最后将每组导出为单独 STEP 文件并回读验证。

## 环境

- 推荐使用仓库内的 `environment.yml` 创建独立 Conda 环境，其中锁定 Python 3.11 和 OCCT 7.9.3。
- Open CASCADE `DRAWEXE`：程序会搜索 PATH 和 `C:\msys64\ucrt64\bin\DRAWEXE.exe`，也可用 `--drawexe` 指定。

本机验收环境为 Python 3.14.5、Open CASCADE 7.9.3。

```bash
conda env create -f environment.yml
conda activate mbd-pre
./scripts/run_reproduce.sh test
./scripts/run_reproduce.sh sample
```

`test` 验证代码和 OCCT；`sample` 复现仓库内的 84-Solid 示例；`full` 会下载锁定语料并执行完整的长时间评估流水线。

## 运行

```powershell
python .\step_geometry_encoder.py "C:\Users\LENOVO\Desktop\motor.STEP" --output .\motor_v4_output
```

使用仓库内附带的示例数据：

```powershell
python .\step_geometry_encoder.py .\data\input\motor.STEP --output .\motor_v4_output
```

重复调参时可复用标准化零件：

```powershell
python .\step_geometry_encoder.py "C:\Users\LENOVO\Desktop\motor.STEP" --output .\motor_v4_output --reuse-cache --threshold 0.12
```

精确层有三个等级：

- `--precision-mode boolean`（默认）：刚体对齐后执行双向布尔差，适合最终验收。
- `--precision-mode rigid`：验证全部拓扑顶点能否在旋转+平移后重合，适合快速迭代。
- `--precision-mode off`：只运行候选层，用于特征研究，不建议作为最终结果。

`--precision-workers 4` 控制布尔终审的隔离进程数，可根据 CPU 和内存调整为 1～16。

`strict` 模式保留绝对尺寸；`family` 模式的候选层允许整体均匀缩放。注意：默认布尔精确层验证的是同尺寸刚体全等，因而会将不同尺寸的系列件再次分开。

## 处理流水线

1. OCCT/XDE 精确读取并拆分 Solid，生成可缓存的标准化 STEP。
2. 收集质量属性、解析曲面/曲线、AAG、WL 子结构和旋转不变形状统计。
3. 计算拓扑、几何、整体形状和尺寸四通道距离。
4. 用确定性 complete-link 构建候选组，避免链式误合并。
5. 用完整顶点距离指纹求正旋转刚体变换；镜像件不会被当成旋转等价件。
6. 高精度模式对对齐后实体做 `A-B` 和 `B-A`，候选组只会被拆分，不会被精确层跨组误合并。
7. 导出各组 STEP，重新导入后检查 Solid 数、体积和 B-Rep 合法性。

详细设计、失败策略和扩展点见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 持续数据与算法迭代

`iteration_engine` 把一次性脚本组织成两个有门禁的闭环：一条根据 STEP 产品名称和几何覆盖签名寻找覆盖不足的实体类型，再从 DataCite、Zenodo、Mendeley 和 GitHub 定向发现许可明确的装配；另一条在固定 Boolean-final 基准上比较候选阈值的精确组召回和计算工作量，并通过稳定性与人工置信区间决定是否允许晋级。

```bash
python3 -m iteration_engine.cli plan
python3 -m iteration_engine.cli cycle --offline
python3 -m iteration_engine.cli discover
python3 -m iteration_engine.cli cycle --acquire --classify
python3 scripts/prescreen_sources.py --reuse-probes
```

联网发现、下载和长时间分类必须显式启动。元数据预判先估计制造业领域、工程器件和装配置信度；未知许可或低装配证据模型不会自动录用，缺少人工标签时算法候选不会自动晋级。整体架构见 [docs/AUTOMATION_ARCHITECTURE.md](docs/AUTOMATION_ARCHITECTURE.md)，下载前筛选细节见 [docs/METADATA_PRESCREEN_ARCHITECTURE.md](docs/METADATA_PRESCREEN_ARCHITECTURE.md)。

## 可审计输出

- `workflow_manifest.json`：运行 ID、源文件哈希、Git 版本、配置、阶段耗时、质量门禁和产物哈希。
- `workflow_events.jsonl`：逐事件日志，失败时保留阶段和堆栈。
- `data_quality.json`：实体覆盖、未知几何类型、属性异常和距离矩阵校验。
- `precision_report.json`：每条精确复核关系的变换、残差、布尔差体积与通过/失败原因。
- `parts.csv` / `similarities.csv` / `report.json` / `method.json`：数据、相似度分解、分组和方法快照。
- `grouped_steps/manifest.json`：每组导出后的回读数量、体积误差与 `checkshape` 结果。

## 测试与验收

```powershell
python -m unittest -v
.\scripts\validate.ps1 -StepFile "C:\Users\LENOVO\Desktop\motor.STEP" -Output .\motor_v4_output
```

第一条运行单元、性质与小型 OCCT 端到端测试；第二条再执行真实数据验收，并以工作流质量门禁决定成败。

## motor.STEP 发布验收

- 84 个 Solid，18 个候选组，经 72 条迭代精确关系复核后得到 20 个分组。
- 原第 2/3 组的 18 个视觉相同件通过刚体与双向布尔复核，保持在同一组。
- 一个 38 件的候选组被精确分成 31 和 7 件两类；零件 75/76 因无法由正旋转+平移建立全拓扑对应而分开。
- 20 个分组 STEP 全部回读合法，实际 Solid 合计 84，最大体积相对误差为 `3.66×10⁻⁸`。
- 6 个质量门禁全部通过；并行布尔精确阶段耗时约 326 秒。

## 外部装配语料与人工复核

仓库现在包含一套可复现的外部装配评估工作区：29 个许可明确的 STEP 总成来源、断点续传与哈希校验、OCCT 结构准入、批量布尔终审、阈值/输入顺序稳定性分析，以及无需逐个打开 STEP 的风险分层联系表。入口见 [research/README.md](research/README.md)，完整评估协议见 [docs/EVALUATION_PROTOCOL.md](docs/EVALUATION_PROTOCOL.md)。

最终结果必须使用 `--precision-mode boolean`。`rigid` 只用于快速筛查；真实 SO-100 对照表明，刚体模式可能把视觉和顶点均接近、但 B-Rep 实际不同的零件错误合并。

## 边界

- 这是几何等价/相似分组，不会无依据推断零件功能语义。
- 刚体初对齐依赖 B-Rep 顶点；对无顶点、高度对称或退化模型需扩展曲面采样/曲面对应。
- 布尔差是高成本终审；大型数据集应使用缓存、分层复核和并行作业。
- 工程实现与开源许可不能代替正式专利自由实施（FTO）意见。
