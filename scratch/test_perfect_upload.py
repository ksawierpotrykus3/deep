import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_perfect_upload():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    async def upload_and_ask(file_path: Path, prompt_text: str):
        print(f"\n=======================================================")
        print(f"TESTING UPLOAD FOR: {file_path.name}")
        print(f"=======================================================")
        
        # Reset chat
        await mgr.reset_chat()
        await asyncio.sleep(1.0)
        
        # 1. Open upload drawer
        upload_btn = page.locator('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"]').first
        await upload_btn.click()
        await asyncio.sleep(0.5)
        
        # 2. Click "Prześlij pliki" with file chooser interceptor
        item = page.locator('button:has-text("Prześlij pliki"), button[aria-label*="Prześlij pliki"], button.hidden-local-upload-button').first
        async with page.expect_file_chooser(timeout=5000) as fc_info:
            await item.click()
        fc = await fc_info.value
        await fc.set_files(str(file_path.resolve()))
        print(f"File {file_path.name} attached via file chooser!")
        
        # 3. Wait for attachment chip to appear in DOM
        for i in range(15):
            await asyncio.sleep(0.5)
            has_chip = await page.evaluate("""
                () => {
                    const chips = document.querySelectorAll('input-area-v2 img, rich-textarea img, .gem-attachment-style-img, file-preview, .file-chip, file-card, [data-test-id="file-attachment"]');
                    return chips.length > 0;
                }
            """)
            if has_chip:
                print(f"Attachment chip confirmed after {(i+1)*0.5}s!")
                break
                
        # 4. Inject prompt
        await mgr._inject_prompt_to_input(prompt_text)
        await asyncio.sleep(0.5)
        
        # 5. Send
        await mgr._click_send_button()
        print("Prompt and file submitted. Streaming response:")
        
        # 6. Stream
        last_len = 0
        full_resp = ""
        for _ in range(40):
            await asyncio.sleep(0.5)
            curr = await page.evaluate("""
                () => {
                    const resp = document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown, .model-response');
                    return resp.length > 0 ? (resp[resp.length - 1].innerText || '') : '';
                }
            """)
            if len(curr) > last_len:
                sys.stdout.write(curr[last_len:])
                sys.stdout.flush()
                full_resp = curr
                last_len = len(curr)
                
            is_done = await page.evaluate("""
                () => {
                    const stopBtn = document.querySelector('button[aria-label*="Zatrzymaj"], button[aria-label*="Stop"]');
                    const copyBtn = document.querySelector('button[aria-label*="Kopiuj"], button[aria-label*="Copy"]');
                    return !stopBtn && !!copyBtn;
                }
            """)
            if is_done and len(full_resp) > 20:
                break
                
        print(f"\n[DONE] Response length: {len(full_resp)} chars.")
        return full_resp

    # Test 1: Image file (.png)
    img_file = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787146308302.png")
    resp1 = await upload_and_ask(img_file, "Wymień w 2 punktach o jakich modelach jest mowa na grafice.")
    assert "Gemini 3.1 Pro" in resp1 or "3.1 Pro" in resp1, f"Expected 3.1 Pro in response, got: {resp1[:100]}"
    assert "Gemini 3.7 Flash" in resp1 or "3.7 Flash" in resp1, f"Expected 3.7 Flash in response, got: {resp1[:100]}"

    # Test 2: Source code file (.py)
    code_file = Path("scratch/sample_algorithm.py")
    resp2 = await upload_and_ask(code_file, "Jaki algorytm znajduje się w przesłanym pliku Python i jaka jest jego złożoność?")
    assert "quicksort" in resp2.lower() or "quick sort" in resp2.lower() or "sortowani" in resp2.lower(), f"Expected quicksort, got: {resp2[:100]}"

    print("\n\n>>> WSZYSTKIE TESTY PLIKÓW I SCREENÓW ZALICZONE W 100%! <<<")
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_perfect_upload())
