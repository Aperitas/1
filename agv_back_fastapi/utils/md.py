"""
极简 Markdown -> HTML 渲染器（只为在 /docs 里展示 docs/*.md 用）。

支持：标题(#~####)、围栏代码块、表格、有序/无序列表、引用、分隔线、
     行内 **粗体** / `代码` / [链接](url)。不引第三方依赖。
"""
import re
from html import escape

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """行内元素：先转义，再替换粗体/代码/链接"""
    text = escape(text, quote=False)
    text = _INLINE_CODE.sub(lambda m: "<code>%s</code>" % m.group(1), text)
    text = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group(1), text)
    text = _LINK.sub(lambda m: '<a href="%s" target="_blank">%s</a>' % (m.group(2), m.group(1)), text)
    return text


def _split_row(line: str):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _is_sep(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    body = set(s.replace(" ", ""))
    return body.issubset(set("|:-")) and "-" in body


def render_markdown(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 围栏代码块
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append('<pre class="code"><code>%s</code></pre>' % escape("\n".join(buf)))
            continue

        # 表格
        if stripped.startswith("|") and i + 1 < n and _is_sep(lines[i + 1]):
            header = _split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            html = ['<table><thead><tr>']
            html += ["<th>%s</th>" % _inline(c) for c in header]
            html.append("</tr></thead><tbody>")
            for row in rows:
                html.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in row) + "</tr>")
            html.append("</tbody></table>")
            out.append("".join(html))
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            i += 1
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            out.append("<hr/>")
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % "<br/>".join(_inline(b) for b in buf))
            continue

        # 列表（无序 / 有序）
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                cur = lines[i].strip()
                mm = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", cur)
                if not mm:
                    break
                items.append("<li>%s</li>" % _inline(mm.group(1)))
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
            continue

        # 空行
        if not stripped:
            i += 1
            continue

        # 段落
        buf = []
        while i < n and lines[i].strip() and not lines[i].strip().startswith(("```", "|", "#", ">")):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % _inline(" ".join(buf)))

    return "\n".join(out)


PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>%(title)s</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'PingFang SC','Microsoft YaHei',sans-serif;
      max-width:1000px;margin:0 auto;padding:28px 20px 80px;line-height:1.65;color:#1f2328;}
 h1{border-bottom:1px solid #d0d7de;padding-bottom:.3em;}
 h2{border-bottom:1px solid #eaeef2;padding-bottom:.25em;margin-top:2em;}
 table{border-collapse:collapse;width:100%%;margin:1em 0;font-size:14px;}
 th,td{border:1px solid #d0d7de;padding:6px 10px;text-align:left;vertical-align:top;}
 th{background:#f6f8fa;}
 pre.code{background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;padding:12px;overflow:auto;font-size:13px;}
 code{background:#f6f8fa;border-radius:4px;padding:1px 5px;font-size:90%%;}
 pre.code code{background:none;padding:0;}
 blockquote{border-left:4px solid #d0d7de;margin:0;padding:.2em 1em;color:#57606a;background:#f6f8fa;}
 .top{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:#57606a;margin-bottom:8px;}
 a{color:#0969da;text-decoration:none;} a:hover{text-decoration:underline;}
</style></head><body>
<div class="top"><span>%(updated)s</span><span><a href="/docs">&larr; 返回接口文档</a></span></div>
%(body)s
</body></html>"""