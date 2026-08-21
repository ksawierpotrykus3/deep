import sys
import io
import json
import base64
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_live_vision():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # 1. Reset conversation
    print("[1] Resetting chat...")
    await mgr.reset_chat()
    await asyncio.sleep(1.0)
    
    # 2. Upload the user image
    img_path = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787152059776.png")
    print(f"[2] Uploading image: {img_path}...")
    uploaded = await mgr.upload_files([str(img_path.resolve())])
    print(f"Uploaded: {uploaded}")
    await asyncio.sleep(2.0)
    
    # 3. Check input area attachments
    att_info = await page.evaluate("""
        () => {
            const imgs = Array.from(document.querySelectorAll('input-area-v2 img, gem-attachment, .attachment-preview')).map(i => ({
                src: (i.getAttribute('src') || '').slice(0, 50),
                tag: i.tagName,
                className: i.className
            }));
            const sendBtnDisabled = document.querySelector('button[aria-label*="Wyślij"], button[aria-label*="Send"], button.send-button')?.hasAttribute('disabled');
            return {
                attachments: imgs,
                sendBtnDisabled
            };
        }
    """)
    print("ATTACHMENTS_IN_INPUT:", att_info)
    
    # 4. Inject prompt
    prompt = "Odczytaj dokładnie tekst z załączonego zrzutu ekranu. Wypisz: 1. Wiadomość użytkownika na samej górze. 2. Trzy punkty z sekcji 'Plan' na samym dole."
    print(f"\n[3] Injecting prompt: {prompt}...")
    await mgr._inject_prompt_to_input(prompt)
    await asyncio.sleep(0.5)
    
    # 5. Click send button
    print("[4] Submitting prompt...")
    await mgr._click_send_button()
    await asyncio.sleep(1.0)
    
    # 6. Monitor responses in DOM
    print("\n[5] Monitoring DOM response turns for 30s...")
    for i in range(15):
        await asyncio.sleep(2.0)
        dom_status = await page.evaluate("""
            () => {
                const turns = Array.from(document.querySelectorAll('message-content, model-response, .model-response-text, .response-container-content, div.markdown, .model-response, user-query, conversation-container *')).filter(el => {
                    const len = (el.innerText || '').trim().length;
                    return len > 10 && el.children.length <= 5;
                }).map(el => ({
                    tag: el.tagName,
                    className: el.className,
                    text: (el.innerText || '').trim().slice(0, 100),
                    len: (el.innerText || '').trim().length
                }));

                const stopBtn = !!document.querySelector('button[aria-label*="Stop"], button[aria-label*="Zatrzymaj"]');
                const copyBtn = !!document.querySelector('button[aria-label*="Copy"], button[aria-label*="Kopiuj"]');

                return {
                    turnsCount: turns.length,
                    turns: turns.slice(0, 5),
                    stopBtn,
                    copyBtn
                };
            }
        """)
        print(f"[{(i+1)*2}s] Turns: {dom_status['turnsCount']}, StopBtn: {dom_status['stopBtn']}, CopyBtn: {dom_status['copyBtn']}")
        for t in dom_status['turns']:
            print(f"   -> [{t['tag']}.{t['className']}] ({t['len']} chars): {t['text'][:60]}...")
            
        if dom_status['copyBtn'] and not dom_status['stopBtn'] and dom_status['turnsCount'] > 0:
            print("\n>>> GEMINI RESPONSE COMPLETED! <<<")
            break
            
    # 7. Extract final response
    final_text = await page.evaluate("""
        () => {
            const responses = Array.from(document.querySelectorAll('model-response, message-content, .model-response-text, div.markdown')).map(el => (el.innerText || '').trim()).filter(t => t.length > 50);
            return responses.length > 0 ? responses[responses.length - 1] : '';
        }
    """)
    print("\n=======================================================")
    print(f"FINAL EXTRACTED RESPONSE ({len(final_text)} chars):")
    print("=======================================================")
    print(final_text)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_live_vision())
