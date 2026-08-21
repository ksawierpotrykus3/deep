import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_sub():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Switch to 3.7 Flash
    await mgr.switch_model_ui("gemini-3.7-flash", enable_thinking=True)
    await asyncio.sleep(1.0)
    
    # 2. Focus editor & type
    editor = page.locator('div[role="textbox"], .ql-editor, textarea').first
    await editor.click()
    await page.keyboard.insert_text("Napisz w 1 zdaniu co oznacza Gemini 3.7 Flash z myśleniem rozszerzonym.")
    await asyncio.sleep(0.5)
    
    # 3. Click Send
    send_btn = page.locator('button[aria-label*="Wyślij"], button[aria-label*="Send"]').first
    await send_btn.click()
    print("SEND BUTTON CLICKED!")
    
    # 4. Wait and observe response chunks
    for i in range(25):
        await asyncio.sleep(1.0)
        resp_text = await page.evaluate("""
            () => {
                // Find all model response containers
                const containers = document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown');
                if (containers.length > 0) {
                    return containers[containers.length - 1].innerText;
                }
                // Fallback: search main chat area
                const chatWin = document.querySelector('chat-window');
                return chatWin ? chatWin.innerText.slice(0, 500) : 'NO_CHAT_WIN';
            }
        """)
        print(f"[{i}s] RESP_TEXT:\n{resp_text}\n---")
        if "Gemini" in resp_text or "Flash" in resp_text or len(resp_text) > 20:
            print("GENERATION DETECTED!")
            break
            
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_sub())
