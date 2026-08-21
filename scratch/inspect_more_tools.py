import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_more_tools():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Click + button
    plus_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]').first
    await plus_btn.click()
    print("PLUS BUTTON CLICKED!")
    await asyncio.sleep(0.8)
    
    # 2. Click "Więcej narzędzi" button
    more_tools_clicked = await page.evaluate("""
        () => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.innerText || '').includes('Więcej narzędzi') ||
                (b.getAttribute('aria-label') || '').includes('Więcej narzędzi') ||
                b.classList.contains('more-tools-button')
            );
            if (btn) {
                btn.click();
                return { clicked: true, text: btn.innerText };
            }
            return { clicked: false };
        }
    """)
    print("MORE_TOOLS_CLICKED:", more_tools_clicked)
    await asyncio.sleep(1.0)
    
    # 3. Inspect items now visible
    items = await page.evaluate("""
        () => {
            const allBtns = Array.from(document.querySelectorAll('.cdk-overlay-container button, .mat-mdc-menu-content button, [role="menuitem"], .toolbox-drawer button, mat-list-item, div[role="button"]')).map(el => ({
                text: el.innerText.trim(),
                ariaLabel: el.getAttribute('aria-label') || '',
                tag: el.tagName,
                className: el.className
            }));
            return allBtns;
        }
    """)
    print("ITEMS_AFTER_MORE_TOOLS:", items)
    
    # 4. Click Deep Research
    clicked_dr = await page.evaluate("""
        () => {
            const allBtns = Array.from(document.querySelectorAll('.cdk-overlay-container button, [role="menuitem"], button, mat-list-item, div[role="button"]'));
            const drBtn = allBtns.find(b => 
                (b.innerText || '').includes('Deep Research') ||
                (b.getAttribute('aria-label') || '').includes('Deep Research')
            );
            if (drBtn) {
                drBtn.click();
                return { clicked: true, text: drBtn.innerText };
            }
            return { clicked: false };
        }
    """)
    print("CLICKED_DEEP_RESEARCH_RESULT:", clicked_dr)
    await asyncio.sleep(1.5)
    
    # Check input area for Deep Research badge
    input_dom = await page.evaluate("""
        () => {
            const chips = Array.from(document.querySelectorAll('input-area-v2 *, input-container *')).map(el => ({
                tag: el.tagName,
                className: el.className,
                text: el.innerText ? el.innerText.trim() : ''
            })).filter(e => e.text.includes('Deep Research'));
            return chips;
        }
    """)
    print("INPUT_DOM_BADGES:", input_dom)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_more_tools())
