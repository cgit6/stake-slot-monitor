#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from curl_cffi import requests as curl_requests
from playwright.sync_api import sync_playwright

PAGE_URL = "https://stake.com/zh/casino/group/slots"
API_URL = "https://stake.com/_api/graphql"
OUT = Path(os.getenv("STAKE_TOP50_OUT", "data/stake_top50_latest.json"))
FAIL_OUT = Path(os.getenv("STAKE_TOP50_FAIL_OUT", "stake_top50_failed.json"))
PROFILE_DIR = Path(
    os.getenv("STAKE_PROFILE_DIR", str(Path.home() / ".stake-slot-monitor-profile"))
).expanduser()

# Keep bootstrap and scheduled runs on the same browser fingerprint.
BROWSER_UA = os.getenv(
    "STAKE_BROWSER_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.7390.37 Safari/537.36",
)

QUERY = r'''query SlugKuratorGroup($slug: String!, $limit: Int!, $offset: Int!, $showGames: Boolean = true, $sort: GameKuratorGroupGameSortEnum = popular, $showProviders: Boolean = false, $filterIds: [String!], $isActivePlayersFeatureFlagOn: Boolean = false, $language: LanguageEnum = en) {
  slugKuratorGroup(slug: $slug) {
    id
    slug
    translation
    gameCount(filterIds: $filterIds, language: $language)
    groupGamesList(limit: $limit, offset: $offset, sort: $sort, filterIds: $filterIds, language: $language) @include(if: $showGames) {
      id
      game {
        id
        name
        slug
        playerCount @include(if: $isActivePlayersFeatureFlagOn)
        groupGames { group { id slug translation type } }
      }
    }
  }
}'''

CHALLENGE_MARKERS = (
    "just a moment",
    "請稍候",
    "正在執行安全驗證",
    "驗證您是人類",
    "verify you are human",
)


def vars_for(slug="slots"):
    return {
        "slug": slug,
        "limit": 50,
        "offset": 0,
        "showGames": True,
        "sort": "popular",
        "showProviders": True,
        "filterIds": None,
        "isActivePlayersFeatureFlagOn": True,
        "language": "en",
    }


def provider_from_game(game):
    groups = game.get("groupGames") or []
    for entry in groups:
        g = (entry or {}).get("group") or {}
        if "provider" in str(g.get("type") or "").lower():
            return g.get("translation") or g.get("slug") or g.get("id")
    for entry in groups:
        g = (entry or {}).get("group") or {}
        slug = str(g.get("slug") or "")
        if slug and slug not in {"slots", "popular", "recommended-slots"}:
            return g.get("translation") or slug
    return None


def normalize(body):
    root = ((body or {}).get("data") or {}).get("slugKuratorGroup") or {}
    items = root.get("groupGamesList") or []
    rows = []
    for i, item in enumerate(items[:50], 1):
        game = (item or {}).get("game") or {}
        rows.append(
            {
                "rank": i,
                "id": game.get("id"),
                "name": game.get("name"),
                "slug": game.get("slug"),
                "playerCount": game.get("playerCount"),
                "provider": provider_from_game(game),
            }
        )
    return rows


def is_cloudflare_challenge(page):
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=2000)[:4000]
    except Exception:
        body = ""
    text = f"{title}\n{body}".lower()
    return any(marker in text for marker in CHALLENGE_MARKERS)


def new_persistent_context(playwright, *, headless):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        locale="zh-TW",
        timezone_id="Asia/Taipei",
        viewport={"width": 1440, "height": 1000},
        user_agent=BROWSER_UA,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return context


def bootstrap_profile(timeout_seconds=600):
    """One-time/manual Cloudflare verification using the same persistent profile."""
    print(f"Stake browser profile: {PROFILE_DIR}")
    print("A browser window will open. Complete the Cloudflare 'verify you are human' check once.")
    print("Keep this terminal running until it reports that verification is complete.")

    with sync_playwright() as p:
        context = new_persistent_context(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=120_000)
            deadline = time.time() + timeout_seconds
            passed_at = None
            while time.time() < deadline:
                if not is_cloudflare_challenge(page) and "stake" in (page.url or "").lower():
                    if passed_at is None:
                        passed_at = time.time()
                    # Require several stable seconds after the challenge disappears.
                    if time.time() - passed_at >= 5:
                        print("Cloudflare verification passed. Profile has been saved.")
                        print(f"Current page: {page.url}")
                        return 0
                else:
                    passed_at = None
                page.wait_for_timeout(1000)

            try:
                page.screenshot(path="stake_top50_bootstrap_timeout.png", full_page=True)
            except Exception:
                pass
            print("Timed out waiting for the Cloudflare verification.")
            return 2
        finally:
            context.close()


def try_http(debug):
    """Fast path; may be blocked even when the persistent browser profile works."""
    s = curl_requests.Session(impersonate="chrome")
    try:
        page = s.get(PAGE_URL, timeout=30)
        debug["http_page_status"] = page.status_code
        headers = {
            "accept": "*/*",
            "accept-language": "zh-TW,zh;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "origin": "https://stake.com",
            "referer": PAGE_URL,
            "x-language": "zh",
        }
        best = []
        for slug in ("slots", "recommended-slots"):
            r = s.post(
                API_URL,
                headers=headers,
                json={"query": QUERY, "variables": vars_for(slug)},
                timeout=30,
            )
            try:
                body = r.json()
            except Exception:
                body = None
            rows = normalize(body) if body else []
            debug.setdefault("http_attempts", []).append(
                {"slug": slug, "status": r.status_code, "count": len(rows)}
            )
            if len(rows) > len(best):
                best = rows
            if len(rows) >= 50:
                return rows[:50]
        return best
    except Exception as e:
        debug["http_error"] = repr(e)
        return []
    finally:
        s.close()


def try_browser(debug):
    """Reuse a manually verified persistent Stake browser profile."""
    observed = []
    best_rows = []

    with sync_playwright() as p:
        context = new_persistent_context(p, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        def on_request(req):
            if "/_api/graphql" not in req.url or req.method != "POST":
                return
            try:
                payload = req.post_data_json
                if callable(payload):
                    payload = payload()
            except Exception:
                try:
                    payload = json.loads(req.post_data or "{}")
                except Exception:
                    return
            if isinstance(payload, dict) and "SlugKuratorGroup" in (
                payload.get("query") or ""
            ):
                observed.append(
                    {
                        "query": payload.get("query"),
                        "variables": payload.get("variables") or {},
                        "operationName": payload.get("operationName"),
                    }
                )

        page.on("request", on_request)
        try:
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(12_000)
            debug["browser_title"] = page.title()
            debug["browser_url"] = page.url
            debug["profile_dir"] = str(PROFILE_DIR)

            if is_cloudflare_challenge(page):
                debug["bootstrapRequired"] = True
                debug["reason"] = "Cloudflare human verification is required for the persistent browser profile"
                return []

            payloads = []
            for obs in reversed(observed):
                v = dict(obs.get("variables") or {})
                if v.get("slug") not in {"slots", "recommended-slots"}:
                    continue
                v.update(
                    {
                        "limit": 50,
                        "offset": 0,
                        "sort": "popular",
                        "showGames": True,
                        "isActivePlayersFeatureFlagOn": True,
                    }
                )
                payload = {"query": obs["query"], "variables": v}
                if obs.get("operationName"):
                    payload["operationName"] = obs["operationName"]
                payloads.append(payload)
            for slug in ("slots", "recommended-slots"):
                payloads.append({"query": QUERY, "variables": vars_for(slug)})

            for payload in payloads:
                response = page.evaluate(
                    """async (payload) => {
                      try {
                        const r = await fetch('/_api/graphql', {
                          method: 'POST', credentials: 'include',
                          headers: {'accept':'*/*','content-type':'application/json','x-language':'zh'},
                          body: JSON.stringify(payload)
                        });
                        const text = await r.text();
                        let data = null; try { data = JSON.parse(text); } catch(e) {}
                        return {status:r.status, data, preview:text.slice(0,300)};
                      } catch(e) { return {status:0, data:null, preview:String(e)}; }
                    }""",
                    payload,
                )
                rows = normalize(response.get("data")) if response.get("data") else []
                debug.setdefault("browser_attempts", []).append(
                    {
                        "slug": (payload.get("variables") or {}).get("slug"),
                        "status": response.get("status"),
                        "count": len(rows),
                        "preview": response.get("preview"),
                    }
                )
                if len(rows) > len(best_rows):
                    best_rows = rows
                if len(rows) >= 50:
                    return rows[:50]

            # Fallback to Stake's own pagination.
            collected = {}

            def on_response(resp):
                if "/_api/graphql" not in resp.url:
                    return
                try:
                    req = resp.request
                    payload = req.post_data_json
                    if callable(payload):
                        payload = payload()
                    if not isinstance(payload, dict) or "SlugKuratorGroup" not in (
                        payload.get("query") or ""
                    ):
                        return
                    body = resp.json()
                    rows = normalize(body)
                    offset = int((payload.get("variables") or {}).get("offset") or 0)
                    for j, row in enumerate(rows):
                        collected[offset + j] = row
                except Exception:
                    pass

            page.on("response", on_response)
            page.reload(wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(8_000)
            if is_cloudflare_challenge(page):
                debug["bootstrapRequired"] = True
                debug["reason"] = "Cloudflare verification expired while reloading the persistent profile"
                return best_rows[:50]

            for _ in range(12):
                if len(collected) >= 50:
                    break
                clicked = False
                for label in (
                    "載入更多",
                    "加载更多",
                    "Load More",
                    "顯示更多",
                    "Show More",
                ):
                    try:
                        loc = page.get_by_text(label, exact=False).last
                        if loc.is_visible(timeout=800):
                            loc.click(timeout=3000)
                            page.wait_for_timeout(2500)
                            clicked = True
                            break
                    except Exception:
                        pass
                if not clicked:
                    page.mouse.wheel(0, 6000)
                    page.wait_for_timeout(1800)

            if len(collected) > len(best_rows):
                best_rows = [collected[k] for k in sorted(collected)[:50]]
                for i, row in enumerate(best_rows, 1):
                    row["rank"] = i
            debug["browser_ui_collected"] = len(collected)
            return best_rows[:50]
        except Exception as e:
            debug["browser_error"] = repr(e)
            return best_rows[:50]
        finally:
            try:
                page.screenshot(path="stake_top50_debug.png", full_page=True)
            except Exception:
                pass
            context.close()


def run_snapshot():
    captured = datetime.now(ZoneInfo("Asia/Taipei")).replace(microsecond=0).isoformat()
    debug = {}
    rows = try_http(debug)
    source = "graphql-http"
    if len(rows) < 50:
        browser_rows = try_browser(debug)
        if len(browser_rows) > len(rows):
            rows = browser_rows
            source = "stake-browser-profile"

    result = {
        "capturedAtTaipei": captured,
        "status": "ok" if len(rows) == 50 else "failed",
        "count": len(rows),
        "source": source,
        "games": rows,
        "debug": debug,
    }

    if len(rows) != 50:
        FAIL_OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "failed",
                    "count": len(rows),
                    "bootstrapRequired": bool(debug.get("bootstrapRequired")),
                    "debug": debug,
                },
                ensure_ascii=False,
            )
        )
        return 2

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "count": 50,
                "capturedAtTaipei": captured,
                "source": source,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Open a headed persistent browser once so the user can complete Cloudflare verification manually.",
    )
    parser.add_argument(
        "--bootstrap-timeout",
        type=int,
        default=600,
        help="Seconds to wait for manual Cloudflare verification (default: 600).",
    )
    args = parser.parse_args()

    if args.bootstrap:
        sys.exit(bootstrap_profile(args.bootstrap_timeout))
    sys.exit(run_snapshot())


if __name__ == "__main__":
    main()
