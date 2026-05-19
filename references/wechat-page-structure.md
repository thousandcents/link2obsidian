# WeChat Article Page Structure Reference (2026)

## Background

As of May 2026, WeChat public account articles have upgraded to a Vue.js dynamically-rendered page structure. The legacy HTML extraction method (`div#js_content`) no longer works for new pages.

## Two Page Structures

### Legacy (Traditional HTML)

- Title in `var msg_title = '...'` or `og:title`
- Content in `<div id="js_content" style="visibility: hidden;">...</div>`
- Images use `<img data-src="...">` tags
- Extracted via readability-lxml or regex

### New (Vue.js Dynamic Rendering)

- Page is ~1.9MB, mostly JavaScript
- Article data stored in `cgiDataNew` object inside `<script>` tags
- Title: `title: JsDecode('...')`
- Content: `content_noencode: JsDecode('...')` (plain text, not HTML)
- Author: `nick_name: JsDecode('...')`
- Time: `create_time: JsDecode('...')`
- Cover image: `cdn_url_1_1: JsDecode('...')` or `cdn_url: JsDecode('...')`
- Requires simulating WeChat's JsDecode function to decode escape sequences

## JsDecode Function

WeChat frontend uses `JsDecode` to decode escaped characters:

```javascript
function JsDecode(str) {
    return str
        .replace(/\\x5c/g, '\\')    // backslash
        .replace(/\\x0d/g, '\r')   // carriage return
        .replace(/\\x22/g, '"')    // double quote
        .replace(/\\x26/g, '&')    // ampersand
        .replace(/\\x27/g, "'")    // single quote
        .replace(/\\x3c/g, '<')    // less than
        .replace(/\\x3e/g, '>')    // greater than
        .replace(/\\x0a/g, '\n');  // newline
}
```

Python equivalent:

```python
def jsdecode(val):
    if not val:
        return val
    val = val.replace('\\x5c', '\\\\')
    val = val.replace('\\x0d', '\r')
    val = val.replace('\\x22', '"')
    val = val.replace('\\x26', '&')
    val = val.replace("\\x27", "'")
    val = val.replace('\\x3c', '<')
    val = val.replace('\\x3e', '>')
    val = val.replace('\\x0a', '\n')
    return val
```

## Detection

Check which page type:

```bash
# Check for legacy HTML content area
grep -c 'id="js_content"' page.html

# Check for new script data area
grep -c 'content_noencode' page.html
```

## Known Limitations

- New version content is plain text, no rich formatting or images
- If content includes images, they need to be fetched from `cdn_url` or `sub_articles` fields
- Multi-article messages need to check `sub_articles` array
