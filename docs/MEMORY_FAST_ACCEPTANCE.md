# 纯内存 fast 验收记录

验收日期：2026-09-08。参考为保留不变的 Python fast 实现；本次不调整算法阈值、
权重或候选组语义。rigid 仍是独立复核层，快速分类没有声称等于精确分类。

## 检查方法

1. Python 原有 35 项测试全部通过。
2. `cpp/fast` 独立构建和测试通过；新增拓扑描述符后仍无第三方依赖。
3. `cpp/occt_fast` 独立构建和测试通过，测试调用方编译选项为 `-std=gnu++17`。
   验证旋转平移、strict/family、输入顺序、整体多 Solid、空输入、异常配置、
   异常 BodyId、几何跳过诊断，以及调用前后目录列表不变。
4. 根项目 5 项 CTest 通过，包括原 C++ fast/rigid 与 Python 数值对照。
5. 9 类几何夹具：长方体、圆柱、截圆锥、尖圆锥、球、环面、NURBS 长方体、
   NURBS 圆柱、圆柱孔体。测试驱动把相同形状写成 STEP，分别交给原 C++ STEP
   解析器和未修改的 Python 描述符提取器，与直接内存描述符比较。
   STEP 读写只存在于测试/CLI；独立分类库不依赖数据交换模块。
6. `check_memory_report.py` 检查 motor 源文件 SHA-256 与已有 Python 报告相符，
   使用 Python 重算全部 84×84 距离矩阵。C++ 测试驱动一次导入原装配后，
   直接遍历内存实体并运行 `classify`，逐零件、逐距离、逐分区比较。

## motor.STEP 结果

基线报告：`runs/motor_compare_rigid_c940dc3/report.json`。
源文件 SHA-256：`fc09d281fba7f3ab84265cf91e22022170db67e34eda8f2533f710426bc20ce3`。

| 项目 | 结果 / 验收门槛 |
| --- | --- |
| 有效零件 | 84，跳过 0 |
| fast 分组 | 18 组，所有零件对的同组关系与 Python 完全一致 |
| 拓扑计数、曲面/曲线直方图、两套 WL、图统计 | 全部精确一致 |
| 顶点距离直方图最大绝对误差 | 约 2.47×10⁻¹¹；门槛 10⁻¹⁰ |
| 体积、面积、边长、惯性矩最大相对误差 | 约 1.05×10⁻¹⁴；门槛 10⁻¹⁰ |
| 全距离矩阵最大绝对误差 | 约 1.09×10⁻¹¹；门槛 10⁻¹⁰ |

分组验收比较每对零件是否同组，不依赖组号或显示顺序。数值不要求位级一致：
STEP 导出小数截断、顶点坐标量化和浮点累加会带来微小差异。
同一套输入特征的 C++/Python 距离运算仍使用原 `10⁻¹²` 门槛；
从 OCCT 内存几何到 Python STEP 特征的端到端验收采用 `10⁻¹⁰`。
阈值附近的新数据仍应执行同样的分区回归，现有样本不能证明所有 CAD 输入都等价。

兼容处理包括圆锥半角取绝对值、完整球面回走 seam 边界归为 vertex loop，
以匹配 OCCT 标准 STEP 输出的描述符语义。参考 OCCT 7.9.3 官方
[面转换实现](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/TopoDSToStep/TopoDSToStep_MakeStepFace.cxx)
和 [wire 转换实现](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/TopoDSToStep/TopoDSToStep_MakeStepWire.cxx)。

另外修正了旧 `parity-report` 的可审计性：参考报告不含距离矩阵时，
现在输出 `distance_matrix_checked=false` 和误差 `null`，不再用 `0` 冒充已核验。

接入方法见 [cpp/occt_fast/README.md](../cpp/occt_fast/README.md)。
