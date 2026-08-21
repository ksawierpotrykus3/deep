import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_uploads():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    print("=" * 60)
    print("1. INSPEKCJA PRZYCISKU UPLOAD / NARZĘDZIA")
    print("=" * 60)
    
    # Locate upload trigger button in input container
    upload_btn_info = await page.evaluate("""
        () => {
            const btns = Array.from(document.querySelectorAll('input-area-v2 button, input-container button, fieldset button, button')).map(b => ({
                ariaLabel: b.getAttribute('aria-label') || '',
                className: b.className,
                tag: b.tagName,
                text: b.innerText.trim()
            })).filter(b => 
                b.ariaLabel.includes('Przesyłanie') || 
                b.ariaLabel.includes('narzędzia') || 
                b.ariaLabel.includes('Upload') ||
                b.ariaLabel.includes('Dodaj') ||
                b.ariaLabel.includes('Plik')
            );
            return btns;
        }
    """)
    print("UPLOAD_BUTTONS_FOUND:", upload_btn_info)
    
    print("\n" + "=" * 60)
    print("2. KLIKNIĘCIE PRZYCISKU PRZESYŁANIA I SPRAWDZENIE MENU")
    print("=" * 60)
    
    # Click upload button
    await page.evaluate("""
        () => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => 
                (b.getAttribute('aria-label') || '').includes('Przesyłanie') ||
                (b.getAttribute('aria-label') || '').includes('Upload') ||
                (b.getAttribute('aria-label') || '').includes('narzędzia')
            );
            if (btn) btn.click();
        }
    """)
    await asyncio.sleep(1.0)
    
    # Inspect menu items that opened
    menu_items = await page.evaluate("""
        () => {
            const items = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item, gem-menu-item, a')).map(el => ({
                text: el.innerText.trim(),
                ariaLabel: el.getAttribute('aria-label') || '',
                className: el.className,
                tag: el.tagName
            })).filter(i => i.text.length > 0 || i.ariaLabel.length > 0);
            return items.slice(0, 25);
        }
    """)
    print("MENU_ITEMS_AFTER_UPLOAD_CLICK:", menu_items)
    
    print("\n" + "=" * 60)
    print("3. SPRAWDZENIE METODY EXPECT_FILE_CHOOSER (PLAYWRIGHT)")
    print("=" * 60)
    
    test_image = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787146308302.png")
    
    # Test expect_file_chooser
    try:
        async with page.expect_file_chooser(timeout=5000) as fc_info:
            # Click "Prześlij pliki" or file input trigger
            await page.evaluate("""
                () => {
                    const item = Array.from(document.querySelectorAll('button, [role="menuitem"], .mat-mdc-menu-item')).find(el => 
                        (el.innerText || '').includes('Prześlij') ||
                        (el.innerText || '').includes('plik') ||
                        (el.innerText || '').includes('Upload') ||
                        (el.getAttribute('aria-label') || '').includes('Prześlij')
                    );
                    if (item) item.click();
                    else {
                        // Fallback click main upload btn
                        const btn = document.querySelector('button[aria-label*="Przesyłanie"]');
                        if (btn) btn.click();
                    }
                }
            """)
        file_chooser = await fc_info.value
        print(f"FILE_CHOOSER_INTERCEPTED! is_multiple={file_chooser.is_multiple()}")
        await file_chooser.set_files(str(test_image.resolve()))
        print("SET_FILES_VIA_FILE_CHOOSER: SUCCESS!")
    except Exception as e:
        print(f"FILE_CHOOSER_NOTE: {e}")
        # Try direct input[type="file"]
        has_file_input = await page.evaluate("() => !!document.querySelector('input[type=\"file\"]')")
        print(f"DIRECT_FILE_INPUT_EXISTS: {has_file_input}")
        if has_file_input:
            await page.set_input_files('input[type="file"]', str(test_image.resolve()))
            print("SET_INPUT_FILES: SUCCESS!")

    # Wait and check attachment chips
    await asyncio.sleep(3.0)
    attachments = await page.evaluate("""
        () => {
            const chips = Array.from(document.querySelectorAll('input-area-v2 img, rich-textarea img, .gem-attachment-style-img, file-preview, .file-chip')).map(el => ({
                tag: el.tagName,
                src: el.getAttribute('src') || '',
                className: el.className
            }));
            return chips;
        }
    """)
    print("CONFIRMED_ATTACHMENTS_IN_DOM:", attachments)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_uploads())
