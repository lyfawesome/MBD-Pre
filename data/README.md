# 示例数据与验收结果

## 当前基线

- `input/motor.STEP`：原始装配示例，SHA-256 为 `fc09d281fba7f3ab84265cf91e22022170db67e34eda8f2533f710426bc20ce3`。
- `motor_v4_results/`：使用 Git 提交 `c940dc3c00f3f924202a39e0cbb9eaaa5d7d82f8` 和几何内核 v4.1.0，从空缓存冷启动计算的当前基线。
- `motor_v4_results/grouped_steps/`：21 个分组 STEP 文件及导出回读清单。
- `motor_v4_results/parts.csv`：84 个部件的特征、候选组和最终组。
- `motor_v4_results/similarities.csv`：部件间相似度矩阵。
- `motor_v4_results/report.json`：主运行报告。
- `motor_v4_results/precision_report.json`：精确复核结果。
- `motor_v4_results/precision_checkpoint.json`：与源文件、参数和算法修订绑定的精确复核检查点。
- `motor_v4_results/data_quality.json`：数据质量校验结果。
- `motor_v4_results/workflow_manifest.json`、`workflow_events.jsonl`：工作流产物清单和事件日志。

当前结果为：84 个 Solid、18 个候选组、74 条精确复核关系、21 个最终组。21 个导出文件全部可回读，共回读 84 个 Solid，最大相对体积误差为 `3.65198169360252E-08`，六项质量门全部通过。

该结果经过两次独立冷启动复算，最终分区和关系判定完全一致；`parts.csv` 与 `similarities.csv` 的 SHA-256 也分别一致。完整复现信息见 `motor_v4_results/BASELINE.md`。

## 历史数据

`archive/motor_v4_legacy_21_groups/` 保存更新前的 v4.0.0 历史结果：84 个 Solid、18 个候选组、71 条精确复核关系、21 个最终组。归档的 30 个原始文件与更新前内容逐文件 SHA-256 一致。

新旧结果虽然都为 21 组，但成员分区不同，因此不能只比较组数。历史目录仅用于回归比较，不代表当前算法基线。

## 复现

```powershell
python .\step_geometry_encoder.py .\data\input\motor.STEP --output .\runs\motor_baseline --precision-mode boolean --precision-workers 4
```

复核时应比较每组的成员集合、精确关系判定、导出回读结果和质量门，不应只比较最终组数。
