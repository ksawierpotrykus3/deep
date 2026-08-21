import sys
import io
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def run_deep_research_full():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    print("Navigating to Gemini...")
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Reset conversation
    print("[1] Resetowanie czatu...")
    await mgr.reset_chat()
    await asyncio.sleep(1.0)
    
    # 2. Open tools menu
    print("[2] Otwieranie menu narzędzi (+)...")
    plus_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]').first
    await plus_btn.click()
    await asyncio.sleep(0.8)
    
    # 3. Check if Deep Research is directly visible or click 'Więcej narzędzi'
    print("[3] Aktywacja trybu Deep Research...")
    await page.evaluate("""
        () => {
            const drDirect = Array.from(document.querySelectorAll('button, [role="menuitem"], mat-list-item')).find(b => 
                (b.innerText || '').includes('Deep Research')
            );
            if (drDirect) {
                drDirect.click();
                return;
            }
            const moreBtn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.innerText || '').includes('Więcej narzędzi') || b.classList.contains('more-tools-button')
            );
            if (moreBtn) moreBtn.click();
        }
    """)
    await asyncio.sleep(0.8)
    
    # Click Deep Research item
    activated = await page.evaluate("""
        () => {
            const drBtn = Array.from(document.querySelectorAll('button, [role="menuitem"], mat-list-item')).find(b => 
                (b.innerText || '').includes('Deep Research')
            );
            if (drBtn) {
                drBtn.click();
                return true;
            }
            return false;
        }
    """)
    print("DEEP_RESEARCH_BUTTON_CLICKED:", activated)
    await asyncio.sleep(1.0)
    
    # Verify badge
    has_badge = await page.evaluate("""
        () => !!document.querySelector('.selected-item-gem-button, [aria-label*="Deep Research"], input-area-v2 .gem-button')
    """)
    print("DEEP_RESEARCH_BADGE_ACTIVE:", has_badge)
    
    # 4. Inject prompt
    research_query = "Przygotuj zwięzły, dogłębny raport na temat: Tranzystory GAAFET (Nanosheet) w węzłach 2nm i 1.4nm (TSMC N2, Intel 18A, Samsung SF2) - kluczowe innowacje fizyczne i termiczne."
    print(f"\n[4] Wprowadzanie tematu badania:\n{research_query}")
    
    await mgr._inject_prompt_to_input(research_query)
    await asyncio.sleep(0.5)
    await mgr._click_send_button()
    print("Prompt wysłany! Oczekiwanie na wygenerowanie planu badań...")
    
    # 5. Wait for "Zacznij wyszukiwanie" button to appear (up to 45s)
    print("\n[5] Oczekiwanie na plan badań i przycisk 'Zacznij wyszukiwanie'...")
    start_search_found = False
    for i in range(45):
        await asyncio.sleep(1.0)
        btn_check = await page.evaluate("""
            () => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => 
                    (b.innerText || '').includes('Zacznij wyszukiwanie') ||
                    (b.innerText || '').includes('Start research') ||
                    (b.innerText || '').includes('Start search')
                );
                return {
                    found: !!btn,
                    disabled: btn ? btn.hasAttribute('disabled') : true,
                    text: btn ? btn.innerText.trim() : ''
                };
            }
        """)
        if btn_check["found"] and not btn_check["disabled"]:
            print(f"[{i}s] Znaleziono przycisk: '{btn_check['text']}'! Klikam...")
            start_search_found = True
            break
        else:
            if (i + 1) % 5 == 0:
                print(f"[{i+1}s] Czekam na plan badań...")
                
    if not start_search_found:
        print("[BŁĄD] Nie znaleziono przycisku 'Zacznij wyszukiwanie'.")
        await mgr.close()
        return

    # Click "Zacznij wyszukiwanie"
    await page.evaluate("""
        () => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.innerText || '').includes('Zacznij wyszukiwanie') ||
                (b.innerText || '').includes('Start research') ||
                (b.innerText || '').includes('Start search')
            );
            if (btn) btn.click();
        }
    """)
    print("[6] Przycisk 'Zacznij wyszukiwanie' kliknięty! Rozpoczynam pętlę monitorowania Deep Research...")
    
    # 6. Monitor research progress & detect completion
    start_time = time.time()
    last_status_report = ""
    full_report_text = ""
    
    for i in range(120): # Up to 10 minutes (polling every 5s)
        await asyncio.sleep(5.0)
        elapsed = int(time.time() - start_time)
        
        status_info = await page.evaluate("""
            () => {
                // Check if 'Udostępnij i wyeksportuj' / 'Share & export' is visible
                const exportBtn = Array.from(document.querySelectorAll('button')).find(b => 
                    (b.innerText || '').includes('Udostępnij i wyeksportuj') ||
                    (b.innerText || '').includes('Share & export') ||
                    (b.getAttribute('aria-label') || '').includes('Udostępnij i wyeksportuj')
                );
                
                // Completed text on left chat
                const completedMessage = Array.from(document.querySelectorAll('message-content, model-response, div')).find(el => 
                    (el.innerText || '').includes("I've completed your research") ||
                    (el.innerText || '').includes("Zakończyłem badanie") ||
                    (el.innerText || '').includes("Badanie zostało zakończone")
                );

                // Progress cards / badges
                const progressNodes = Array.from(document.querySelectorAll('.research-status, .research-card, div, span, button')).filter(el => {
                    const t = el.innerText || '';
                    return t.includes('zbieranie informacji') || 
                           t.includes('Przeszukuj') || 
                           t.includes('Analizuj') || 
                           t.includes('Tworzenie raportu') ||
                           t.includes('Generuj') ||
                           t.includes('Przeszukuję');
                }).map(e => e.innerText.trim());

                // Research article content length
                const articles = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], main')).map(a => a.innerText.trim()).filter(t => t.length > 200);
                articles.sort((a, b) => b.length - a.length);

                return {
                    isCompleted: !!exportBtn || !!completedMessage,
                    hasExportButton: !!exportBtn,
                    progressSteps: progressNodes.slice(0, 3),
                    contentLength: articles.length > 0 ? articles[0].length : 0,
                    topSnippet: articles.length > 0 ? articles[0].slice(0, 150) : ''
                };
            }
        """)
        
        step_desc = ", ".join(status_info["progressSteps"][:2]) if status_info["progressSteps"] else "Praca w toku"
        print(f"[{elapsed}s] POSTĘP: {step_desc} | Długość treści w panelu: {status_info['contentLength']} zn.")
        
        if status_info["isCompleted"] or status_info["contentLength"] > 1500:
            print(f"\n[SUKCES] Wykryto zakończenie Deep Research po {elapsed}s!")
            break

    # 7. Extract the complete research report via "Udostępnij i wyeksportuj" -> "Kopiuj treść" and DOM fallback
    print("\n[7] Pobieranie pełnej treści wygenerowanego raportu...")
    await asyncio.sleep(2.0)
    
    extracted_report = await page.evaluate("""
        async () => {
            // 1. Try clicking Export -> Copy content
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

            // 2. Extract full text from right panel article container
            const containers = Array.from(document.querySelectorAll('article, .canvas-container, [role="document"], main, message-content, div.markdown')).map(el => el.innerText.trim()).filter(t => t.length > 300);
            containers.sort((a, b) => b.length - a.length);
            return containers.length > 0 ? containers[0] : '';
        }
    """)
    
    print(f"\n=======================================================")
    print(f"WYGENEROWANY RAPORT DEEP RESEARCH ({len(extracted_report)} znaków):")
    print(f"=======================================================")
    print(extracted_report[:1200] + "\n\n[... PEŁNA TREŚĆ RAPORTU ...]\n\n" + extracted_report[-600:])
    
    # Save to disk
    report_file = Path("scratch/deep_research_gaafet_full_report.md")
    report_file.write_text(extracted_report, encoding="utf-8")
    print(f"\n[PLIK] Raport zapisany na dysku: {report_file.resolve()}")
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(run_deep_research_full())
