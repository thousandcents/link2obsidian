# 图片路径修复（vault-root 相对路径）

## 问题
link2obsidian 文章在 ingest 流程中从 `Clippings/` 根目录移动到 `raw/articles/`。图片真实位置始终在 `Thousand/Clippings/images/`（vault root 下）。文件相对路径只在文件当前所在目录有效，移动后即失效。

| 引用写法 | 从 `Clippings/foo.md` 解析到 | 从 `raw/articles/foo.md` 解析到 | 结论 |
|---|---|---|---|
| `images/bar.png` | `Thousand/Clippings/images/bar.png` ✅ | `Thousand/Clippings/raw/images/bar.png` ❌ | 文件相对，仅根目录有效 |
| `../images/bar.png` | `Thousand/images/bar.png` ❌ | `Thousand/Clippings/raw/images/bar.png` ❌ | 全错（旧版技能误示例） |
| `../../images/bar.png` | 越级，❌ | `Thousand/Clippings/images/bar.png` ✅（仅在此深度碰巧对） | 脆弱，深度一变即错 |
| `Clippings/images/bar.png` | `Thousand/Clippings/images/bar.png` ✅ | `Thousand/Clippings/images/bar.png` ✅ | **唯一全对** |

**结论**：任何位置都只用 vault-root 相对路径 `Clippings/images/xxx`。Obsidian 从 vault root（`Thousand/`）解析，与 `.md` 文件深度无关。

## 批量检测破损引用
```bash
cd /home/jack-lin-sparrow/Obsidian/Thousand/Clippings
# 文件相对路径引用（应为 0）
grep -rln '!\[.*\](../images/' raw/articles/ | wc -l
grep -rln '!\[.*\](images/'      raw/articles/ | wc -l
```

## 批量修复
```python
from pathlib import Path
base = Path("/home/jack-lin-sparrow/Obsidian/Thousand/Clippings/raw/articles")
for f in base.glob("*.md"):
    t = f.read_text(encoding="utf-8")
    if "../images/" in t or "](images/" in t:
        # 顺序关键：先替换长的 ../images/，再替换裸 ](images/
        t2 = t.replace("../images/", "Clippings/images/").replace("](images/", "](Clippings/images/")
        f.write_text(t2, encoding="utf-8")
        print("fixed", f.name)
```

> ⚠️ 顺序陷阱：必须先把 `../images/` 换成 `Clippings/images/`，否则 `../images/`.replace("images/", "Clippings/images/") 会变成 `..Clippings/images//` 造成二次污染。同理 `](images/` 不会误伤已正确的 `](Clippings/images/`（前者要求 `](` 紧贴 `images/`，后者是 `/` 紧贴 `images/`）。

## 验证
- 修复后用 Obsidian 打开文章，确认每张图都能渲染；
- 或在 `execute_code` 里用 `Path("Thousand/Clippings/images/<hash>.<ext>").exists()` 逐张确认文件存在（图片 hash 来自 URL，与 `.md` 引用一致）。

## 根因
旧版 SKILL.md 第 4 步「嵌入规则」曾示例 `![描述文字](../images/文件名.png)`，Agent 据此手动嵌入后用文件相对路径；postprocess.py 第 8 步只修 `images/`→`Clippings/images/`，不修 `../images/`。文件移入 `raw/articles/` 后路径全部失效。现 SKILL.md 已改为统一 `Clippings/images/`。
