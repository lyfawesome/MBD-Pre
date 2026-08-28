# STEP 几何无监督分组器

这是一个轻量、无训练的 Python 工程。它把 STEP 装配中的每个实体表示为可解释的几何—拓扑描述，并把相似实体自动放到同一组；每组由 Open CASCADE 单独写成一个 STEP 文件。

当前版本不再使用随机 128 维投影，也不使用当前文件内的 Z-score/MAD 缩放。相同零件跨文件运行时不会因为参照集合变化而改变表示。

## 环境

- Python 3.11 或更高版本；只使用标准库，不需要 `pip install`。
- Open CASCADE 的 `DRAWEXE`。程序会依次查找 PATH 和 `C:\msys64\ucrt64\bin\DRAWEXE.exe`，也可用 `--drawexe` 指定。

本机测试环境：Python 3.14.5、Open CASCADE 7.9.3。

## 运行

首次完整运行：

```powershell
python .\step_geometry_encoder.py "C:\Users\LENOVO\Desktop\motor.STEP" --output .\motor_v3_output
```

再次调整阈值时复用已经过 OCCT 标准化的零件：

```powershell
python .\step_geometry_encoder.py "C:\Users\LENOVO\Desktop\motor.STEP" --output .\motor_v3_output --reuse-cache --threshold 0.12
```

只分析、不导出分组 STEP：

```powershell
python .\step_geometry_encoder.py "C:\Users\LENOVO\Desktop\motor.STEP" --output .\analysis_only --skip-step-export
```

## 两种相似度模式

- `--mode strict`：默认。保留绝对尺寸，适合把同规格零件归为一组。
- `--mode family`：忽略整体均匀缩放，适合寻找同形状、不同规格的零件系列。

`--threshold` 是组内允许的最大组合距离，范围为 0～1。默认 `0.12`，即同组任意两个实体的最终相似度至少约为 `0.88`。阈值越小分组越严格。

严格模式还使用 `--size-tolerance 0.03` 硬门控：体积、表面积或总边长任一相对差超过 3%，零件不会进入同一组。该参数与线性尺寸误差不是一一对应关系，因为体积会随尺寸三次方变化。

## 算法

1. OCCT 精确读取 STEP/XDE，并按 `Solid` 拆分装配。
2. OCCT 计算体积、表面积、总边长、质心、主惯性矩、包围盒和拓扑数量。
3. 每个 Solid 由 OCCT 重新写成规范化 STEP，避免原文件中复杂实体表示造成漏读。
4. Python 构造以面为节点、共享边为连接的属性面邻接图 AAG。
5. 对 AAG 做 3 轮 Weisfeiler–Lehman 子结构重标记；严格模式保留绝对解析参数，系列模式使用尺度归一化参数。
6. 计算解析曲面/基础曲线分布、无量纲质量属性和由几何直径归一化的全顶点对软直方图。
7. 按拓扑、几何、整体形状和绝对尺寸四个通道计算可解释距离。
8. 使用确定性的凝聚 complete-link 聚类，防止 A≈B≈C 导致 A 与 C 被链式误合并。
9. 聚类后重新检查组内全部零件对、尺寸硬门控和索引覆盖。
10. OCCT 写出每组 STEP，并重新导入每个文件，核对实际 Solid 数量、总体积并执行 `checkshape`。

严格模式默认权重：拓扑 0.40、几何 0.25、形状 0.20、尺寸 0.15。系列模式的尺寸权重为 0。

## 输出

- `parts.csv`：零件编号、组号和精确几何属性。
- `similarities.csv`：所有零件对的总相似度，以及四个通道的距离分解。
- `report.json`：完整分组、组内最低/平均相似度、描述符与验证结果。
- `method.json`：算法通道、权重和“无训练/无随机投影”声明。
- `normalized_parts/`：OCCT 标准化后的单实体 STEP 缓存。
- `grouped_steps/`：每组一个 STEP 文件及 `manifest.json` 验证清单。

## motor.STEP 实测

在提供的 `motor.STEP` 上：

- OCCT 识别 84 个 Solid；
- 严格模式、阈值 0.12 得到 18 组；
- 原先被姿态错误拆开的第 2、3 组合并为一个 18 实体组；
- 18 个分组文件合计包含 84 个 Solid；
- 18 个输出文件的实际 Solid 数均与预期一致，并全部通过 OCCT B-Rep `checkshape`；
- 第二次独立运行的 `parts.csv`、`similarities.csv` 哈希一致，分组可复现。

测试命令：

```powershell
python -m unittest -v
```

## 限制

- 这是几何相似分组，不会无依据地推断“转子、端盖、轴承”等功能语义。
- 顶点点对距离是轻量的 D2-like 代理，不是表面均匀采样；球面、无拓扑顶点曲面和 B-spline 内部形变仍需由其他通道补充。
- 全顶点对计算使用流式直方图，内存为常数级，但时间复杂度仍是 O(V²)；超大单体需要增加与点顺序无关的确定性采样。
- 当前聚类后复核包括组内完整距离、尺寸门控、索引覆盖、导出回读数量、体积和 B-Rep 合法性；它还不是“刚体对齐后做布尔对称差”的严格几何等价证明。
- 当前采用标准库实现的确定性凝聚 complete-link，针对几十到几百个装配实体优化。
- 工程实现与开源许可均不能代替正式专利自由实施（FTO）法律意见。
