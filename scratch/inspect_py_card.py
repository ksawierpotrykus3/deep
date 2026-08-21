import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_code_card():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    code_file = Path("scratch/sample_algorithm.py")
    
    # Open upload drawer
    upload_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"]').first
    await upload_btn.click()
    await asyncio.sleep(0.5)
    
    item = page.locator('button:has-text("Prześlij pliki"), button[aria-label*="Prześlij pliki"], button.hidden-local-upload-button').first
    async with page.expect_file_chooser(timeout=5000) as fc_info:
        await item.click()
    fc = await fc_info.value
    await fc.set_files(str(code_file.resolve()))
    print("Code file set in file chooser.")
    
    await asyncio.sleep(2.0)
    
    # Dump all elements in input-area-v2 and dialogs
    dom_info = await page.evaluate("""
        () => {
            const inputArea = document.querySelector('input-area-v2') || document.querySelector('input-container');
            const dialogs = Array.from(document.querySelectorAll('mat-dialog-container, .cdk-overlay-pane, .error-banner, [role="alert"]')).map(d => ({
                text: d.innerText.trim(),
                className: d.className
            }));
            const fileCards = Array.from(document.querySelectorAll('input-area-v2 *')).map(el => ({
                tag: el.tagName,
                className: el.className,
                text: el.innerText ? el.innerText.slice(0, 100) : '',
                ariaLabel: el.getAttribute('aria-label') || ''
            })).filter(e => e.text.includes('sample') || e.text.includes('py') || e.ariaLabel.includes('sample'));

            const sendBtn = Array.from(document.querySelectorAll('input-area-v2 button, input-container button')).find(b => 
                (b.getAttribute('aria-label') || '').includes('Wyślij')
            );

            return {
                dialogs,
                fileCards,
                sendBtnDisabled: sendBtn ? sendBtn.hasAttribute('disabled') : 'NO_BTN',
                sendBtnClasses: sendBtn ? sendBtn.className : ''
            };
        }
    """)
    print("DOM_INFO_AFTER_CODE_UPLOAD:", dom_info)
    
    # Try typing prompt
    await mgr._inject_prompt_to_input("Wyjaśnij co robi ten kod.")
    await asyncio.sleep(1.0)
    
    # Check send button again
    send_check = await page.evaluate("""
        () => {
            const sendBtn = Array.from(document.querySelectorAll('input-area-v2 button, input-container button')).find(b => 
                (b.getAttribute('aria-label') || '').includes('Wyślij')
            );
            return {
                disabled: sendBtn ? sendBtn.hasAttribute('disabled') : 'NO_BTN',
                ariaLabel: sendBtn ? sendBtn.getAttribute('aria-label') : ''
            };
        }
    """)
    print("SEND_BTN_CHECK_AFTER_TYPING:", send_check)
    
    # Click send
    await mgr._click_send_button()
    print("Send button clicked!")
    
    # Observe response
    for i in range(15):
        await asyncio.sleep(1.0)
        resp = await page.evaluate("""
            () => {
                const resp = document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown, .model-response');
                return resp.length > 0 ? resp[resp.length - 1].innerText : '';
            }
        """)
        print(f"[{i}s] RESP ({len(resp)} chars): {resp[:100]}...")
        if len(resp) > 20:
            break

    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_code_card())
