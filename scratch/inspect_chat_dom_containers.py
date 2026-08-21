import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_containers():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Check all tag names and classes of chat turns
    res = await page.evaluate("""
        () => {
            const userElems = Array.from(document.querySelectorAll('user-query, .user-query, [data-test-id="user-query"]')).map(e => e.tagName);
            const modelElems = Array.from(document.querySelectorAll('model-response, .model-response, [data-test-id="model-response"]')).map(e => e.tagName);
            return {
                userElems,
                modelElems
            };
        }
    """)
    print("DOM_CHAT_TAGS:", res)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_containers())
