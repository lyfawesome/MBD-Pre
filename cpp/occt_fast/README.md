# 纯内存 OCCT 快速分类

`mbd::occt_fast::classify` 直接接收宿主持有的 `TopoDS_Shape` 和稳定 BodyId，
在内存中提取特征并返回快速分组。调用期间没有文件读写、STEP 序列化、子进程、
Python、JSON、UI 或 rigid 依赖。Python 参考实现和原有文件工作流继续保留。

## 源码集成

将 `cpp/fast` 和 `cpp/occt_fast` 两个目录作为相邻目录一起复制或通过 Git 引入。
不要只复制头文件，也不需要修改算法源码。

```cmake
# 宿主先提供匹配自身 OCCT 的 OpenCASCADE_DIR / CMAKE_PREFIX_PATH。
add_subdirectory(third_party/mbd-pre/cpp/occt_fast)
target_link_libraries(your_application PRIVATE mbd::occt_fast)
```

```cpp
#include <mbd_occt_fast/classifier.hpp>

std::vector<mbd::occt_fast::Body> bodies{
    {"Body-101", firstShape},
    {"Body-102", secondShape},
};
auto result = mbd::occt_fast::classify(bodies);
for (const auto& group : result.groups) {
    // group 是一组稳定 BodyId，可映射回宿主对象。
}
for (const auto& diagnostic : result.skipped) {
    // 向宿主报告 diagnostic.body_id 和 diagnostic.message。
}
```

主接口兼容 C++17；库内部用 C++20 编译，因此工具链须支持 C++20。
链接的是宿主的 OCCT 基础、几何和建模库，不链接 STEP 数据交换库。
宿主与静态库需使用兼容的编译器、运行库和同一套 OCCT 头文件/二进制。
本仓库验证环境为 OCCT 7.9.3、MinGW GCC 16.1；其他 OCCT 版本需重跑验收。

## 输入和结果约定

- 一个 BodyId 对应一个逻辑零件。Solid、由多个 Solid 组成的 Compound/CompSolid
  都以整体处理，保留每个实例的位置，不拆成多个分类对象。
- 输入必须是实体或实体装配；空形状、没有实体、混入游离面/边、无法完整遍历的
  wire 或不支持的几何类型会进入 `skipped`，不会默认为有效分类对象。
- BodyId 必须非空且唯一；重复/空 ID、无效配置抛出 `std::invalid_argument`。
  几何检查不是完整的 B-Rep 合法性认证，宿主应提供合法实体。
- Shape 是共享的只读快照，调用期间宿主不能修改底层拓扑。所有坐标、半径和
  质量属性必须使用同一单位；与现有 Python STEP 基线对照时使用毫米。
- 默认 `strict`、距离阈值 `0.12`、尺寸容差 `0.03`、WL 深度 `3`；
  `Mode::family` 支持整体均匀缩放的系列件分组。
- `groups` 包括单件组。`body_ids` 按 ID 字符串排序，`assignments`（从 1 起）和
  `distances` 与此顺序对齐。相同 ID/几何不受输入列表排列影响。
- 单个几何失败不取消其他零件；全部被跳过时返回空分组和诊断。
  系统级错误（例如内存耗尽）会向调用方传播。
- 输出是原 fast 算法的候选组，不包含 rigid/Boolean 精确复核。

宿主负责 BodyId 映射、ground 过滤、单件组隐藏、线程调度、revision 检查和 UI。
函数是同步的，没有共享的算法缓存或全局设置；异步调用应在宿主工作线程执行，
返回时核对快照版本再应用结果。它没有中途取消接口。

## 特征复用与依赖边界

```text
只读 TopoDS_Shape + BodyId
          |
          v
mbd_occt_fast：OCCT 内存拓扑遍历 + 质量属性
          |
          v
mbd_fast：PartTopology -> GraphDescriptor -> 四通道距离 -> complete-link
          |
          v
BodyId 分组 + 距离矩阵 + 跳过诊断
```

`mbd_fast/topology.hpp` 提供无 CAD 内核依赖的 `PartTopology` 和
`describe_topology`。原 STEP 解析器也使用这一描述符实现，避免两套 C++ 算法分叉。
OCCT 适配器遍历曲面、曲线、面边邻接和顶点，不通过 STEP 文本绕行。

需要按 revision 缓存特征的 C++20 调用方，可包含
`<mbd_occt_fast/features.hpp>` 调用 `describe(shape)`，并额外链接 `mbd::fast`，
为返回的 `PartFeatures.source_file` 设置稳定 ID 后调用 `mbd::fast::group`。
该字段仅用作确定性排序键，不触发文件访问。缓存键还应包括单位和 WL 深度。

距离矩阵需要 O(n²) 内存；顶点距离直方图遍历每个零件的顶点对。
这是去掉磁盘转换的版本，未改变原快速算法的距离定义、权重和分组策略。

## 构建与验收

```powershell
# 独立构建，不配置根项目，不需要 Python 或 JSON。
cmake -S cpp/occt_fast -B build/occt-fast-standalone -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/occt-fast-standalone
ctest --test-dir build/occt-fast-standalone --output-on-failure

# Python、原 C++、内存版描述符和距离的对照测试。
./scripts/validate_cpp.ps1
python -m unittest -v

# motor 全文件验收。只有测试驱动读 STEP，分类函数仅接收内存 Shape。
python scripts/check_memory_report.py build/cpp-ninja/mbd_memory_parity.exe `
  data/input/motor.STEP runs/motor_compare_rigid_c940dc3/report.json
```

验收边界、数值容差和结果见 [内存版验收记录](../../docs/MEMORY_FAST_ACCEPTANCE.md)。
