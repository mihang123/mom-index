"""
代理配置 — 统一管理出网代理。

原始仓库把 PROXY 硬编码为 127.0.0.1:7890（Clash 之类），
在没有该本地代理的机器上会直接抛连接错误。这里改为可配置：

优先级：
1. 环境变量 MOM_INDEX_PROXY（例: http://127.0.0.1:7890）
2. 环境变量 HTTP_PROXY / HTTPS_PROXY（requests 默认行为，无需显式传 proxies）
3. 直连

不设置任何代理变量时返回 None，交给 requests 自动处理（它会自行读取环境变量）。
"""
import os
from typing import Optional, Dict

PROXY_ENV_KEY = "MOM_INDEX_PROXY"


def get_proxies() -> Optional[Dict[str, str]]:
    """返回 requests 可用的 proxies 字典；None 表示不显式指定。"""
    raw = os.environ.get(PROXY_ENV_KEY, "").strip()
    if not raw:
        return None
    return {"http": raw, "https": raw}
