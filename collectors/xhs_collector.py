"""
小红书数据采集器（rnote.dev API）
需要配置 RNODE_API_KEY 环境变量或直接填入
"""
import os
import requests
from datetime import datetime
from typing import List, Dict, Optional
import time

from .proxy_config import get_proxies

# 配置: 在 https://rnote.dev/auth/register 注册后获取
# 设置环境变量 RNODE_API_KEY 或直接填入
API_KEY = os.environ.get("RNODE_API_KEY", "")
API_BASE = "https://rnote.dev/api/v2"

SEARCH_KEYWORDS = {
    # 用小白的语言去搜，才能找到小白
    "nasdaq":     ["美股怎么买", "纳斯达克新手", "纳指还能买吗", "买美股"],
    "gold":       ["黄金怎么买", "买黄金亏了", "黄金新手", "黄金还能涨吗"],
    "cpo":        ["CPO是什么", "光模块还能涨吗", "通信ETF"],
    "semiconductor": ["芯片还能买吗", "半导体新手", "芯片ETF"],
}

# 排序方式：general 综合 / time_descending 最新 / popularity_descending 最多点赞
SORT_TYPE = "general"


class _Budget:
    """请求预算控制 —— 按次计费接口必须防止翻页逻辑意外超支。"""

    def __init__(self, used: int = 0, limit: int = 20):
        self.used = used
        self.limit = limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def allow(self) -> bool:
        return self.remaining > 0


def search_notes(keyword: str, count: int = 20, sort_type: str = SORT_TYPE,
                 budget: Optional["_Budget"] = None) -> List[Dict]:
    """搜索小红书笔记。

    参数说明（对照 rnote.dev 线上 OpenAPI 核实）：
      - keyword  必填，搜索词
      - page     页码，从 1 开始（不是 count，上游旧代码用的是 count，会被服务端静默忽略）
      - sort_type 排序，取值 general / time_descending / popularity_descending /
                   comment_descending / collect_descending
      - note_type / time_filter 为中文枚举，如 "视频笔记" / "一周内"

    翻页时必须把首次响应中的 search_id 与 search_session_id 原样带回，
    否则会重复取到第一页。

    budget: 可选的请求预算，传入后翻页会受其上限约束。
    """
    if not API_KEY:
        print(f"  ⚠️ 未配置 RNODE_API_KEY，跳过小红书搜索: {keyword}")
        return []

    notes: List[Dict] = []
    page = 1
    search_id = ""
    search_session_id = ""

    while len(notes) < count and page <= 5:
        if budget is not None and not budget.allow():
            print(f"  ⚠️ 达到请求预算上限，停止翻页")
            break

        params = {
            "keyword": keyword,
            "page": page,
            "sort_type": sort_type,
        }
        if search_id:
            params["search_id"] = search_id
        if search_session_id:
            params["search_session_id"] = search_session_id

        try:
            resp = requests.get(
                f"{API_BASE}/crawler/search/notes",
                params=params,
                headers={"X-API-Key": API_KEY, "User-Agent": "mom-index/1.0"},
                proxies=get_proxies(),
                timeout=20,
            )
        except Exception as e:
            print(f"  XHS 请求失败: {e}")
            break

        if budget is not None:
            budget.used += 1

        if resp.status_code != 200:
            print(f"  XHS API错误: {resp.status_code} {resp.text[:150]}")
            break

        body = resp.json()
        # 统一响应结构: {"success": bool, "data": {...}, "error": str|null}
        if not body.get("success"):
            print(f"  XHS 业务失败: {body.get('error')}")
            break

        data = body.get("data") or {}
        # 搜索结果路径: data.data.items
        inner = data.get("data") or {}
        items = inner.get("items") or []
        # 翻页三件套：仅首次搜索返回
        search_id = data.get("search_id") or search_id
        search_session_id = data.get("search_session_id") or search_session_id

        for item in items:
            note = item.get("note") or item.get("note_card") or item
            if note and isinstance(note, dict):
                parsed = _parse_note(note)
                if parsed:
                    notes.append(parsed)

        if not items:
            break
        page += 1
        if not search_id and not search_session_id:
            # 拿不到翻页凭据，继续翻会重复第一页
            break

    return notes[:count]

def get_note_detail(note_id: str) -> Optional[Dict]:
    """获取笔记详情（含评论）"""
    if not API_KEY:
        return None
    try:
        resp = requests.get(
            f"{API_BASE}/crawler/note/image",
            params={"note_id": note_id},
            headers={"X-API-Key": API_KEY},
            proxies=get_proxies(),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def _parse_note(raw: Dict) -> Optional[Dict]:
    """标准化笔记格式 — 适配 rnote.dev API 返回结构。

    搜索结果里可能混有非笔记卡片（推荐模块、话题模块等），
    这里统一做一次有效性校验，没有标题的条目直接丢弃。
    """
    user = raw.get("user") or raw.get("author") or {}
    interact = raw.get("interact_info") or raw.get("note_interact_info") or {}
    tags = raw.get("tag_list") or raw.get("tags") or []

    # 搜索卡片里标题可能在 display_title，详情接口里在 title/desc
    title = (raw.get("display_title") or raw.get("title")
             or raw.get("desc") or "").strip()

    note_id = raw.get("id") or raw.get("note_id") or raw.get("noteId") or ""
    if not title or not note_id:
        return None

    if not isinstance(user, dict):
        user = {}

    return {
        "id": note_id,
        "title": title[:100],
        "content": raw.get("desc") or raw.get("content") or "",
        "platform": "xiaohongshu",
        "author": user.get("nickname") or user.get("nick_name") or "未知",
        "author_followers": user.get("follower_count", 0),
        "likes": interact.get("liked_count", 0),
        "comments_count": interact.get("comment_count", 0),
        "collected_at": datetime.now().isoformat(),
        "tags": [t.get("name", t) if isinstance(t, dict) else t for t in tags],
    }

def _gen_sample_posts() -> Dict[str, List[Dict]]:
    """生成模拟小红书帖子 — 当真实 API 不可用时的 fallback。
    语言风格模仿真实 小白/宝妈，涵盖追涨/恐慌/跟风/求助四种典型模式。
    当前市场背景: 科技牛市(CPO+半导体涨) + 黄金阴跌 + 纳指高位震荡。"""
    now = datetime.now().isoformat()
    samples = {
        # Gold: 恐慌割肉为主 — 黄金从高位跌了20%，小白大量恐慌卖出
        "gold": [
            {"title": "黄金亏了20%了要不要割肉啊😭", "content": "小白一个，当初听博主说黄金保值才买的，结果一路跌到现在亏了两成，心态真的崩了。各位大佬帮看看还能留吗？"},
            {"title": "宝妈求救！黄金还能涨回来吗？", "content": "全职带娃没时间看盘，今天一看账户绿了一片，黄金不是避险的吗为什么跌这么惨？有懂的姐妹吗？"},
            {"title": "黄金到底还能不能买啊", "content": "新手求问，现在黄金跌了好多，是不是可以抄底了？还是说还会继续跌？好纠结啊"},
            {"title": "救命！！黄金大跌我要不要跑", "content": "亏了一万多块了，老公还不知道，再跌下去奶粉钱都要没了，好慌好慌好慌"},
            {"title": "黄金怎么买啊，纯小白求教", "content": "从来没买过投资产品，听同事说黄金不错，但完全不知道在哪买、买哪个，有大佬愿意教一下吗"},
            {"title": "割了割了不玩了", "content": "受不了了，每天打开账户都在亏，今天割肉清仓了，亏了八千认了。以后再也不碰投资了"},
            {"title": "听朋友说黄金会涨到500，能信吗", "content": "朋友说现在黄金是底部，后面会大涨，有点心动但又怕继续亏，有没有懂行的分析一下？"},
            {"title": "亏麻了，黄金什么时候能回本", "content": "三月份买在高点，现在跌了快两成了，每天看着账户都想哭，有没有跟我一样的姐妹"},
            {"title": "黄金还能留吗姐妹们", "content": "刚开始定投黄金就赶上大跌，买啥啥跌，是不是我不适合投资啊。要不要止损？求过来人给个建议😭"},
            {"title": "黄金这是怎么了天天跌", "content": "小白不懂就问，黄金不是最稳的吗？为什么最近天天跌，是不是要打仗了？好害怕"},
            {"title": "新手想抄底黄金可以吗", "content": "看到黄金跌了这么多，感觉机会来了，但第一次买不太会操作，有没有大佬教一下在哪买手续费低？"},
            {"title": "昨天刚割今天就涨了我要气死了", "content": "扛了两个月天天亏，昨天终于忍不住割了，结果今天一看涨了两个点？？？心态彻底崩了，再也不玩了"},
            {"title": "当初谁说黄金保值的给我出来", "content": "入坑三个月亏了15%，谁跟我说黄金是最稳的投资？比股票亏得还多！到底还要不要坚持"},
            {"title": "请问现在黄金值得定投吗", "content": "想开始定投黄金ETF，但是看最近一直在跌，不知道该不该开始。求懂的大佬给点建议"},
            {"title": "亏了两万块，老公说再亏就离婚", "content": "偷偷拿家庭存款买了黄金基金，结果一直跌。老公发现了说再亏下去就离婚。姐妹们我该怎么办"},
            {"title": "黄金ETF和纸黄金买哪个好啊", "content": "完全搞不懂这些产品有什么区别，有没有人能简单告诉我哪个更适合小白长期持有的？"},
        ],
        # CPO: FOMO追涨为主 — 科技牛+AI算力概念，小白疯狂追涨
        "cpo": [
            {"title": "CPO还能买吗？小白求教", "content": "最近总刷到光模块CPO的帖子，所有人都在说会涨，但我不懂这个到底是什么。大佬们觉得现在还能上车吗？"},
            {"title": "满仓干就完了！冲冲冲！", "content": "科技牛来了兄弟们，CPO方向稳稳的，今天全部满仓杀进去，不冲不是中国人！"},
            {"title": "问了几个博主都说CPO要起飞", "content": "关注的好几个投资博主都在推CPO，说是AI算力核心，要不要跟一把？还是再等等回调？"},
            {"title": "CPO通信ETF是什么啊", "content": "看很多人讨论通信ETF，跟CPO是什么关系啊？纯小白不太懂这些专业名词，有人能解释一下吗"},
            {"title": "涨了涨了CPO起飞！！", "content": "果然没让我失望，上周听朋友推荐买了点通信ETF今天就大涨了，好后悔买少了！还能加仓吗？"},
            {"title": "CPO已经涨太多了还能追吗", "content": "看着它天天涨就是不敢买，今天又涨了三个点，再不买是不是就永远上不了车了？"},
            {"title": "通信ETF是一键买入CPO吗", "content": "小白想买CPO方向，有人跟我说直接买通信ETF就行，是这样吗？还能不能再加？"},
            {"title": "今天CPO又大涨我还没上车", "content": "每次都想着等回调，结果越等越涨。今天又涨了快五个点，真的要哭了。现在追还来得及吗？"},
            {"title": "梭哈了通信ETF，家人们祝我好运", "content": "听了博主分析果断满仓通信ETF，AI时代CPO是核心，这波我信了！有没有一起的"},
            {"title": "CPO涨了这么多还能买吗纯小白", "content": "从来没买过股票，看到大家都在讨论CPO，手里有点闲钱想试试，但完全不知道从哪下手"},
            {"title": "后悔上周没买CPO少赚好多", "content": "上周就想买的一直犹豫，结果这周直接涨了十几个点，心态崩了。现在买是不是追高了？"},
            {"title": "跟朋友买的CPO今天赚了两千块", "content": "朋友推荐的通信ETF真的起飞了，后悔买少了。要不要再加点仓位？感觉AI行情才刚刚开始"},
        ],
        # Nasdaq: 温和追涨 — 纳指高位，小白犹豫但仍在买入
        "nasdaq": [
            {"title": "美股还能不能买啊，感觉涨好多了", "content": "纳指今年涨了好多，小白不太懂美股，现在还能买吗？还是等回调？求大神指点"},
            {"title": "第一次买美股ETF，需要注意什么", "content": "刚开好账户准备定投纳指，完全不懂规则，有没有买过的大佬讲讲？手续费高吗？"},
            {"title": "纳指还能上车吗，纠结了好几天了", "content": "一直想买但每天都觉得太高了不敢下手，结果越等越涨，感觉自己错过了好多。今天要不要果断点？"},
            {"title": "小白想问，为什么纳指一直涨啊", "content": "不太懂宏观经济，但感觉美股一直在涨，是不是有什么特殊原因？现在买会不会接盘？"},
            {"title": "听朋友说纳指比A股稳多了", "content": "朋友说你买A股还不如买纳指ETF，长期看一直在涨。有没有买过的兄弟说说是不是真的？"},
            {"title": "定投纳指一个月了，感觉还不错", "content": "小白开始定投纳指ETF了，虽然现在点位不低但打算长期拿着。有没有同样在定投的？一起交流"},
            {"title": "纳指定投选哪个ETF好啊", "content": "刚接触美股不太懂，看到有513100、159941好几个都可以买纳指，小白应该选哪个？"},
            {"title": "现在买纳指会不会高位接盘啊", "content": "纳指都涨到两万多点了，身边好多人都在买，但我总觉得太高了。有没有大佬分析一下风险？"},
            {"title": "把A股清仓全部换纳指了", "content": "A股太折磨人了，朋友说美股长期肯定涨，今天直接全部清仓A股买了纳指ETF，小白这样操作对吗？"},
            {"title": "纳指每天限额1000块怎么办", "content": "想多买点纳指但是说每天只能买1000块？有什么办法多买一点吗？太影响我定投了"},
            {"title": "新手刚开始定投美股求交流", "content": "刚工作一年想开始理财，看了一圈觉得纳指最稳，从今天开始每周定投500块，希望能坚持下去"},
            {"title": "好纠结要不要卖A股买纳指", "content": "看了最近一年的收益，A股基金亏了10%，纳指基金赚了25%，要不要把A股的钱转到纳指去？"},
        ],
        # Semiconductor: 追涨为主 — 芯片行情好，小白跟风买入
        "semiconductor": [
            {"title": "芯片半导体还能上车吗", "content": "最近芯片涨了好多啊，看周围人都在买半导体，我也心动了。求大神分析一下现在还能不能入？"},
            {"title": "宝妈想买半导体，有没有推荐", "content": "带娃之余想搞点投资，看芯片方向挺火的，但完全不知道买哪个好。有没有简单直接的推荐？"},
            {"title": "半导体ETF和芯片ETF有什么区别啊", "content": "小白不太懂，看到有半导体ETF也有芯片ETF，这俩是一样的吗？哪个更好？求解答"},
            {"title": "现在不买芯片老了会后悔", "content": "AI时代芯片就是石油，现在不买等涨到天上再买就晚了。我已经满仓半导体了，家人们冲不冲？"},
            {"title": "芯片这波能涨到什么时候", "content": "刚入市两周就赚了五个点，芯片太猛了。博主们都说还能涨很久，是不是该再多买一点？"},
            {"title": "大佬们看着眼馋，可以进点吗现在", "content": "天天看大佬们晒芯片的收益，自己手里还是空的，感觉再不买就要被时代抛弃了。现在还能追吗？"},
            {"title": "跟博主买了半导体基金今天赚了", "content": "关注的投资博主推荐了半导体方向，买了5000块今天就赚了200多，开心！要不要再多投一点？"},
            {"title": "半导体涨了好多不敢追了", "content": "已经涨了快30%了，现在进去是不是就是接盘的？但是朋友圈都在买，好纠结"},
            {"title": "纯小白想买点芯片方向的基金", "content": "完全没经验，但是感觉芯片是未来方向，想先从基金开始。有没有低风险的推荐？"},
            {"title": "芯片还能涨多久啊", "content": "已经上车半个月了，每天都在涨，有点慌。会不会突然大跌？要不要先卖一部分？"},
            {"title": "后悔没早点买半导体", "content": "两个月前就有人跟我说要买芯片，当时没当回事，现在涨了30%了才想起来。现在上车还晚不晚？"},
            {"title": "半导体的逻辑是什么啊看不懂", "content": "大家都说芯片好但我不太懂为什么好，有没有人能用大白话解释一下？买ETF就够了吗？"},
            {"title": "新手刚买了半导体ETF求带", "content": "今天第一天入市买了半导体ETF，什么都不懂，有没有一起交流的群？互相学习"},
            {"title": "AI概念涨疯了是不是该跑了", "content": "满仓半导体ETF一个月赚了15%，看到网上说现在是泡沫，是不是该止盈了？还是继续拿着？"},
        ],
    }
    result = {}
    for sector, posts in samples.items():
        parsed = []
        for i, p in enumerate(posts):
            parsed.append({
                "id": f"xhs_sim_{sector}_{i}",
                "title": p["title"],
                "content": p["content"],
                "platform": "xiaohongshu",
                "author": f"小红书用户_{sector}_{i}",
                "author_followers": 0,
                "likes": 0,
                "comments_count": 0,
                "collected_at": now,
                "tags": [],
            })
        result[sector] = parsed
    return result


def collect_all(max_requests: int = 20) -> Dict[str, List[Dict]]:
    """采集所有板块的小红书数据。API不可用时使用模拟数据。

    max_requests: 本次最多发起的 API 请求数（按次计费，免费测试 Key 每日仅 100 次，
    因此需要一个硬上限，避免翻页逻辑意外超支）。
    """
    if API_KEY:
        result = {}
        budget = _Budget(used=0, limit=max_requests)
        for sector_key, keywords in SEARCH_KEYWORDS.items():
            if not budget.allow():
                print(f"  ⚠️ 已达请求上限 {max_requests}，跳过剩余板块")
                break
            all_notes = []
            for kw in keywords:
                if not budget.allow():
                    print(f"  ⚠️ 已达请求上限 {max_requests}，停止采集")
                    break
                # 每个关键词取 10 条
                notes = search_notes(kw, count=10, budget=budget)
                all_notes.extend(notes)
                time.sleep(0.3)  # 轻微限速，避免触发 429
            # 按 id 去重
            seen = set()
            unique = []
            for n in all_notes:
                if n["id"] not in seen:
                    seen.add(n["id"])
                    unique.append(n)
            result[sector_key] = unique
            print(f"  [小红书-{sector_key}] 采集到 {len(unique)} 条")
        print(f"  [小红书] 本次共发起 {budget.used} 次 API 请求")
        return result
    else:
        print("  ⚠️ 无 API Key，使用模拟小红书数据")
        sample = _gen_sample_posts()
        for sector, posts in sample.items():
            print(f"  [小红书-模拟-{sector}] {len(posts)} 条")
        return sample


if __name__ == "__main__":
    if not API_KEY:
        print("请先设置 RNODE_API_KEY 环境变量")
        print("注册地址: https://rnote.dev/auth/register")
    else:
        data = collect_all()
        for k, v in data.items():
            print(f"{k}: {len(v)} posts")
