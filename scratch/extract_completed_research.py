import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def extract_research():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    print("Navigating to Gemini...")
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.5)
    
    # 1. Inspect recent chats / click the GAAFET Deep Research conversation if needed
    print("Checking current page state...")
    
    # Check if the right panel is currently open
    panel_info = await page.evaluate("""
        () => {
            // Find all buttons on page
            const allButtons = Array.from(document.querySelectorAll('button, [role="button"], mat-icon-button, gem-button')).map(b => ({
                text: b.innerText.trim(),
                ariaLabel: b.getAttribute('aria-label') || '',
                tag: b.tagName,
                className: b.className
            })).filter(b => b.text.length > 0 || b.ariaLabel.length > 0);

            // Find all large text containers
            const textContainers = Array.from(document.querySelectorAll('*')).filter(el => {
                const len = (el.innerText || '').length;
                return len > 1000 && el.children.length <= 15;
            }).map(el => ({
                tag: el.tagName,
                className: el.className,
                id: el.id,
                textLength: el.innerText.length,
                snippet: el.innerText.slice(0, 200)
            }));

            return {
                buttons: allButtons.filter(b => 
                    b.text.includes('Udostępnij') || 
                    b.text.includes('Spis treści') || 
                    b.text.includes('Utwórz') || 
                    b.text.includes('Kopiuj') ||
                    b.text.includes('GAAFET') ||
                    b.ariaLabel.includes('Udostępnij') ||
                    b.ariaLabel.includes('GAAFET')
                ),
                textContainers: textContainers.slice(0, 10)
            };
        }
    """)
    print("PANEL_AND_BUTTON_INFO:", panel_info)
    
    # If the conversation needs to be opened from history
    if len(panel_info["textContainers"]) == 0:
        print("Looking for GAAFET chat in sidebar history...")
        opened_chat = await page.evaluate("""
            () => {
                const historyLinks = Array.from(document.querySelectorAll('a, [role="button"], mat-list-item')).filter(el => 
                    (el.innerText || '').includes('GAAFET') || (el.innerText || '').includes('Tranzystory')
                );
                if (historyLinks.length > 0) {
                    historyLinks[0].click();
                    return { clicked: true, text: historyLinks[0].innerText };
                }
                return { clicked: false };
            }
        """)
        print("OPENED_CHAT_FROM_SIDEBAR:", opened_chat)
        await asyncio.sleep(3.0)

    # 2. Extract full research report
    report_data = await page.evaluate("""
        async () => {
            // Click 'Udostępnij i wyeksportuj'
            const allBtns = Array.from(document.querySelectorAll('button, div[role="button"]'));
            const exportBtn = allBtns.find(b => 
                (b.innerText || '').includes('Udostępnij i wyeksportuj') ||
                (b.getAttribute('aria-label') || '').includes('Udostępnij i wyeksportuj') ||
                (b.innerText || '').includes('Share & export')
            );
            
            let exportClicked = false;
            let copyClicked = false;
            if (exportBtn) {
                exportBtn.click();
                exportClicked = true;
                await new Promise(r => setTimeout(r, 600));

                const copyBtn = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item, span')).find(b => 
                    (b.innerText || '').includes('Kopiuj treść') ||
                    (b.innerText || '').includes('Copy content')
                );
                if (copyBtn) {
                    copyBtn.click();
                    copyClicked = true;
                }
            }

            // Extract the longest document / article text
            const articles = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], main, .model-response, message-content, div.markdown')).map(el => ({
                text: el.innerText.trim(),
                tag: el.tagName,
                className: el.className,
                len: el.innerText.trim().length
            })).filter(a => a.len > 500);

            articles.sort((a, b) => b.len - a.len);

            return {
                exportClicked,
                copyClicked,
                longestContentLength: articles.length > 0 ? articles[0].len : 0,
                fullContent: articles.length > 0 ? articles[0].text : '',
                allArticlesFound: articles.map(a => ({ tag: a.tag, className: a.className, len: a.len }))
            };
        }
    """)
    
    print("\nREPORT_EXTRACTION_RESULT:")
    print("Export clicked:", report_data.get("exportClicked"))
    print("Copy clicked:", report_data.get("copyClicked"))
    print("Articles found:", report_data.get("allArticlesFound"))
    print("Longest content length:", report_data.get("longestContentLength"))
    
    full_text = report_data.get("fullContent", "")
    if len(full_text) > 500:
        out_file = Path("scratch/GAAFET_Deep_Research_Report.md")
        out_file.write_text(full_text, encoding="utf-8")
        print(f"\n[SUKCES] Pełny raport Deep Research ({len(full_text)} znaków) zapisany w: {out_file.resolve()}")
        print("\n--- POCZĄTEK RAPORTU ---")
        print(full_text[:1500])
        print("\n...\n")
        print("--- KONIEC RAPORTU ---")
        print(full_text[-800:])
    else:
        print("[OSTRZEŻENIE] Nie znaleziono treści dłuższego raportu.")
        
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(extract_research())
