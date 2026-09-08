# C++迁移基线与验收契约

## 冻结的Python基线

- Git基线：`b812619`。
- Python测试：35项通过。
- fast默认参数：`strict`、阈值`0.12`、尺寸相对门限`0.03`、WL三轮、确定性complete-link。
- rigid默认参数：顶点容差`1e-5`；只允许旋转和平移组成的SE(3)变换；必须同时保持全部顶点、带曲线类型的边连接和带曲面类型的面边界。
- motor基线：84个Solid，18个fast候选组，rigid复核结果以对应Python rigid运行报告为准。
- 29装配体条件基线：rigid可判定7697/8359个Solid；fast pair precision 96.0603%，recall 100%，F1 97.9906%，ARI 97.9865%。

Python实现继续作为参考实现和算法快速迭代入口，不删除、不冻结开发。

## C++范围

`mbd_geometry_cpp`当前包含：

1. Python `similarity.py`等价的四通道fast距离、strict尺寸门控和family尺度不变模式；
2. Python `density_complete_link`等价的确定性complete-link；
3. 对OCCT标准化单Solid STEP的独立解析；
4. Python `precision.py`等价的顶点距离指纹、SE(3)恢复、镜像拒绝、带类型边和面边界校验；
5. 候选组内rigid拆分和全局rigid代表件分组；
6. 原生OCCT装配STEP读取、Solid拆分、精确质量属性和逐Solid标准化STEP写出；
7. 从原始装配STEP独立运行fast/rigid并输出C++报告；
8. 从Python `report.json`和`normalized_parts`复算描述符、fast与rigid分区的验收命令。

Boolean终审、分组STEP导出和完整工作流审计继续由Python实现负责；它们不属于本轮fast/rigid内核迁移范围。

## 一致性标准

- 离散结果：fast候选分区与rigid最终分区必须与Python完全相同，组号本身可不同。
- rigid关系：通过/拒绝必须逐对一致；镜像件必须拒绝。
- 浮点结果：fast最终距离通道绝对误差不超过`1e-12`；STEP顶点距离直方图的跨标准库误差不超过`1e-10`；rigid残差必须满足Python使用的同一顶点容差。
- 确定性：输入重排后，以稳定键对齐的分区不变。
- 回归入口：Python `python -m unittest -v`与C++ `ctest --test-dir build/cpp --output-on-failure`都必须通过。

## 构建与复算

```powershell
cmake -S . -B build/cpp-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp-ninja --config Release
ctest --test-dir build/cpp-ninja --output-on-failure

.\build\cpp-ninja\mbd_geometry_cli.exe parity-report `
  .\runs\motor_compare_rigid_c940dc3\report.json `
  .\runs\motor_compare_rigid_c940dc3\normalized_parts
```

`parity-report`退出码为0表示两个分区都一致；退出码2表示至少一个分区不同，并输出两套C++分组供定位。

原生motor验收结果：84个Solid、18个fast候选组、19个rigid组，两个分区均与Python rigid基线完全一致。C++与Python的体积、面积和惯性矩逐项一致，边长最大相对误差为`1.05e-14`。
