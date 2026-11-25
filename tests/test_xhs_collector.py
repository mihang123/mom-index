"""
针对小红书采集器的离线测试 —— 不需要 API Key。

用本地 mock server 模拟 rnote.dev 的真实响应结构，验证：
1. 请求参数名正确（page / sort_type，而非旧的 count / sort）
2. 翻页时正确回传 search_id 与 search_session_id
3. 响应结构解析正确，且会丢弃非笔记卡片
"""
import sys
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RECEIVED = []


def _make_item(i, page):
    return {
        "id": f"note_{page}_{i}",
        "note_card": {
            "id": f"note_{page}_{i}",
            "display_title": f"第{page}页第{i}条 黄金新手怎么买",
            "desc": "小白一个，完全不懂",
            "user": {"nickname": f"宝妈_{page}_{i}", "follower_count": 12},
            "interact_info": {"liked_count": i, "comment_count": i},
        },
        "type": "normal_note",
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        RECEIVED.append({k: v[0] for k, v in q.items()})
        page = int(q.get("page", ["1"])[0])
        # 服务端约定：翻页必须带 search_id，否则视为非法
        if page > 1 and "search_id" not in q:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"need search_id")
            return
        items = [_make_item(i, page) for i in range(1, 6)]
        if page == 1:
            # 混入一个非笔记卡片，应被过滤掉
            items.append({"type": "recommend_module", "module": {"title": "推荐模块"}})
        body = {
            "success": True,
            "data": {
                "data": {"items": items},
                "search_id": "SID_abc",
                "search_session_id": "SSID_def",
                "page": page,
                "next_page": page + 1,
            },
            "billed": True,
        }
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class XhsCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 8898), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

        import collectors.xhs_collector as xc
        cls.xc = xc
        xc.API_KEY = "sk-mock-test-key"
        xc.API_BASE = "http://127.0.0.1:8898/api/v2"
        xc.get_proxies = lambda: None

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        RECEIVED.clear()

    def test_uses_page_and_sort_type_not_count_and_sort(self):
        self.xc.search_notes("黄金怎么买", count=6)
        self.assertTrue(RECEIVED)
        first = RECEIVED[0]
        self.assertNotIn("count", first, "不应再传 count（服务端会静默忽略）")
        self.assertNotIn("sort", first, "不应再传 sort（服务端会静默忽略）")
        self.assertEqual(first.get("page"), "1")
        self.assertEqual(first.get("sort_type"), "general")

    def test_pagination_carries_search_id_and_session(self):
        notes = self.xc.search_notes("黄金怎么买", count=12)
        self.assertEqual(len(notes), 12)
        self.assertGreaterEqual(len(RECEIVED), 2)
        second = RECEIVED[1]
        self.assertEqual(second.get("page"), "2")
        self.assertEqual(second.get("search_id"), "SID_abc")
        self.assertEqual(second.get("search_session_id"), "SSID_def")

    def test_parses_note_and_drops_non_note_cards(self):
        notes = self.xc.search_notes("黄金怎么买", count=5)
        self.assertTrue(notes)
        n = notes[0]
        self.assertEqual(n["platform"], "xiaohongshu")
        self.assertTrue(n["title"])
        self.assertTrue(n["id"].startswith("note_"))
        # 非笔记卡片没有 note_card、没有 id，应被过滤
        self.assertTrue(all(x["id"].startswith("note_") for x in notes))

    def test_budget_limits_number_of_requests(self):
        """预算上限必须真的拦住翻页 —— 免费测试 Key 每日仅 100 次，不能超支。"""
        budget = self.xc._Budget(used=0, limit=2)
        notes = self.xc.search_notes("黄金怎么买", count=20, budget=budget)
        self.assertLessEqual(budget.used, 2, "实际请求数不应超过预算上限")
        self.assertGreaterEqual(budget.used, 1)
        self.assertEqual(len(RECEIVED), budget.used)

    def test_collect_all_respects_max_requests(self):
        """collect_all 的 max_requests 是硬上限。"""
        self.xc.collect_all(max_requests=3)
        self.assertLessEqual(len(RECEIVED), 3)


if __name__ == "__main__":
    unittest.main()
