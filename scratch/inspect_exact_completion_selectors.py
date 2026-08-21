import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_completion_selectors():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    target_url = "https://gemini.google.com/app/7b0b7cab2ff7d848"
    print(f"Loading completed research URL: {target_url}...")
    await page.goto(target_url, wait_until="domcontentloaded")
    await asyncio.sleep(4.0)
    
    # Deep DOM inspection of all possible completion indicators
    selectors_check = await page.evaluate("""
        () => {
            // 1. All buttons anywhere in document, shadow roots, headers
            const allButtons = Array.from(document.querySelectorAll('*')).filter(el => 
                el.tagName === 'BUTTON' || 
                el.getAttribute('role') === 'button' ||
                el.classList.contains('mat-mdc-button-base') ||
                el.classList.contains('gem-button')
            ).map(b => ({
                tag: b.tagName,
                text: b.innerText ? b.innerText.trim() : '',
                ariaLabel: b.getAttribute('aria-label') || '',
                className: b.className,
                id: b.id,
                role: b.getAttribute('role')
            }));

            // 2. Filter buttons related to Export, Share, Content
            const exportBtns = allButtons.filter(b => 
                b.text.includes('Udostępnij') ||
                b.text.includes('wyeksportuj') ||
                b.text.includes('Share') ||
                b.text.includes('export') ||
                b.text.includes('Spis') ||
                b.text.includes('Utwórz') ||
                b.ariaLabel.includes('Udostępnij') ||
                b.ariaLabel.includes('wyeksportuj') ||
                b.ariaLabel.includes('Share')
            );

            // 3. Check for chat messages
            const chatMessages = Array.from(document.querySelectorAll('message-content, model-response, div.model-response-text, .response-container-content, div')).map(el => el.innerText ? el.innerText.trim() : '').filter(t => 
                t.includes("completed your research") ||
                t.includes("ukończone") ||
                t.includes("Zakończyłem") ||
                t.includes("Feel free to ask")
            );

            // 4. Check for active progress spinners/indicators
            const spinners = Array.from(document.querySelectorAll('mat-progress-bar, mat-spinner, .spinner, [role="progressbar"], .loading')).map(s => ({
                tag: s.tagName,
                className: s.className,
                visible: s.offsetParent !== null
            }));

            // 5. Canvas container inspection
            const canvasNodes = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], gem-canvas, .document-editor, .canvas-body, main *')).filter(el => {
                const text = el.innerText || '';
                return text.includes('Ewolucja architektura tranzystorowej') ||
                       text.includes('Od FinFET do GAAFET') ||
                       text.includes('Architektura i fizyka tranzystorów');
            }).map(el => ({
                tag: el.tagName,
                className: el.className,
                textLength: el.innerText.length,
                selector: el.tagName.toLowerCase() + (el.className ? '.' + el.className.split(' ').join('.') : '')
            }));

            return {
                totalButtonsFound: allButtons.length,
                exportButtons: exportBtns,
                chatMessagesFound: chatMessages.slice(0, 3),
                spinnersFound: spinners,
                canvasNodes: canvasNodes.slice(0, 5)
            };
        }
    """)
    
    print("================================================================================")
    print("ANALIZA SELECTORÓW W ZAKOŃCZONYM BADANIU DEEP RESEARCH:")
    print("================================================================================")
    print(f"Total Buttons: {selectors_check['totalButtonsFound']}")
    print("\n[EXPORT / SHARE BUTTONS]:")
    for b in selectors_check['exportButtons']:
        print("  ->", b)
        
    print("\n[COMPLETED CHAT MESSAGES]:")
    for m in selectors_check['chatMessagesFound']:
        print("  ->", repr(m[:100]))
        
    print("\n[ACTIVE SPINNERS]:", selectors_check['spinnersFound'])
    
    print("\n[CANVAS NODES]:")
    for c in selectors_check['canvasNodes']:
        print("  ->", c)
        
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_completion_selectors())
