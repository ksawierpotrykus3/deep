import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_models():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    print("Navigating to Gemini...")
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    picker_info = await page.evaluate("""
        () => {
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"], mat-select, [aria-haspopup="menu"]')).map(b => ({
                text: b.innerText.trim(),
                ariaLabel: b.getAttribute('aria-label') || '',
                tag: b.tagName,
                className: b.className,
                ariaExpanded: b.getAttribute('aria-expanded')
            })).filter(b => b.text.includes('Pro') || b.text.includes('Flash') || b.text.includes('Rozszerzony') || b.ariaLabel.includes('model') || b.ariaLabel.includes('Model'));
            return buttons;
        }
    """)
    print("MODEL_PICKER_BUTTONS:", picker_info)
    
    clicked = await page.evaluate("""
        () => {
            const btn = Array.from(document.querySelectorAll('button, div[role="button"]')).find(b => 
                (b.innerText.includes('Pro') || b.innerText.includes('Flash') || b.innerText.includes('Rozszerzony')) &&
                !b.hasAttribute('disabled')
            );
            if (btn) {
                btn.click();
                return { clicked: true, text: btn.innerText };
            }
            return { clicked: false };
        }
    """)
    print("CLICKED_BUTTON:", clicked)
    await asyncio.sleep(1.5)
    
    menu_items = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('button, [role="menuitem"], [role="menuitemcheckbox"], [role="option"], div.mat-mdc-menu-panel *, .menu-item, [role="menu"] *')).map(el => ({
                text: el.innerText.trim(),
                role: el.getAttribute('role'),
                tag: el.tagName,
                className: el.className,
                ariaChecked: el.getAttribute('aria-checked')
            })).filter(i => i.text.length > 0 && (i.text.includes('3.') || i.text.includes('Flash') || i.text.includes('Pro') || i.text.includes('Myślenie') || i.text.includes('rozszerzone')));
            return items;
        }
    """)
    print("MENU_ITEMS_FOUND:", menu_items)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_models())
