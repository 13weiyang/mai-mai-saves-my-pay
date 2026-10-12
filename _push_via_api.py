# -*- coding: utf-8 -*-
"""把项目文件推到 GitHub 仓库 —— 走 api.github.com。

⚠️ 为什么不用 git push（2026-10-10 实测，别重复踩）：
  · github.com / www.github.com  —— 本机直连超时；沙箱代理返 502 ⇒ **https 推不了**
  · ssh.github.com:443           —— 通了，但账号 token **缺 admin:public_key**，
                                   加不了公钥 ⇒ **ssh 也推不了**
  · api.github.com               —— **200 通**，且 token 的 `repo` 权限够
  ⇒ 唯一能用的路 = **GitHub API**（本脚本）。

做法（Git Data API，一次提交）：
  逐个 POST /git/blobs → POST /git/trees → POST /git/commits → 把 refs/heads/main 指过去

排除规则：照 .gitignore（_trash/、_tmp_*/、*.bak*、__pycache__/、token 等）

用法：
  python _push_via_api.py --dry-run        # 只列要传的文件
  python _push_via_api.py "提交说明"        # 真传
"""
import base64
import fnmatch
import json
import os
import subprocess
import sys
import urllib.request

GH = r"E:\workbuddy-space\tools\gh\gh.exe"
REPO = "13weiyang/mai-mai-saves-my-pay"
API = "https://api.github.com"
BRANCH = "main"

IGNORE_DIRS = {"_trash", ".git", "__pycache__", ".vscode", ".idea", ".pytest_cache",
               ".workbuddy"}   # ⚠️ 2026-10-11 补：Agent 记忆与日志，绝不进公开仓库
IGNORE_DIR_PREFIX = ("_tmp_",)
IGNORE_FILES = ["预览-*.png", "*.bak*", "*.pyc", "mcd-token.txt", ".env",
                "mcp-config.json", ".DS_Store", "Thumbs.db",
                "workbuddy.md"]   # ⚠️ 2026-10-12：内部开发全过程记录，不上公开仓库


def collect():
    out = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs
                   if d not in IGNORE_DIRS and not d.startswith(IGNORE_DIR_PREFIX)]
        for f in files:
            if any(fnmatch.fnmatch(f, p) for p in IGNORE_FILES):
                continue
            rel = os.path.relpath(os.path.join(root, f), ".").replace("\\", "/")
            if rel.startswith("./"):
                rel = rel[2:]
            out.append(rel)
    return sorted(out)


def api(method, path, payload, token):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "mai-mai-deploy")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def main():
    dry = "--dry-run" in sys.argv
    msg = next((a for a in sys.argv[1:] if not a.startswith("--")),
               "初始提交：麦门搭子 · 说一句，麦麦就到")

    files = collect()
    total = sum(os.path.getsize(f) for f in files)
    print("待传 %d 个文件，合计 %.2f MB" % (len(files), total / 1048576))
    for f in files:
        print("   %8.1f KB  %s" % (os.path.getsize(f) / 1024, f))
    if dry:
        print("\n（--dry-run，未上传）")
        return

    token = subprocess.check_output([GH, "auth", "token"], text=True).strip()
    if not token:
        raise SystemExit("拿不到 token（先跑 gh auth status 确认已登录）")

    # ⚠️ 空仓库（零提交）**不能**直接用 Git Data API —— 会 409 Conflict。
    #    先拿 Contents API 放一个文件，造出第一个 commit；之后 blobs/trees 才可用。
    print("\n=== ⓪ 确保仓库已有初始 commit ===")
    refpath = "/repos/%s/git/ref/heads/%s" % (REPO, BRANCH)
    try:
        parent = api("GET", refpath, None, token)["object"]["sha"]
        print("   已有分支，HEAD =", parent)
    except urllib.error.HTTPError as e:
        # ⚠️ 空仓库这里返回的是 **409**（不是 404）—— 实测过，别只接 404。
        if e.code not in (404, 409):
            raise
        r = api("PUT", "/repos/%s/contents/README.md" % REPO,
                {"message": "chore: 初始化仓库",
                 "content": base64.b64encode("初始化中…\n".encode("utf-8")).decode("ascii"),
                 "branch": BRANCH}, token)
        parent = r["commit"]["sha"]
        print("   空仓库 ⇒ 已造初始 commit:", parent)

    print("\n=== ① 上传 blobs ===")
    tree = []
    for i, rel in enumerate(files, 1):
        raw = open(rel, "rb").read()
        r = api("POST", "/repos/%s/git/blobs" % REPO,
                {"content": base64.b64encode(raw).decode("ascii"),
                 "encoding": "base64"}, token)
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": r["sha"]})
        print("   [%2d/%d] %s" % (i, len(files), rel))

    print("=== ② 建 tree ===")
    t = api("POST", "/repos/%s/git/trees" % REPO, {"tree": tree}, token)
    print("   tree =", t["sha"])

    print("=== ③ 建 commit ===")
    c = api("POST", "/repos/%s/git/commits" % REPO,
            {"message": msg, "tree": t["sha"], "parents": [parent]}, token)
    print("   commit =", c["sha"])

    print("=== ④ 指向 %s ===" % BRANCH)
    try:
        api("PATCH", "/repos/%s/git/refs/heads/%s" % (REPO, BRANCH),
            {"sha": c["sha"], "force": True}, token)
        print("   已更新已有分支")
    except Exception as e:
        api("POST", "/repos/%s/git/refs" % REPO,
            {"ref": "refs/heads/%s" % BRANCH, "sha": c["sha"]}, token)
        print("   已新建分支（首次）")

    print("\n完成：https://github.com/%s" % REPO)


if __name__ == "__main__":
    main()
