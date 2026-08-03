"""HTTP server with no-cache headers for dashboard development."""
import http.server
import os
from urllib.parse import unquote, urlsplit

FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据从 frontend/data 读取（pipeline 每次运行后会把 data/ 同步到此目录）
DATA_DIR = os.path.join(FRONTEND_DIR, "data")
PUBLIC_DATA_FILES = {"dashboard_data.json", "history.json", "xhs_posts.json"}

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        request_path = unquote(urlsplit(path).path)
        if request_path.startswith("/data/"):
            filename = os.path.basename(request_path)
            if filename in PUBLIC_DATA_FILES:
                return os.path.join(DATA_DIR, filename)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.chdir(FRONTEND_DIR)
    http.server.test(HandlerClass=NoCacheHandler, port=port)
