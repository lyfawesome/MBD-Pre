# 技术决策、现有技术与协作记录

更新日期：2026-09-04

本文把项目讨论中会影响算法、实验和知识产权判断的结论固化到 Git。它是工程研究记录，不是法律意见；专利状态只是检索时点快照，商业发布前仍需由专利代理师基于目标国家和最终权利要求做 FTO（自由实施）分析。

## 1. 项目目标与术语

目标不是让精确算法替代快速聚类，而是建立两层系统：

1. **候选层**：从 STEP/B-Rep 提取确定性几何—拓扑向量，以近线性特征计算和受控的成对距离快速形成候选组。
2. **复核层**：只在候选组内用刚体对应、拓扑/曲面约束和可选的双向实体差集提供独立证据。
3. **反馈层**：把误合并、误拆分和无法判定的困难样本写入数据集，用于调整描述符、阈值或训练自监督编码器。

这里的“无监督”是指分组时不依赖人工类别标签。B-Rep 图神经网络并不天然等于有监督学习：它可以采用图增强一致性、对比学习、掩码属性恢复或几何重建等自监督目标。是否有监督由训练目标决定，不由网络结构决定。

## 2. 当前实现如何把几何映射为向量

当前方法不是单个黑箱神经向量，而是可解释的多通道描述符：

- **整体与尺寸**：体积、面积、包围盒主尺度、质心和惯性相关统计，经尺度处理后形成全局特征。
- **几何原语**：平面、圆柱面、圆锥面、球面等曲面类型，以及直线、圆弧等曲线类型的计数和参数统计。
- **拓扑**：Solid/Shell/Face/Wire/Edge/Vertex 数量、欧拉相关量和面邻接图统计。
- **局部结构**：属性邻接图（AAG）与 Weisfeiler–Lehman 子结构摘要，用于区分全局计数接近但连接方式不同的实体。
- **旋转不变量**：距离、方向和形状分布等不依赖装配姿态的统计。

相似度按拓扑、几何、整体形状和尺寸四个通道分别计算，再组合为候选距离。候选聚类使用 complete-link，要求一个组内的所有成对关系都满足限制，从而抑制单链接的链式误合并。

## 3. 精确复核的职责边界

三种运行模式的含义：

- `off`：只运行候选层。它是快速算法本身的输出，也是评估召回率和候选压缩率的对象。
- `rigid`：在候选组内寻找保持手性的旋转加平移，并检查完整拓扑顶点对应。它比快速层多了实例级对应和残差检查，但不是连续曲面实体相等的完备证明。
- `boolean`：刚体对齐后计算 `A-B` 与 `B-A`，结合差集体积、OCCT 操作状态和容差判断。它更接近实体级终审，但仍可能受建模容差、退化边、缝边和布尔鲁棒性影响。

复核结果必须使用三态语义：

- `same`：现有证据支持相同；
- `different`：存在明确的几何或拓扑反证；
- `indeterminate`：对应歧义、内核失败或数值证据不足。

布尔操作失败不能直接解释为 `different`。精确层当前只拆分候选组，不跨候选组合并，因此快速层一旦误拆，精确层无法自动恢复；评估时必须同时测量候选组召回率和精确复核后的纯度。

## 4. motor.STEP 已确认事实

当前冻结基线见 `data/motor_v4_results/BASELINE.md`：

- 输入包含 84 个 Solid。
- 快速层形成 18 个候选组；74 条精确关系中 63 条通过、10 条确认不同、1 条无法判定。
- 最终得到 21 个组，21 个导出 STEP 均回读有效。
- 曾被快速层归为 38 件的候选组在当前 Boolean 基线中被拆成 29、8、1。
- 部件 75/76 的争议来源位于刚体对应阶段：当前算法找不到正旋转加平移下的完整拓扑对应。视觉相似不能单独证明它们刚体全等；此案例应保留为人工标签和算法反例，而不是静默接受复核结论。

## 5. 可复用的开源工程

以下项目分别覆盖候选检索、配准、B-Rep 表征或精确度量，不等同于本仓库的完整两层流程：

| 项目 | 可借鉴内容 | 与本项目的差异 |
| --- | --- | --- |
| [shapematch](https://github.com/TobyBorland/shapematch) | 仿射不变特征点直方图、SVD 变换和表面采样偏差 | 更偏两个形状的直接匹配，不负责装配拆分、候选聚类和审计闭环 |
| [Open3D](https://github.com/isl-org/Open3D) / [Global registration](https://www.open3d.org/docs/latest/tutorial/pipelines/global_registration.html) | 下采样、FPFH、RANSAC 粗配准和 ICP 精配准 | 面向点云；B-Rep 拓扑、曲面参数和 STEP 回写需另建 |
| [BRepMatching](https://github.com/deGravity/BRepMatching) | 学习 B-Rep 拓扑对应 | 依赖学习与 Parasolid 环境，目标是对应而非完整无监督分组工作流 |
| [UV-Net](https://github.com/AutodeskAILab/UV-Net) | 面—边 B-Rep 图编码器 | 提供表示学习基础，不包含独立精确复核层 |
| [3D_STEP_Classification](https://github.com/divanoLetto/3D_STEP_Classification) | STEP 转图、GCN 分类与检索 | 以监督分类为主，不能直接证明几何等价 |
| [CADGenBench](https://github.com/huggingface/cadgenbench) | 有效性、刚体对齐、表面 F1、体积 IoU、Betti 拓扑等评估门禁 | 是生成式 CAD 评测框架，不负责快速装配分组 |
| [Faiss](https://github.com/facebookresearch/faiss) | 大规模向量近邻检索与聚类 | 只解决向量索引，不定义 CAD 表征或精确判等 |

## 6. 论文路线

- [Accurate Instance-Level CAD Model Retrieval in Large-Scale Databases](https://arxiv.org/abs/2207.01339)：学习描述符召回候选，再用鲁棒点集匹配重排，支持“快速召回 + 高成本复核”的总体方向。
- [Learning Structure Correspondence Between CAD Models](https://www.sciencedirect.com/science/article/pii/S0031320323008233)：面向结构对应，可用于补强部件间局部匹配证据。
- [GC-CAD](https://arxiv.org/abs/2406.08863)：几何一致性的自监督 CAD 表征，说明图编码器可以保持无标签训练。
- [Self-supervised representation learning for CAD](https://arxiv.org/abs/2210.10807)：自监督 CAD 表征的另一条证据链。
- [CADGCL](https://doi.org/10.1007/s00371-025-03949-y)：面向 CAD 图对比学习，可作为困难样本驱动表示学习的参考。
- [SolidGen](https://www.research.autodesk.com/app/uploads/2024/02/SolidGen_Paper.pdf)：使用图与 Weisfeiler–Lehman 哈希处理重复/结构信息，支持确定性图摘要作为廉价门禁。

建议的升级顺序不是立即替换现有描述符，而是：先冻结可解释基线和误差集；再训练自监督 B-Rep 编码器用于候选召回；最后仍由独立的刚体/曲面/实体证据校准。只有在跨数据集候选召回、稳定性和总成本均改善时才晋级。

## 7. 重点专利族与工程区分

下表只做技术导航，不给出“不侵权”结论：

| 专利/申请 | 公开的核心链条 | 与当前路线需要重点区分之处 |
| --- | --- | --- |
| [CN117237659B](https://patents.google.com/patent/CN117237659B/zh) | STEP 面信息形成“词向量”，结合邻接矩阵进入图语义混合网络，得到模型向量后 K-means | 不复刻“曲面文本/语义预训练模型 + 指定图混合网络 + 整体向量 + K-means”的组合；保持确定性多通道基线，并对任何学习升级重新做权利要求映射 |
| [CN108595631B](https://patents.google.com/patent/CN108595631B/en) | 粗粒度谱/向量匹配后进行细粒度面编码匹配 | 两阶段粗精匹配概念接近；需逐项核对其特征、二分匹配和面编码限定，而不能只凭标题判断 |
| [US20240061980A1](https://patents.google.com/patent/US20240061980A1/en) / EP4325388B1 | 对 B-Rep 面、边、coedge 建模的拓扑感知深度 CAD 签名 | 自监督 B-Rep GNN 升级前需检查目标法域、家族状态和具体网络/签名权利要求 |
| [US20240370612A1](https://patents.google.com/patent/US20240370612A1/en) | Siamese GNN 和配合评分 | 当前几何等价聚类不同于配合预测；若引入孪生图网络或装配关系评分需重新分析 |
| [US9946732B2](https://patents.google.com/patent/US9946732) | 不变量/依赖描述符、面配对、变换和比较分类 | 刚体匹配及描述符组合可能落入其讨论范围，需针对独立权利要求做 claim chart |
| [US11288411B2](https://patents.google.com/patent/US11288411B2/en) | body signature、刚体对齐、精确/重叠/邻接匹配 | 与复核层较接近；应区分输入签名、匹配步骤、输出用途和法域 |
| [US8429174B2](https://patents.google.com/patent/US8429174B2/en) | 面向 3D 模型的领域化搜索与索引 | 大规模索引部署前需检查其有效权利要求与届满日期 |

工程上的降低风险策略：保留独立研发记录；记录每个特征和步骤的公开来源；避免照搬单一专利独立权利要求的完整组合；将候选表示、聚类策略与精确证据设计为可替换模块；在商业化前针对最终实现、销售地和服务器所在地完成正式 FTO。

## 8. OCCT 社区经验与已知陷阱

- [`TopoDS_Shape::IsSame/IsEqual` 的语义](https://dev.opencascade.org/content/two-read-same-topodsshape)：它们主要比较共享的底层 `TShape`、位置和方向，不能判断两个独立导入 STEP 实体的几何全等。
- [相似几何讨论](https://dev.opencascade.org/content/find-similar-geometry)：通用曲面相等不存在始终廉价可靠的单一判断，应使用分层证据。
- [OCCT Boolean operations](https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations)：布尔过程包含求交、分割和构建结果，状态和警告应进入报告。
- [容差修复讨论](https://dev.opencascade.org/content/fixing-tolerances-inside-shape)：容差会导致布尔失败；自动扩大或重写容差可能掩盖真实问题。

## 9. Git 协作约定

### 提交边界

按可独立审阅和回滚的语义组织提交：

1. 算法代码与对应测试；
2. 数据源或冻结基线结果；
3. 研究、专利和技术决策文档；
4. 大规模自动生成结果或外部语料清单。

不要把算法修改、数十万行生成 STEP 和研究结论塞入同一个提交。生成数据必须附带源文件哈希、运行配置、Git 版本、程序版本和回读验证清单。

### 每个误分类案例的最小记录

- 源模型哈希、部件 ID 和可审阅的导出 STEP；
- 快速层总距离及四通道分解；
- 候选阈值和聚类路径；
- 刚体变换、行列式、对应数量和最大/RMS 残差；
- Boolean 双向差体积、内核状态、容差和警告；
- 人工标签（相同/不同/不确定）、判断人和日期；
- 代码提交、配置哈希及产物路径。

人工视觉结论不能覆盖原始机器证据；二者应并列保存。出现冲突时建立“困难对”数据，先添加回归测试，再修改特征或判定规则。

### 合并门禁

- 单元与小型 OCCT 端到端测试通过；
- 冻结 motor 基线可复现，任何组数变化都有差异说明；
- 候选召回率、精确后纯度、无法判定率和耗时分别报告；
- 输出 STEP 全部回读，核对 Solid 数、体积误差和 B-Rep 合法性；
- 文档明确区分“实测事实”“工程决定”“待验证假设”和“法律状态快照”。

## 10. 后续建议

1. 为 38 件争议组和 75/76 建立带人工标签的最小回归夹具，保留 `indeterminate` 选项。
2. 把纯算法计时与 STEP 读取/标准化计时分离，分别报告候选特征、距离/聚类、rigid 和 Boolean 阶段。
3. 在更多装配上统计候选对压缩率、pair recall、final precision/recall 和每阶段耗时，而不只比较最终组数。
4. 自监督 GNN 先作为候选召回的旁路实验，采用固定 Boolean/人工混合基准评估，达到门禁后再替换生产候选向量。
5. 商业化前为目标实现制作逐项 claim chart，并通过 CNIPA、USPTO、EPO 等官方登记确认法律状态。
