# 示例数据与验收结果

## 目录

- `input/motor.STEP`：原始装配示例，SHA-256 为 `fc09d281fba7f3ab84265cf91e22022170db67e34eda8f2533f710426bc20ce3`。
- `motor_v4_results/grouped_steps/`：早期 v4 验收时冻结的 21 个 STEP 分组及回读验证清单，仅保留作历史对照。
- `motor_v4_results/report.json`：完整分组报告。
- `motor_v4_results/precision_report.json`：刚体对齐和双向布尔差证据。
- `motor_v4_results/data_quality.json`：数据质量检查结果。
- `motor_v4_results/workflow_manifest.json`：运行配置、阶段耗时、质量门禁和产物哈希。

数据集合计约 64.2 MB。标准化中间缓存和旧版本输出未收录。

## 复现

```powershell
python .\step_geometry_encoder.py .\data\input\motor.STEP --output .\reproduced_output
```

当前 v4.1 实现的预期结果：84 个 Solid，18 个候选组，20 个精确复核组，72 条精确关系，所有导出回读门禁通过。仓库内的 `motor_v4_results` 是旧算法生成的冻结产物，因此仍为 21 组；不要用它替代当前代码的复现验收。
