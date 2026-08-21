import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_menu():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Click upload button
    upload_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"]').first
    await upload_btn.click()
    print("UPLOAD BUTTON CLICKED!")
    await asyncio.sleep(1.0)
    
    menu_items = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('.cdk-overlay-container button, .mat-mdc-menu-content button, [role="menuitem"]')).map(el => ({
                text: el.innerText.trim(),
                ariaLabel: el.getAttribute('aria-label') || '',
                tag: el.tagName,
                className: el.className
            }));
            return items;
        }
    """)
    print("UPLOAD_MENU_OPTIONS:", menu_items)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_menu())
