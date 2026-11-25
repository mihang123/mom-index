"""
东方财富股吧采集器 — 反检测升级版
支持板块: 纳斯达克ETF, 黄金ETF, 通信ETF(CPO), 半导体ETF
"""
import re
import html as html_mod
import requests
import time
from datetime import datetime
from typing import List, Dict, Optional

from .anti_detection import get_anti_detection
from .proxy_config import get_proxies

SECTORS = {
    "nasdaq":     {"name": "纳斯达克", "code": "of159941", "etf": "513100"},
    "gold":       {"name": "黄金",     "code": "of518880", "etf": "518880"},
    "cpo":        {"name": "CPO通信",  "code": "of515880", "etf": "515880"},
    "semiconductor": {"name": "半导体", "code": "of512480", "etf": "512480"},
}

_ad = get_anti_detection()


def fetch_board(code: str) -> str:
    """获取股吧页面HTML — 使用反检测请求头"""
    url = f"https://guba.eastmoney.com/list,{code}.html"
    headers = _ad.get_common_headers(referer="https://guba.eastmoney.com")
    resp = requests.get(url, headers=headers, proxies=get_proxies(), timeout=15)
    resp.encoding = 'utf-8'
    return resp.text


def _strip_tags(s: str) -> str:
    return html_mod.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def parse_posts(html_content: str) -> List[Dict]:
    """解析帖子列表。

    页面结构说明：东方财富股吧早前用 <cite class="l1..l5"> 承载
    阅读数/回复数/标题/作者/时间，当前版本已改为
    <div class="articleh ..."> 容器内的 <span class="l1..l5">。

    关键点：页面中还存在"最后更新/作者"之类的表头 span，
    若按全页顺序分别抓取 l1..l5 再按下标拼装，会与标题列表错位。
    因此改为逐个帖子容器解析，容器内 span 顺序固定为 l1..l5，
    标题从容器内的 l3 链接直接取，保证一条帖子各字段严格对应。
    """
    posts = []

    # ---- 主路径：按帖子容器解析 ----
    blocks = re.findall(
        r'<div class="articleh[^"]*">(.*?)</div>',
        html_content,
        re.DOTALL
    )
    for block in blocks:
        m = re.search(
            r'<span[^>]*class="[^"]*\bl3\b[^"]*"[^>]*>(.*?)</span>',
            block,
            re.DOTALL
        )
        if not m:
            continue
        l3 = m.group(1)
        link = re.search(r'<a[^>]*href="(/news,[^"]*)"[^>]*title="([^"]*)"', l3, re.DOTALL)
        if not link:
            continue
        url, title = link.group(1), html_mod.unescape(link.group(2).strip())
        if not title or title == '点击开始搜索':
            continue

        def _grab(cls: str) -> str:
            mm = re.search(
                rf'<span[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</span>',
                block,
                re.DOTALL
            )
            return mm.group(1) if mm else ""

        author_html = _grab("l4")
        am = re.search(r'<font[^>]*>(.*?)</font>', author_html, re.DOTALL)
        author = _strip_tags(am.group(1)) if am else (_strip_tags(author_html) or "未知")

        posts.append({
            "id": f"guba_{url.split(',')[-1].replace('.html','')}",
            "title": title,
            "url": f"https://guba.eastmoney.com{url}",
            "platform": "guba",
            "author": author or "未知",
            "reads": _strip_tags(_grab("l1")) or "0",
            "replies": _strip_tags(_grab("l2")) or "0",
            "date": _strip_tags(_grab("l5")) or "未知",
            "collected_at": datetime.now().isoformat(),
        })

    if posts:
        return posts

    # ---- 兜底路径：旧版 <cite> 结构 ----
    title_pattern = re.compile(
        r'<a[^>]*href="(/news,[^"]*)"[^>]*title="([^"]*)"[^>]*>',
        re.DOTALL
    )
    read_pattern = re.compile(r'<cite[^>]*class="[^"]*l1[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)
    reply_pattern = re.compile(r'<cite[^>]*class="[^"]*l2[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)
    author_pattern = re.compile(r'<cite[^>]*class="[^"]*l4[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', re.DOTALL)
    date_pattern = re.compile(r'<cite[^>]*class="[^"]*l5[^"]*"[^>]*>(.*?)</cite>', re.DOTALL)

    titles = title_pattern.findall(html_content)
    reads = read_pattern.findall(html_content)
    replies = reply_pattern.findall(html_content)
    authors = author_pattern.findall(html_content)
    dates = date_pattern.findall(html_content)

    for i, (url, title) in enumerate(titles):
        title = html_mod.unescape(title.strip())
        if not title or title == '点击开始搜索':
            continue
        posts.append({
            "id": f"guba_{url.split(',')[-1].replace('.html','')}",
            "title": title,
            "url": f"https://guba.eastmoney.com{url}",
            "platform": "guba",
            "author": authors[i].strip() if i < len(authors) else "未知",
            "reads": reads[i].strip() if i < len(reads) else "0",
            "replies": replies[i].strip() if i < len(replies) else "0",
            "date": dates[i].strip() if i < len(dates) else "未知",
            "collected_at": datetime.now().isoformat(),
        })
    return posts


def collect_all() -> Dict[str, List[Dict]]:
    """采集所有板块 — 带人类延迟防触发风控"""
    result = {}
    for sector_key, cfg in SECTORS.items():
        try:
            html = fetch_board(cfg["code"])
            posts = parse_posts(html)
            result[sector_key] = posts
            print(f"  [{cfg['name']}] 采集到 {len(posts)} 条帖子")
            # 板块之间加延迟
            _ad.sleep_like_human("scroll")
        except Exception as e:
            print(f"  [{cfg['name']}] 采集失败: {e}")
            result[sector_key] = []
    return result


if __name__ == "__main__":
    data = collect_all()
    for k, v in data.items():
        print(f"{k}: {len(v)} posts")
