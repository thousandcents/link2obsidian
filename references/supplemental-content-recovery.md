# Supplemental Content Recovery from User Screenshots

## Session: 2026-07-20 — 创业初期如何分配股权

### Problem
WeChat scraper captured only the first ~200 chars of a 6200-word article. The article was a "wrapper" — 90% was a paid knowledge-planet (知识星球) promotion, but 10% contained actual methodology content in later sections. User provided 4 long screenshots of the full article.

### What Worked
1. **Vision OCR** — `vision_analyze` on each screenshot extracted the hidden text content
2. **Image triage** — Of 4 screenshots, 1 was a non-content (QR code + directory), 3 were content (methodology sections)
3. **Content stitching** — OCR text was appended to the article body in logical chapter order
4. **Typo batch fix** — Common OCR errors were fixed via `content.replace()` before writing

### Typo Patterns Observed
| OCR Output | Correct | Context |
|------------|---------|---------|
| 平局存活率 | 平均存活率 | statistics term |
| 独立独行 | 特立独行 | idiom |
| 卖家舍业 | 抛家舍业 | idiom |
| 分岐 | 分歧 | variant character |

### Image Naming Convention
Used descriptive names for supplemental images rather than hash-based names:
- `equity-screenshot-2.jpg` (section 02 content)
- `equity-screenshot-3.jpg` (section 03 content)
- `equity-summary.jpg` (section 04 summary)

This makes the images self-documenting in `Clippings/images/`.

### Key Insight
**Promotional wrapper detection**: When an article has a long table of contents but the scraper only returns 1-2 paragraphs, AND the article mentions "知识星球" / "付费社群" / "扫码阅读", it's likely a paywall wrapper. The actual content may exist only in user-provided screenshots or behind a paywall.

### Decision
Even after supplementing the full 6200-word content, the article was still classified as **marginal** because:
- Core methodology was brief (only ~500 words of actual content)
- Majority was still promotional (knowledge-planet CTAs)
- No unique framework, data, or actionable steps beyond generic advice

Thus: **stored in `raw/articles/` without wiki page**.

### frontmatter Update Pattern
```python
# After appending body content, recalculate sha256
content = open(f).read()
parts = content.split('---\n', 2)
frontmatter, body = parts[1], parts[2]
new_sha = hashlib.sha256(body.encode()).hexdigest()
updated_fm = re.sub(r'(sha256:\s*)[0-9a-f]+\n', r'\g<1>' + new_sha + '\n', frontmatter, count=1)
new_content = f'---\n{updated_fm}---\n{body}'
open(f, 'w').write(new_content)
```

### Checklist for Future Supplemental Recovery
- [ ] OCR all screenshots with `vision_analyze`
- [ ] Classify each image: content vs decorative (cover/QR/promo)
- [ ] Copy content images to `Clippings/images/` with descriptive names
- [ ] Batch-fix OCR typos using known pattern list
- [ ] Append cleaned text to article body in chapter order
- [ ] Recalculate and update `sha256` in frontmatter
- [ ] Verify no `../images/` or bare `images/` paths remain
- [ ] Run `postprocess.py` if format needs cleanup
- [ ] Update `index.md` and `log.md`
