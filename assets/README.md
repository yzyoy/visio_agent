# `assets/` 资源目录

只读资源放在**本目录**下，不要改到别的路径（`VISIO_TEMPLATE_DIR` 默认指向 `assets/templates`）。

## 应有的目录结构

解压官方 **`visio-assets-release.zip`** 到**仓库根目录**（与 `apps/` 同级）后，大文件会出现在此处：

| 路径 | 内容 |
| --- | --- |
| **`templates/library/`** | `.vsdx` 模板库 |
| **`templates/stencils/`** | `.vssx` 形状库 |
| **`indexes/`** | `template_library*.json`、`stencil_library*.json` 等索引 |

也就是在磁盘上应具备：

- **`<仓库根>/assets/templates/...`**
- **`<仓库根>/assets/indexes/...`**

若你只克隆了代码，`templates/` 可能为空或被 `.gitignore` 忽略；需从 Release 补齐或本地打包，见仓库根目录 [`README.md`](../README.md) 里的「恢复资产」。

## 解压方式（概要）

在仓库根执行（会把 zip 内的 `assets/...` 写到当前工程中对应位置）：

```bash
python tools-offline/package_assets_release.py --extract path/to/visio-assets-release.zip
```

**不要**解压到随意子目录再手动挪散文件；若图形界面解压多出一层 `…/某文件夹/assets/`，应把整个 **`assets` 目录**挪到与仓库根下现有的 `assets` **合并**（保持上述子路径名一致）。

---

## English

Read-only assets live **under this folder** (default `VISIO_TEMPLATE_DIR` is `assets/templates`).

After extracting **`visio-assets-release.zip`** into the **repository root** (alongside `apps/`), you should have:

| Path | Contents |
| --- | --- |
| **`templates/library/`** | `.vsdx` template library |
| **`templates/stencils/`** | `.vssx` stencils |
| **`indexes/`** | JSON indexes (`template_library*.json`, etc.) |

i.e. **`<repo>/assets/templates/...`** and **`<repo>/assets/indexes/...`**.

A plain clone may omit large `templates/`; restore from Releases or build the zip locally — see [`README.md`](../README.md) (Quick start — restore assets).

```bash
python tools-offline/package_assets_release.py --extract path/to/visio-assets-release.zip
```

Run from the repo root so files land under this `assets/` tree. If GUI unzip nested an extra folder, merge the resulting **`assets`** directory with the repo’s `assets/`.
