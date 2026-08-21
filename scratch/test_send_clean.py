import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_send():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Switch to 3.7 Flash Rozszerzony
    await mgr.switch_model_ui("gemini-3.7-flash", enable_thinking=True)
    await asyncio.sleep(1.0)
    
    # 2. Click & Type into editor
    editor = page.locator('div[role="textbox"][contenteditable="true"], .ql-editor').first
    await editor.click()
    await page.keyboard.insert_text("Napisz w jednym zdaniu: co to jest Gemini 3.7 Flash?")
    await asyncio.sleep(0.5)
    
    # 3. Click the exact send button inside input-container
    clicked = await page.evaluate("""
        () => {
            const btns = Array.from(document.querySelectorAll('input-area-v2 button, input-container button, fieldset button'));
            const sendBtn = btns.find(b => 
                (b.getAttribute('aria-label') || '').includes('Wyślij wiadomość') ||
                (b.getAttribute('aria-label') || '').includes('Send message') ||
                (b.getAttribute('aria-label') || '').includes('Wyślij') ||
                (b.getAttribute('aria-label') || '').includes('Send')
            );
            if (sendBtn && !sendBtn.hasAttribute('disabled')) {
                sendBtn.click();
                return { clicked: true, ariaLabel: sendBtn.getAttribute('aria-label') };
            }
            return { clicked: false };
        }
    """)
    print("SEND_BUTTON_CLICK_RESULT:", clicked)
    if not clicked.get("clicked"):
        # Fallback: Enter key
        print("Falling back to keyboard Enter press...")
        await page.keyboard.press("Enter")

    # 4. Wait and observe response streaming in real time
    print("\nWaiting for response from Gemini 3.7 Flash (Rozszerzone)...")
    last_len = 0
    full_resp = ""
    for i in range(40):
        await asyncio.sleep(1.0)
        curr_text = await page.evaluate("""
            () => {
                // Find latest response container
                const resp = document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown, .model-response');
                if (resp.length > 0) {
                    return resp[resp.length - 1].innerText || '';
                }
                return '';
            }
        """)
        if len(curr_text) > last_len:
            delta = curr_text[last_len:]
            sys.stdout.write(delta)
            sys.stdout.flush()
            full_resp = curr_text
            last_len = len(curr_text)
            
        # Check if done
        is_done = await page.evaluate("""
            () => {
                const stopBtn = document.querySelector('button[aria-label*="Zatrzymaj"], button[aria-label*="Stop"]');
                const copyBtn = document.querySelector('button[aria-label*="Kopiuj"], button[aria-label*="Copy"]');
                return !stopBtn && !!copyBtn;
            }
        """)
        if is_done and len(full_resp) > 10:
            print("\n\n[INFO] Response completed successfully!")
            break

    print(f"\nFINAL_RESPONSE (Length: {len(full_resp)} chars):")
    print(full_resp)
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_send())
