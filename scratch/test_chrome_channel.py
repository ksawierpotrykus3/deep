import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def test_launch():
    profile = Path("gemini_proxy/data/gemini_profile").resolve()
    p = await async_playwright().start()
    try:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--lang=en-US,en",
            ],
        )
        print("PLAYWRIGHT_CHROME_CHANNEL_LAUNCH_SUCCESS: True")
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.google.com")
        print("PAGE_TITLE:", await page.title())
        await context.close()
    finally:
        await p.stop()

if __name__ == "__main__":
    asyncio.run(test_launch())
