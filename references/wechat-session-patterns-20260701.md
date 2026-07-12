# WeChat Article Patterns Discovered 2026-07-01

These patterns were found during processing of two articles and should be integrated into the main SKILL.md markdown cleanup section when next updated.

## 1. Code Block Closing Text Attachment

Code block close (```) is followed immediately by body text without a blank line:
```
```python
print("hello")
```通过所有关卡的策略，并不能保证实盘一定盈利。
```
Fix: Replace the pattern with:
```
```python
print("hello")
```

通过所有关卡的策略，并不能保证实盘一定盈利。
```

## 2. Debug Text Contamination (Self-Inflicted)

When applying multiple rounds of content.replace() in Python, a debug/guard clause can accidentally inject debug text into the actual file content:

```python
if '最小差距' in content:
    context = content[idx:idx+80]
    # If the variable 'content' isn't properly updated before the guard check,
    # the debug print can be confused with the actual replacement logic
```

Fix: Always verify final file content doesn't contain debug print text:
```python
has_debug = '这段上面已经检查过' in content
```

## 3. `### 第 N 层：` Heading Merge

Quant/finance articles use numbered sub-headings:
```
### 第 1 层：蒙特卡洛模拟（Monte Carlo Simulation）把你的交易序列重采样上千次...
```
Fix: Insert `\n\n` after the first Chinese sentence/colon boundary to separate heading text from body.

## 4. Case Study Bullet with Misplaced Bold

```
- 原始回测：** 4 年期间夏普高达 2.1，看上去非常惊艳。
- 首次走查：** IS/OOS 效率比仅 0.38**
```
Fix: Move `**` before the colon to wrap the name portion:
```
- **原始回测：** 4 年期间夏普高达 2.1，看上去非常惊艳。
- **首次走查：** IS/OOS 效率比仅 0.38**
```

## 5. List Items Without Blank Lines

Multiple consecutive `- ` list items without `\n\n` between them cause the paragraph-level `**` balance check to fail (entire list treated as one paragraph). Fix: ensure each list item is separated by a blank line.
