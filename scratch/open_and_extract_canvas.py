import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def open_and_extract():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Find and click the GAAFET conversation link in history
    print("Finding GAAFET conversation in sidebar...")
    clicked = await page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a, [role="button"], mat-list-item, div.conversation, .chat-history-item')).map(el => ({
                text: el.innerText ? el.innerText.trim() : '',
                href: el.getAttribute('href') || '',
                tag: el.tagName
            })).filter(l => 
                l.text.includes('GAAFET') || 
                l.text.includes('Tranzystory') || 
                l.text.includes('Analiza') ||
                l.href.includes('/app/')
            );
            return links;
        }
    """)
    print("SIDEBAR_LINKS_FOUND:", clicked)
    
    # Click the GAAFET link
    clicked_chat = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('a, [role="button"], mat-list-item, div')).filter(el => 
                (el.innerText || '').includes('GAAFET') || (el.innerText || '').includes('Tranzystory')
            );
            const target = items.find(i => i.tagName === 'A' || i.getAttribute('role') === 'button' || i.closest('a'));
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
    print("CLICKED_CHAT_RESULT:", clicked_chat)
    await asyncio.sleep(3.0)
    
    # 2. Check if right Canvas is open or click on the research card to open Canvas
    canvas_info = await page.evaluate("""
        () => {
            // Check if card on left needs to be clicked to open right panel
            const researchCards = Array.from(document.querySelectorAll('div, button, [role="button"]')).filter(el => 
                (el.innerText || '').includes('Tranzystory GAAFET') || (el.innerText || '').includes('Analiza Architektury')
            );
            const clickableCard = researchCards.find(c => c.classList.contains('research-card') || c.tagName === 'BUTTON' || c.getAttribute('role') === 'button');
            if (clickableCard) {
                clickableCard.click();
            }

            // Dump all elements with substantial text length
            const textNodes = Array.from(document.querySelectorAll('*')).filter(el => {
                const len = (el.innerText || '').length;
                return len > 1000 && el.children.length <= 5;
            }).map(el => ({
                tag: el.tagName,
                className: el.className,
                len: el.innerText.length,
                textSnippet: el.innerText.slice(0, 300)
            }));

            return {
                textNodes: textNodes.slice(0, 5)
            };
        }
    """)
    print("CANVAS_INFO_AFTER_CLICK:", canvas_info)
    await asyncio.sleep(1.5)
    
    # 3. Extract the full research report text
    report = await page.evaluate("""
        async () => {
            // 1. Try 'Udostępnij i wyeksportuj' -> 'Kopiuj treść'
            const exportBtn = Array.from(document.querySelectorAll('button, div[role="button"]')).find(b => 
                (b.innerText || '').includes('Udostępnij i wyeksportuj') ||
                (b.getAttribute('aria-label') || '').includes('Udostępnij i wyeksportuj') ||
                (b.innerText || '').includes('Share & export')
            );
            if (exportBtn) {
                exportBtn.click();
                await new Promise(r => setTimeout(r, 600));
                
                const copyBtn = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item, span')).find(b => 
                    (b.innerText || '').includes('Kopiuj treść') ||
                    (b.innerText || '').includes('Copy content')
                );
                if (copyBtn) {
                    copyBtn.click();
                    await new Promise(r => setTimeout(r, 300));
                }
            }

            // 2. Extract from canvas document container
            const docElements = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], div.markdown, main, message-content')).map(el => el.innerText.trim()).filter(t => t.length > 500);
            docElements.sort((a, b) => b.length - a.length);
            return docElements.length > 0 ? docElements[0] : '';
        }
    """)
    
    print(f"\nEXTRACTED_REPORT_LENGTH: {len(report)} characters")
    if len(report) > 500:
        out_file = Path("scratch/GAAFET_Deep_Research_Report.md")
        out_file.write_text(report, encoding="utf-8")
        print(f"SUCCESS! Saved report to: {out_file.resolve()}")
        print("\n--- REPORT PREVIEW ---")
        print(report[:1500])
        print("\n...\n")
        print(report[-800:])
        
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(open_and_extract())
