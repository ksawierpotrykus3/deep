import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_deep_research_flow():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    print("Navigating to Gemini...")
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Reset conversation
    await mgr.reset_chat()
    await asyncio.sleep(1.0)
    
    print("=" * 60)
    print("KROK 1: WŁĄCZENIE TRYBU DEEP RESEARCH")
    print("=" * 60)
    
    # Open tools menu (+ button)
    upload_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]').first
    await upload_btn.click()
    await asyncio.sleep(0.6)
    
    # Click "Deep Research" item
    clicked_dr = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item, gem-menu-item')).filter(el => 
                (el.innerText || '').includes('Deep Research') ||
                (el.getAttribute('aria-label') || '').includes('Deep Research')
            );
            if (items.length > 0) {
                items[0].click();
                return { success: true, text: items[0].innerText.trim() };
            }
            return { success: false };
        }
    """)
    print("CLICK_DEEP_RESEARCH_RESULT:", clicked_dr)
    await asyncio.sleep(1.0)
    
    # Verify Deep Research badge in input area
    has_dr_badge = await page.evaluate("""
        () => {
            const badge = Array.from(document.querySelectorAll('input-area-v2 *, input-container *')).find(el => 
                (el.innerText || '').includes('Deep Research')
            );
            return !!badge;
        }
    """)
    print("DEEP_RESEARCH_BADGE_ACTIVE:", has_dr_badge)
    
    print("\n" + "=" * 60)
    print("KROK 2: WPISANIE TEMATU BADAWCZEGO I WYSŁANIE")
    print("=" * 60)
    
    research_topic = "Porównanie technologii tranzystorów GAAFET (Nanosheet) z FinFET w węzłach 2nm i 1.4nm (TSMC N2, Intel 18A, Samsung SF2): architektura, upływ prądu i wydajność."
    print(f"Topic: {research_topic}")
    
    await mgr._inject_prompt_to_input(research_topic)
    await asyncio.sleep(0.5)
    await mgr._click_send_button()
    print("Prompt submitted! Waiting for research plan generation...")
    
    print("\n" + "=" * 60)
    print("KROK 3: OCZEKIWANIE NA PLAN BADAŃ I PRZYCISK 'ZACZNIJ WYSZUKIWANIE'")
    print("=" * 60)
    
    # Wait for "Zacznij wyszukiwanie" button to appear (up to 45s)
    plan_found = False
    for i in range(45):
        await asyncio.sleep(1.0)
        btn_info = await page.evaluate("""
            () => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => 
                    (b.innerText || '').includes('Zacznij wyszukiwanie') ||
                    (b.innerText || '').includes('Start research') ||
                    (b.innerText || '').includes('Start search')
                );
                if (btn) {
                    return {
                        found: true,
                        text: btn.innerText.trim(),
                        disabled: btn.hasAttribute('disabled')
                    };
                }
                const planText = Array.from(document.querySelectorAll('message-content, model-response, div')).find(d => 
                    (d.innerText || '').includes('Oto ułożony plan działania') ||
                    (d.innerText || '').includes('Generuję plan badań')
                );
                return {
                    found: false,
                    statusText: planText ? planText.innerText.slice(0, 100) : ''
                };
            }
        """)
        print(f"[{i}s] PLAN STATUS: {btn_info}")
        if btn_info.get("found") and not btn_info.get("disabled"):
            print("Found 'Zacznij wyszukiwanie' button!")
            plan_found = True
            break
            
    if not plan_found:
        print("Timeout waiting for 'Zacznij wyszukiwanie' button.")
        await mgr.close()
        return

    print("\n" + "=" * 60)
    print("KROK 4: KLIKNIĘCIE 'ZACZNIJ WYSZUKIWANIE'")
    print("=" * 60)
    
    clicked_start = await page.evaluate("""
        () => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.innerText || '').includes('Zacznij wyszukiwanie') ||
                (b.innerText || '').includes('Start research') ||
                (b.innerText || '').includes('Start search')
            );
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }
    """)
    print("CLICKED_START_SEARCH:", clicked_start)
    
    print("\n" + "=" * 60)
    print("KROK 5: ŚLEDZENIE POSTĘPU DEEP RESEARCH")
    print("=" * 60)
    
    # Poll progress and detect completion
    for i in range(120):  # Poll every 3s for up to 6 minutes
        await asyncio.sleep(3.0)
        
        status = await page.evaluate("""
            () => {
                // Check if completed (Export button or completed message)
                const exportBtn = Array.from(document.querySelectorAll('button')).find(b => 
                    (b.innerText || '').includes('Udostępnij i wyeksportuj') ||
                    (b.innerText || '').includes('Share & export') ||
                    (b.getAttribute('aria-label') || '').includes('Udostępnij i wyeksportuj')
                );
                
                // Check current progress status text in badge / card
                const progressNodes = Array.from(document.querySelectorAll('.research-status, .research-card, div, span, button')).filter(el => {
                    const t = el.innerText || '';
                    return t.includes('zbieranie informacji') || 
                           t.includes('Przeszukuję') || 
                           t.includes('Analizuję') || 
                           t.includes('Generuję raport') ||
                           t.includes('I completed your research') ||
                           t.includes('completed your research');
                }).map(e => e.innerText.trim());

                // Check right panel / canvas article
                const canvasText = Array.from(document.querySelectorAll('article, .canvas-container, .research-content, main')).map(c => c.innerText.trim()).filter(t => t.length > 100);

                // Check errors
                const errorBanner = document.querySelector('.error-banner, [role="alert"], div.safety-block');

                return {
                    isCompleted: !!exportBtn,
                    progressSteps: progressNodes.slice(0, 3),
                    hasCanvasContent: canvasText.length > 0,
                    canvasLength: canvasText.length > 0 ? canvasText[0].length : 0,
                    errorText: errorBanner ? errorBanner.innerText : null
                };
            }
        """)
        
        print(f"[{(i+1)*3}s] STATUS: completed={status['isCompleted']}, canvasLength={status['canvasLength']}, steps={status['progressSteps']}")
        
        if status.get("isCompleted") or status.get("canvasLength", 0) > 1000:
            print("\n>>> DEEP RESEARCH UKOŃCZONE POMYŚLNIE! <<<")
            break
            
        if status.get("errorText"):
            print(f"\n[BŁĄD GEMINI]: {status['errorText']}")
            break

    print("\n" + "=" * 60)
    print("KROK 6: POBRANIE PEŁNEGO RAPORTU BADAWCZEGO")
    print("=" * 60)
    
    # Try export menu -> Kopiuj treść
    copied_content = await page.evaluate("""
        async () => {
            // Click 'Udostępnij i wyeksportuj'
            const exportBtn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.innerText || '').includes('Udostępnij i wyeksportuj') ||
                (b.innerText || '').includes('Share & export') ||
                (b.getAttribute('aria-label') || '').includes('Udostępnij i wyeksportuj')
            );
            if (exportBtn) {
                exportBtn.click();
                await new Promise(r => setTimeout(r, 600));
                
                const copyBtn = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item')).find(b => 
                    (b.innerText || '').includes('Kopiuj treść') ||
                    (b.innerText || '').includes('Copy content')
                );
                if (copyBtn) {
                    copyBtn.click();
                }
            }

            // Also extract direct text from canvas / article elements
            const articles = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], main, message-content, div.markdown')).map(a => a.innerText.trim()).filter(t => t.length > 500);
            
            // Sort by longest text content
            articles.sort((a, b) => b.length - a.length);
            return articles.length > 0 ? articles[0] : '';
        }
    """)
    
    print(f"\nPOBRANA TREŚĆ RAPORTU (Długość: {len(copied_content)} znaków):")
    print(copied_content[:1000] + "\n...\n" + copied_content[-500:])
    
    # Save report to file
    out_file = Path("scratch/deep_research_gaafet_report.md")
    out_file.write_text(copied_content, encoding="utf-8")
    print(f"\nRaport zapisano do pliku: {out_file.resolve()}")
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_deep_research_flow())
