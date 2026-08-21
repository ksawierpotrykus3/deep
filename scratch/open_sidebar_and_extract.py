import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def open_sidebar_and_extract():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Open sidebar if collapsed
    print("Opening sidebar...")
    await page.evaluate("""
        () => {
            const openBtn = document.querySelector('button[aria-label*="Otwórz pasek boczny"], button[aria-label*="Open side panel"], button.side-nav-sparkle-button');
            if (openBtn && !openBtn.hasAttribute('disabled')) {
                openBtn.click();
            }
        }
    """)
    await asyncio.sleep(1.0)
    
    # 2. Find conversation links
    conv_links = await page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, [role="link"], mat-list-item, div.conversation-title, .gem-nav-list-item')).map(el => ({
                text: el.innerText ? el.innerText.trim() : '',
                href: el.getAttribute('href') || '',
                tag: el.tagName,
                ariaLabel: el.getAttribute('aria-label') || ''
            })).filter(l => l.text.length > 0 || l.ariaLabel.length > 0);
            return links.slice(0, 30);
        }
    """)
    print("ALL_SIDEBAR_LINKS:", conv_links)
    
    # 3. Click the GAAFET conversation
    clicked = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('a, mat-list-item, div, button')).filter(el => 
                (el.innerText || '').includes('GAAFET') || 
                (el.innerText || '').includes('Tranzystory') ||
                (el.getAttribute('aria-label') || '').includes('GAAFET')
            );
            const target = items.find(i => i.tagName === 'A' || i.getAttribute('role') === 'link' || i.closest('a'));
            if (target) {
                target.click();
                return { clicked: true, text: target.innerText.trim() };
            }
            if (items.length > 0) {
                items[0].click();
                return { clicked: true, text: items[0].innerText.trim() };
            }
            return { clicked: false };
        }
    """)
    print("CLICKED_GAAFET_CHAT:", clicked)
    await asyncio.sleep(3.0)
    
    # 4. Extract research report
    report_data = await page.evaluate("""
        () => {
            // Find all rich text / markdown blocks
            const elements = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], main, message-content, div.markdown, model-response')).map(el => ({
                text: el.innerText.trim(),
                tag: el.tagName,
                className: el.className,
                len: el.innerText.trim().length
            })).filter(e => e.len > 300);

            elements.sort((a, b) => b.len - a.len);

            return {
                foundCount: elements.length,
                longestLen: elements.length > 0 ? elements[0].len : 0,
                longestText: elements.length > 0 ? elements[0].text : ''
            };
        }
    """)
    print("REPORT_DATA:", {"foundCount": report_data["foundCount"], "longestLen": report_data["longestLen"]})
    
    full_report = report_data.get("longestText", "")
    if len(full_report) > 500:
        out_file = Path("scratch/GAAFET_Deep_Research_Report.md")
        out_file.write_text(full_report, encoding="utf-8")
        print(f"\n[SUKCES] Wyodrębniono i zapisano pełny raport Deep Research ({len(full_report)} znaków) w:\n{out_file.resolve()}")
        print("\n==================== POCZĄTEK RAPORTU ====================")
        print(full_report[:1500])
        print("\n==================== KONIEC RAPORTU ====================")
        print(full_report[-800:])

    await mgr.close()

if __name__ == "__main__":
    asyncio.run(open_sidebar_and_extract())
