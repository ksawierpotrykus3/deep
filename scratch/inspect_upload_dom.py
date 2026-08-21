import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_upload():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Inspect file inputs
    file_inputs = await page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map(i => ({
                id: i.id,
                className: i.className,
                accept: i.getAttribute('accept'),
                multiple: i.hasAttribute('multiple'),
                outerHTML: i.outerHTML.slice(0, 150)
            }));
            return inputs;
        }
    """)
    print("FILE_INPUTS_FOUND:", file_inputs)
    
    test_image = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787146308302.png")
    print(f"Testing upload of: {test_image} (exists={test_image.exists()})")
    
    # Upload file
    if len(file_inputs) > 0:
        await page.set_input_files('input[type="file"]', str(test_image.resolve()))
        print("SET_INPUT_FILES executed successfully!")
    else:
        # Click upload button to trigger file input
        print("No hidden file input found, clicking upload trigger button...")
        await page.evaluate("""
            () => {
                const btn = document.querySelector('button[aria-label*="Przesyłanie"], button[aria-label*="Upload"], button[aria-label*="Dodaj pliki"]');
                if (btn) btn.click();
            }
        """)
        await asyncio.sleep(1.0)
        await page.set_input_files('input[type="file"]', str(test_image.resolve()))

    # Wait for image thumbnail to upload and be attached
    print("Waiting 4s for image attachment chip to render...")
    await asyncio.sleep(4.0)
    
    attachment_info = await page.evaluate("""
        () => {
            const chips = Array.from(document.querySelectorAll('file-preview, image-preview, .thumbnail, mat-chip, .uploader-preview, input-area-v2 img, rich-textarea img, .file-chip')).map(el => ({
                tag: el.tagName,
                className: el.className,
                src: (el.querySelector('img') || el).getAttribute('src') || '',
                text: el.innerText.slice(0, 50)
            }));
            return chips;
        }
    """)
    print("ATTACHMENTS_IN_DOM:", attachment_info)
    
    # Type prompt
    await mgr._inject_prompt_to_input("Dokonaj szczegółowej analizy tego zrzutu ekranu. Co przedstawia punkt 1, a co punkt 2?")
    await asyncio.sleep(1.0)
    
    # Click Send
    await mgr._click_send_button()
    print("Prompt and image sent! Waiting for response...")
    
    # Receive response stream
    last_len = 0
    full_resp = ""
    for i in range(45):
        await asyncio.sleep(1.0)
        curr_text = await page.evaluate("""
            () => {
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
            
        is_done = await page.evaluate("""
            () => {
                const stopBtn = document.querySelector('button[aria-label*="Zatrzymaj"], button[aria-label*="Stop"]');
                const copyBtn = document.querySelector('button[aria-label*="Kopiuj"], button[aria-label*="Copy"]');
                return !stopBtn && !!copyBtn;
            }
        """)
        if is_done and len(full_resp) > 20:
            print("\n\n[INFO] Vision analysis completed successfully!")
            break
            
    print(f"\nFINAL_VISION_RESPONSE:\n{full_resp}")
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_upload())
