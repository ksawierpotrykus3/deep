import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def extract_canvas_doc():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    # Direct navigation to the GAAFET research conversation
    target_url = "https://gemini.google.com/app/7b0b7cab2ff7d848"
    print(f"Navigating directly to research session: {target_url}...")
    await page.goto(target_url, wait_until="domcontentloaded")
    await asyncio.sleep(4.0)
    
    # 1. Click on the research card in the chat to ensure Canvas opens on the right
    print("Ensuring Canvas panel is active...")
    card_clicked = await page.evaluate("""
        () => {
            const card = Array.from(document.querySelectorAll('div, button, [role="button"]')).find(el => 
                (el.innerText || '').includes('Zaawansowana Analiza Tranzystorów') ||
                (el.innerText || '').includes('Analiza Architektury i Fizyki') ||
                (el.innerText || '').includes('Tranzystory GAAFET 2nm')
            );
            if (card) {
                card.click();
                return { clicked: true, text: card.innerText.slice(0, 50) };
            }
            return { clicked: false };
        }
    """)
    print("RESEARCH_CARD_CLICKED:", card_clicked)
    await asyncio.sleep(2.0)
    
    # 2. Click 'Udostępnij i wyeksportuj' -> 'Kopiuj treść'
    export_result = await page.evaluate("""
        async () => {
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
                    return { success: true, method: 'copy_menu' };
                }
                return { success: true, method: 'export_btn_clicked' };
            }
            return { success: false };
        }
    """)
    print("EXPORT_MENU_RESULT:", export_result)
    await asyncio.sleep(1.0)
    
    # 3. Extract text from the canvas document DOM
    canvas_text = await page.evaluate("""
        () => {
            // Find right side canvas container
            const canvasContainers = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], gem-canvas, .document-editor, .canvas-body, main *')).filter(el => {
                const text = el.innerText || '';
                return text.includes('Ewolucja architektura tranzystorowej') ||
                       text.includes('Od FinFET do GAAFET') ||
                       text.includes('Architektura i fizyka tranzystorów') ||
                       text.includes('Fizyka Urządzeń');
            });

            if (canvasContainers.length > 0) {
                // Find top parent
                canvasContainers.sort((a, b) => b.innerText.length - a.innerText.length);
                return canvasContainers[0].innerText.trim();
            }

            // Fallback: largest document body
            const allBlocks = Array.from(document.querySelectorAll('*')).filter(el => (el.innerText || '').length > 2000 && el.children.length <= 10);
            allBlocks.sort((a, b) => b.innerText.length - a.innerText.length);
            return allBlocks.length > 0 ? allBlocks[0].innerText.trim() : '';
        }
    """)
    
    print(f"\nCANVAS_DOCUMENT_LENGTH: {len(canvas_text)} characters")
    
    if len(canvas_text) > 1000:
        out_doc = Path("scratch/GAAFET_Deep_Research_Document.md")
        out_doc.write_text(canvas_text, encoding="utf-8")
        print(f"\n[SUKCES] Zapisano sformatowany dokument badania w:\n{out_doc.resolve()}")
        print("\n==================== PRZEGLĄD DOKUMENTU ====================")
        print(canvas_text[:2000])
        print("\n...\n")
        print(canvas_text[-1000:])
    else:
        print("Canvas text extraction fallback...")
        
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(extract_canvas_doc())
