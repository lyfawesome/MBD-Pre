# 快速算法独立库架构

## 目标

快速分组内核作为独立 C++20 库 `mbd_fast` 发布。外部软件只需要构造
`mbd::fast::PartFeatures` 并调用 `mbd::fast::group`，不需要修改算法源码，
也不需要依赖 OpenCASCADE、STEP 解析、rigid、JSON 或 Python。

## 依赖边界

```text
外部软件 / 当前 CLI
        |
        | PartFeatures
        v
mbd_fast（纯 C++20）
  - 四通道距离
  - strict / family 模式
  - 确定性 complete-link
        |
        | GroupingResult
        v
分组编号 + 距离矩阵

OCCT STEP 解析 ----> PartFeatures
rigid 精确验证 <---- 快速候选分组
```

`mbd_fast` 不知道特征来自 STEP、数据库还是其他 CAD 内核。STEP 特征提取和
rigid 复核位于几何适配层，不能反向成为快速算法的依赖。

## 稳定接口

- 头文件：`<mbd_fast/fast.hpp>`
- CMake 目标：`mbd::fast`
- 主入口：`mbd::fast::group(parts, config)`
- 输入契约：`PartFeatures`
- 输出契约：`GroupingResult`
- 配置：`Config`，默认值与 Python 基线一致

确定性键由 `source_file`、`label`、`index` 依次选择。调用方应为每个零件
提供稳定且唯一的 `label`，不要使用临时内存地址。

## 集成方式

源码集成：

```cmake
add_subdirectory(path/to/cpp/fast)
target_link_libraries(your_target PRIVATE mbd::fast)
```

安装包集成：

```cmake
find_package(mbd_fast CONFIG REQUIRED)
target_link_libraries(your_target PRIVATE mbd::fast)
```

Windows 使用 MinGW 时，建议把安装前缀放在纯 ASCII 路径。MinGW 链接器处理
导入库的绝对中文路径时可能发生编码损坏；源码内 `add_subdirectory` 已在当前
中文项目路径验证通过。

## 兼容策略

独立接口从 1.0.0 起按语义版本管理。`PartFeatures` 字段、默认配置、距离权重、
分组确定性或结果含义发生不兼容变化时提升主版本。当前项目原有的
`<mbd/fast.hpp>` 保留为兼容转发层，现有 CLI、rigid 流程和测试无需修改。
