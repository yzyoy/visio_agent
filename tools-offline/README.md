# tools-offline

面向离线场景的命令行工具集，**不会**暴露给大模型，也未接入 Agent 的工具接口。

## 作用范围

这些脚本同时维护两类资源：

- **模板**（`.vsdx`）—— `--template-dir` 会写入 `template_library*.json`（若使用 `--stencils-only` 则会跳过模板扫描）。
- **形状库 / stencil**（`.vssx`）—— `--stencil-dir`；单独配合 `--stencils-only` 时，会更新 `stencil_library.json` 与 `stencil_library_lite.json`。

水印检测默认对 **上述两种** 扩展名生效（`.vsdx,.vssx`，可用 `--ext` 覆盖）。它们并非仅限 stencil 的工具。

`assets/templates/` 下的常见目录布局与「应放到哪」的说明：**[`../assets/README.md`](../assets/README.md)**。摘要：

| 路径 | 用途 |
|------|------|
| `assets/templates/library/` | `.vsdx` 模板 |
| `assets/templates/stencils/` | `.vssx` stencil 包 |

可将 `detect_watermarks --library` 指向单独子树（例如仅 `library/`）、仅 `stencils/`，或包含二者的上级目录——扫描器会递归遍历目录树。

生成的索引写入 `--out-dir`（一般为 `assets/indexes/`）：`template_library.json`、`template_library_lite.json`、`stencil_library.json`、`stencil_library_lite.json`。

## 包结构

- **`library_maintenance/`** — `detect_watermarks`、`prune_library`、`regenerate_indexes`。
- **`package_assets_release.py`** — 打 Release 用资产 zip，或**校验并解压**官方包到仓库根（见下一节）。

可通过 **脚本路径** 调用（下文示例），或在仓库根目录使用 **`python -m tools-offline.library_maintenance.<模块名>`** —— 当当前目录在 `sys.path` 中时，带连字符的文件夹名会作为包被正确解析。

## Release 资产 zip（`package_assets_release.py`）

脚本会打包 **`assets/templates/`** 与 **`assets/indexes/`**（条目在 zip 内为 **`assets/templates/...`、`assets/indexes/...`**，相对仓库根、无磁盘盘符前缀）。解压后实际落盘位置与目录树见 **[`../assets/README.md`](../assets/README.md)**。

解压时必须把内容展开到 **仓库根**（与 `apps/`、`assets/` 同级），这样在磁盘上看到 **`(<仓库根>/assets/templates/...)`**；若误解压到多一层文件夹，会变成 **`(<某文件夹>/assets/...)`**，需按 `assets/README.md` 合并到本仓库的 `assets/` 下。

```bash
# 在仓库根目录执行（--repo-root 默认即为当前仓库根）
python tools-offline/package_assets_release.py --extract path/to/visio-assets-release.zip

# 打包（默认输出 dist/visio-assets-release.zip）
python tools-offline/package_assets_release.py --out release/visio-assets-release.zip
```

`--extract` 会校验 zip 内路径均在 **`assets/`** 下、无 `..` 穿越，再放行写入。

## 推荐流程（水印审计 → 剔除 → 重建索引）

1. **检测** —— 写出清单；**不修改任何源文件。**
2. **人工复核** `refine/library_audit/watermarks.json`（或你指定的 `--out` 路径）。
3. **剔除** —— 将标记文件移至隔离区；务必先用 `--dry-run`。会写入 `removed.json` 便于追溯。
4. **重建索引** —— 剔除后运行，使磁盘上的文件与 JSON 索引一致。

更多说明（dry-run、恢复等）：见 [`refine/LIBRARY_PRUNING_PROCEDURE.md`](../refine/LIBRARY_PRUNING_PROCEDURE.md)。

## 命令

请在 **仓库根目录** 执行，以保证路径解析一致。

**水印扫描**（默认扩展名：`.vsdx,.vssx`；可用 `--ext` 覆盖）：

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json
```

若 stencil 不在本次扫描的同一棵目录树下，可再用 `--library assets/templates/stencils` 单独扫一遍。

**剔除**（会移动文件至隔离区，并非删除）：

```bash
python tools-offline/library_maintenance/prune_library.py \
    --manifest refine/library_audit/watermarks.json \
    --quarantine refine/library_audit/quarantine \
    --removed-out refine/library_audit/removed.json \
    --dry-run
```

复核无误后去掉 `--dry-run` 再执行。

**重建索引** —— 任选一种模式：

- **仅模板**（library 下的 `.vsdx`）—— 写入 `template_library.json` 与 `template_library_lite.json`；不写 stencil 时可省略 `--stencil-dir`：

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates/library \
    --out-dir assets/indexes
```

- **模板 + stencil** —— 额外写入 `stencil_library.json` 与 `stencil_library_lite.json`（先扫模板，再扫 stencil）：

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates/library \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

- **仅 stencil** —— 写入 `stencil_library.json` 与 `stencil_library_lite.json`；跳过模板扫描（无需 `--template-dir`）：

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --stencils-only \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

- **仅刷新新增的模板目录** —— 清除该目录前缀下已有索引项，仅重扫该子树，再合并写回 `template_library.json` 与 `template_library_lite.json`：

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates/library \
    --template-subdir "New Folder" \
    --out-dir assets/indexes
```

可重复传入 `--template-subdir`，在一次运行中刷新多个模板子目录。

- **仅刷新新增的 stencil 目录** —— 清除该目录前缀下已有索引项，仅重扫该子树，再合并写回 `stencil_library.json` 与 `stencil_library_lite.json`：

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --stencils-only \
    --stencil-dir assets/templates/stencils \
    --stencil-subdir "Vendor Packs" \
    --out-dir assets/indexes
```

可重复传入 `--stencil-subdir`，在一次运行中刷新多个 stencil 子目录。

会在输出索引旁写入 `regenerate_report.json`。
