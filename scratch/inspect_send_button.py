import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_send_btn():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Type text
    await mgr._inject_prompt_to_input("Test send button")
    await asyncio.sleep(1.0)
    
    # Inspect all buttons in input-area-v2
    btn_info = await page.evaluate("""
        () => {
            const btns = Array.from(document.querySelectorAll('input-area-v2 button, input-container button, fieldset button, button')).map(b => ({
                ariaLabel: b.getAttribute('aria-label') || '',
                className: b.className,
                disabled: b.hasAttribute('disabled'),
                tag: b.tagName,
                text: b.innerText.trim(),
                innerHTML: b.innerHTML.slice(0, 80)
            }));
            return btns;
        }
    """)
    print("ALL_BUTTONS_IN_INPUT_AREA:", btn_info)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_send_btn())
