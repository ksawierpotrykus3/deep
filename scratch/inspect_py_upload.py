import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_code_upload():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    sample_file = Path("scratch/sample_algorithm.py")
    print(f"Uploading file: {sample_file.resolve()}")
    
    # Use file chooser
    async with page.expect_file_chooser(timeout=5000) as fc_info:
        await page.evaluate("""
            () => {
                const btn = document.querySelector('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]');
                if (btn) btn.click();
                setTimeout(() => {
                    const item = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item')).find(el => 
                        (el.innerText || '').includes('Prześlij') ||
                        (el.innerText || '').includes('plik') ||
                        (el.innerText || '').includes('Upload')
                    );
                    if (item) item.click();
                }, 200);
            }
        """)
    fc = await fc_info.value
    await fc.set_files(str(sample_file.resolve()))
    print("Files set in file chooser.")
    
    # Observe DOM changes around attachment & send button over next 10 seconds
    for i in range(10):
        await asyncio.sleep(1.0)
        dom_status = await page.evaluate("""
            () => {
                const chips = Array.from(document.querySelectorAll('input-area-v2 img, rich-textarea img, .gem-attachment-style-img, file-preview, .file-chip, .upload-progress, mat-progress-bar, mat-spinner')).map(el => ({
                    tag: el.tagName,
                    className: el.className,
                    text: el.innerText ? el.innerText.slice(0, 50) : ''
                }));
                const sendBtn = Array.from(document.querySelectorAll('input-area-v2 button, input-container button, fieldset button')).find(b => 
                    (b.getAttribute('aria-label') || '').includes('Wyślij')
                );
                return {
                    chips,
                    sendBtnDisabled: sendBtn ? sendBtn.hasAttribute('disabled') : 'NO_BTN',
                    sendBtnLabel: sendBtn ? sendBtn.getAttribute('aria-label') : ''
                };
            }
        """)
        print(f"[{i}s] STATUS:", dom_status)

    # Now type prompt and send
    await mgr._inject_prompt_to_input("Przeanalizuj ten kod quicksorta.")
    await asyncio.sleep(1.0)
    await mgr._click_send_button()
    print("Send button clicked!")
    
    # Observe response
    for i in range(20):
        await asyncio.sleep(1.0)
        resp = await page.evaluate("""
            () => {
                const resp = document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown, .model-response');
                return resp.length > 0 ? resp[resp.length - 1].innerText : '';
            }
        """)
        print(f"[{i}s] RESP ({len(resp)} chars): {resp[:80]}...")
        if len(resp) > 20:
            break

    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_code_upload())
