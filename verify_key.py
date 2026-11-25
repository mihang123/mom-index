"""
rnote.dev API Key 验证脚本 —— 走免费接口，不消耗余额

用法：
    set RNODE_API_KEY=sk-你的Key
    python verify_key.py

原理：
    /api/v1/account/* 全部免费，不扣余额，余额为 0 也能调，
    限流 30 次/分钟。因此先用它确认 Key 有效、余额多少、
    实际成交价是多少，再决定要不要充值。
"""
import os
import sys
import json
import requests

BASE = "https://rnote.dev/api/v1"
PROXY = os.environ.get("MOM_INDEX_PROXY") or None


def call(path: str) -> tuple:
    """返回 (http状态码, 响应体dict)"""
    key = os.environ.get("RNODE_API_KEY", "").strip()
    if not key:
        print("✗ 未设置环境变量 RNODE_API_KEY")
        print("  set RNODE_API_KEY=sk-你的Key")
        sys.exit(1)
    try:
        r = requests.get(
            f"{BASE}/{path}",
            headers={"X-API-Key": key, "accept": "application/json"},
            proxies=PROXY,
            timeout=20,
        )
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"_raw": r.text[:300]}
    except Exception as e:
        print(f"✗ 请求失败: {type(e).__name__}: {e}")
        sys.exit(1)


def main() -> None:
    print("=" * 60)
    print("   rnote.dev API Key 验证（全部走免费接口，不扣余额）")
    print("=" * 60)

    key = os.environ.get("RNODE_API_KEY", "").strip()
    if not key:
        print("✗ 未设置环境变量 RNODE_API_KEY")
        print("  set RNODE_API_KEY=sk-你的Key")
        sys.exit(1)
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 14 else "（过短）"
    print(f"  Key: {masked}")
    print()

    # ---- 1. 账号信息：邮箱是否已验证 ----
    print("── /account/me ──")
    code, body = call("account/me")
    if code != 200:
        print(f"  ✗ HTTP {code}: {json.dumps(body, ensure_ascii=False)[:200]}")
        if code == 401:
            print("\n  → Key 无效或未携带。请检查是否复制完整、是否已完成邮箱验证。")
        elif code == 402:
            print("  → 余额不足。账号接口虽标注免费，但请先充值至少 $5 后重试。")
        sys.exit(1)

    for k in ("email", "role", "email_verified", "reseller_discount",
              "enterprise_pricing", "rate_limit"):
        if k in body:
            print(f"  {k}: {body[k]}")
    if body.get("email_verified") is False:
        print("  ⚠ 邮箱尚未验证 —— 部分接口可能受限，建议先完成邮箱验证")
    print()

    # ---- 2. 余额 ----
    print("── /account/balance ──")
    code, body = call("account/balance")
    if code == 200:
        for k in ("balance", "total_deposited", "total_charged", "overdraft_limit"):
            if k in body:
                print(f"  {k}: {body[k]}")
        bal = body.get("balance")
        if bal is not None:
            try:
                need = 16 * 0.01  # 四个板块 × 4 关键词 = 16 次搜索
                print(f"\n  跑一轮完整采集约需 16 次搜索请求 = ${need:.2f}")
                if float(bal) < need:
                    print(f"  ⚠ 余额 ${bal} 不足以跑完一轮，建议充值 $5")
                else:
                    print(f"  ✓ 余额充足")
            except (TypeError, ValueError):
                pass
    else:
        print(f"  ✗ HTTP {code}: {json.dumps(body, ensure_ascii=False)[:200]}")
    print()

    # ---- 3. 当前 Key 的信息与 scope ----
    print("── /account/key ──")
    code, body = call("account/key")
    if code == 200:
        for k, v in body.items():
            if k in ("name", "status", "scope", "rate_limit", "note", "comment"):
                print(f"  {k}: {v}")
    else:
        print(f"  ✗ HTTP {code}: {json.dumps(body, ensure_ascii=False)[:200]}")
    print()

    # ---- 4. 实际成交价（经销商折扣后）----
    print("── /account/pricing ──")
    code, body = call("account/pricing")
    if code == 200:
        rows = body if isinstance(body, list) else body.get("pricing", [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            ep = row.get("endpoint_pattern", "")
            if "crawler" in ep or "pgy" in ep:
                print(f"  {ep}")
                print(f"    牌价: {row.get('price_per_request')}  你的价: {row.get('your_price')}")
                if row.get("promo_price"):
                    print(f"    促销价: {row.get('promo_price')} (至 {row.get('promo_expires_at')})")
    else:
        print(f"  ✗ HTTP {code}: {json.dumps(body, ensure_ascii=False)[:200]}")

    print()
    print("=" * 60)
    print("  ✓ Key 有效，免费接口全部调用成功")
    print("  → 现在可以充值并调用 /api/v2/crawler/* 拉取真实小红书数据")
    print("=" * 60)


if __name__ == "__main__":
    main()
