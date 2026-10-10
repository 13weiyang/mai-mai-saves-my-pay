# -*- coding: utf-8 -*-
"""把 demo_stores.json 内嵌进演示.html（file:// 下 fetch 会被 CORS 拦）。

⚠️ 2026-10-10 修一个**严重 bug**：
   老版本用 `end = html.find("\\n", start)` 切旧数据 —— 那只找到"这一行"的换行。
   但注入的数据是**多行**的 ⇒ `html[end:]` 把**旧数据整块留了下来** ⇒
   页面里同时存在两份数据 ⇒ `"1950751": {` 被当成标签语句 ⇒
   **SyntaxError: Unexpected token ':'** ⇒ **整页 JS 不执行（菜单都不出）**。
   当时表现为演示页"没有菜单"，查了半天才逮到。

   现在的做法：**括号配对**找到 `const DATA_ALL = {...}` 这条语句的真正结尾，
   整条替换；并把数据之后、`let CUR = null;` 之前的一切（旧残留）一并清掉。
   ⇒ 反复跑 `_inject.py` 也不会再叠数据。
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "演示.html")
DATA = os.path.join(BASE, "demo_stores.json")

# 紧跟 DATA_ALL 之后的固定代码，用来界定"残留区"的终点
MARK_AFTER = "let CUR = null;"


def find_object_end(html, from_pos):
    """从 from_pos 起的第一个 `{` 开始，找到与之配对的 `}`，返回其下标+1。

    会跳过字符串里的花括号（含转义），所以数据里有 `{`/`}` 也不会数错。
    """
    i = html.index("{", from_pos)
    depth = 0
    in_str = False
    esc = False
    j = i
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    raise SystemExit("✗ DATA_ALL 的花括号不配对 —— 文件可能已损坏")


with open(DATA, encoding="utf-8") as f:
    raw = f.read().strip()
json.loads(raw)          # 先校验是合法 JSON

with open(HTML, encoding="utf-8") as f:
    html = f.read()

start = html.find("const DATA_ALL = ")
if start == -1:
    raise SystemExit("✗ 找不到 const DATA_ALL 占位")

end = find_object_end(html, start)
if html[end:end + 1] == ";":
    end += 1

after = html.find(MARK_AFTER, end)
if after == -1:
    raise SystemExit("✗ 找不到 " + MARK_AFTER)

# 数据语句结束 → 到 MARK_AFTER 之间，正常只该是换行/空白；
# 若这里有东西，就是历史遗留的旧数据残块 —— 一并清掉。
leftover = html[end:after]
# ⚠️ 数据后面**必须补一个换行**再接后续代码 ——
#    否则会变成 `};let CUR = null;` 挤在一行，
#    回归脚本 `_check_demo.js` 里那句 `...\});\r?\n` 的提取正则就断了。
html = html[:start] + "const DATA_ALL = " + raw + ";\n" + html[after:]

with open(HTML, "w", encoding="utf-8") as f:
    f.write(html)

print("已注入 %d 字节数据" % len(raw))
if leftover.strip():
    print("⚠️ 顺手清掉了 DATA_ALL 之后的残留块：%d 字节（旧数据残骸）" % len(leftover))
