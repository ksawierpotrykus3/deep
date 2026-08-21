import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_dr():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Click + button
    plus_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]').first
    await plus_btn.click()
    print("PLUS BUTTON CLICKED!")
    await asyncio.sleep(1.0)
    
    # Inspect all menu options
    menu_items = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('.cdk-overlay-container button, .mat-mdc-menu-content button, [role="menuitem"], .toolbox-drawer button, mat-list-item')).map(el => ({
                text: el.innerText.trim(),
                ariaLabel: el.getAttribute('aria-label') || '',
                tag: el.tagName,
                className: el.className
            }));
            return items;
        }
    """)
    print("ALL_MENU_ITEMS_IN_OVERLAY:", menu_items)
    
    # Click Deep Research
    clicked = await page.evaluate("""
        () => {
            const allBtns = Array.from(document.querySelectorAll('.cdk-overlay-container button, [role="menuitem"], button, mat-list-item, div[role="button"]'));
            const drBtn = allBtns.find(b => 
                (b.innerText || '').includes('Deep Research') ||
                (b.getAttribute('aria-label') || '').includes('Deep Research')
            );
            if (drBtn) {
                drBtn.click();
                return { clicked: true, text: drBtn.innerText, tag: drBtn.tagName, class: drBtn.className };
            }
            return { clicked: false };
        }
    """)
    print("CLICKED_DEEP_RESEARCH:", clicked)
    await asyncio.sleep(1.5)
    
    # Check input area DOM for Deep Research chip / badge
    input_dom = await page.evaluate("""
        () => {
            const inputArea = document.querySelector('input-area-v2') || document.querySelector('input-container');
            const chips = Array.from(document.querySelectorAll('input-area-v2 *, input-container *')).map(el => ({
                tag: el.tagName,
                className: el.className,
                text: el.innerText ? el.innerText.trim() : ''
            })).filter(e => e.text.includes('Deep Research'));
            return {
                chipsFound: chips.length,
                chips: chips.slice(0, 5)
            };
        }
    """)
    print("INPUT_DOM_AFTER_CLICK:", input_dom)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_dr())
