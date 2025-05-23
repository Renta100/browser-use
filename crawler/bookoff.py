from __future__ import annotations
import asyncio
import json
import re
import sys
from typing import List, Dict
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

SEARCH_URL = "https://shopping.bookoff.co.jp/search/?search_word={q}&category=game"

# --- selectors ---
LOAD_MORE = "button.js-infiniteScroll__loadMore"

ROW_OUTER = "div.productItem, li.productItem"
ROW_LINK = "a.productItem__imageLink, a.productItem__link"

MODAL_BTN = "a.productInformation__list__link.js-modal.modal__trigger"
MODAL_BODY = "#modalStoreInformation .modalStoreInformation__body"
ROW_LI = "#modalStoreInformation li.modalStoreInformation__item"
SHOP_LINK = "a.modalStoreInformation__link"
PRICE_SPAN = "span.modalStoreInformation__price"


async def load_all_rows(page, max_clicks: int = 80) -> None:
    """Scroll and click "load more" buttons until no new rows appear."""
    clicks = 0
    prev_count = 0
    while clicks < max_clicks:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        btn = page.locator(LOAD_MORE)
        if await btn.is_visible():
            await btn.click()
            clicks += 1
        await page.wait_for_timeout(800)
        current = await page.locator(ROW_OUTER).count()
        if current == prev_count:
            break
        prev_count = current
    print(f"🔍 load_more clicks = {clicks}")


async def find_target_row(page, code: str):
    """Return the product row that matches the given code."""
    rows = page.locator(ROW_OUTER)
    for i in range(await rows.count()):
        r = rows.nth(i)
        attr = await r.get_attribute("data-product-code")
        if attr and code in attr:
            return r
        inner = r.locator(f'[data-product-code*="{code}"]')
        if await inner.count():
            return r
    return None


async def fetch_bookoff_shops(isbn: str) -> List[Dict]:
    """Return list of shop information for a given ISBN/JAN."""
    url = SEARCH_URL.format(q=isbn)
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=False, slow_mo=160)
        page = await browser.new_page()
        await page.goto(url, timeout=60_000)
        print("🔍 search page loaded")

        await load_all_rows(page)
        total = await page.locator(ROW_OUTER).count()
        print("🔍 rows loaded =", total)

        row = await find_target_row(page, isbn)
        if row is None:
            print("❌ 該当アイテムが見つからない")
            await browser.close()
            return []

        print("✅ row found → click")
        await row.locator(ROW_LINK).first.click(force=True)

        btn = page.locator(MODAL_BTN).first
        if not await btn.count():
            print("❌ 店舗モーダルボタンが無い")
            await browser.close()
            return []
        await btn.click(force=True)

        try:
            await page.locator(MODAL_BODY).first.wait_for(state="visible", timeout=10_000)
        except PWTimeout:
            print("❌ モーダルが開かない")
            await browser.close()
            return []

        body = page.locator(MODAL_BODY)
        prev = 0
        for _ in range(12):
            h = await body.evaluate("el => el.scrollHeight")
            if h == prev:
                break
            await body.evaluate("el => el.scrollBy(0, el.clientHeight)")
            await page.wait_for_timeout(400)
            prev = h

        results, seen = [], set()
        for li in await page.locator(ROW_LI).all():
            shop = (await li.locator(SHOP_LINK).text_content() or "").strip()
            if not shop or shop in seen:
                continue
            seen.add(shop)
            price_txt = await li.locator(PRICE_SPAN).text_content()
            price = int(re.sub(r"\D", "", price_txt)) if price_txt else None
            results.append({"isbn": isbn, "shop": shop, "price": price})

        await browser.close()
        print(f"✅ finished – {len(results)} 店舗")
        return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m crawler.bookoff <ISBN/JAN>")
        sys.exit(1)

    jan = re.sub(r"\D", "", sys.argv[1])
    data = asyncio.run(fetch_bookoff_shops(jan))
    print(json.dumps(data, ensure_ascii=False, indent=2))
