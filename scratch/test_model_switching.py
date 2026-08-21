import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def test_switch():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    async def switch_model_ui(target_model: str, enable_thinking: bool = True):
        print(f"\n=======================================================")
        print(f"Switching UI to: {target_model} (thinking={enable_thinking})")
        print(f"=======================================================")
        
        # 1. Open model switcher menu
        opened = await page.evaluate("""
            () => {
                const btn = document.querySelector('button.input-area-switch, button.model-switcher') || 
                            Array.from(document.querySelectorAll('button')).find(b => 
                                b.innerText.includes('Pro') || b.innerText.includes('Flash') || b.innerText.includes('Rozszerzony')
                            );
                if (btn) {
                    btn.click();
                    return { clicked: true, currentText: btn.innerText.trim() };
                }
                return { clicked: false };
            }
        """)
        print("OPEN_MENU:", opened)
        await asyncio.sleep(1.0)
        
        # 2. Select specific model
        result = await page.evaluate("""
            (args) => {
                const { targetModel, enableThinking } = args;
                const items = Array.from(document.querySelectorAll('gem-menu-item, [role="menuitem"]'));
                let modelItemClicked = false;
                let thinkingToggled = false;
                let clickedName = '';

                // Specific matchers
                let targetTag = '';
                const m = targetModel.toLowerCase();
                if (m.includes('3.7')) targetTag = '3.7';
                else if (m.includes('3.1') || m.includes('pro')) targetTag = '3.1';
                else if (m.includes('3.5') || m.includes('lite')) targetTag = '3.5';
                else targetTag = '3.7'; // default

                for (const item of items) {
                    const text = item.innerText || '';
                    if (text.includes('Myślenie')) continue;

                    if (targetTag === '3.7' && text.includes('3.7 Flash')) {
                        item.click();
                        modelItemClicked = true;
                        clickedName = text;
                        break;
                    } else if (targetTag === '3.1' && (text.includes('3.1') || text.includes('Pro'))) {
                        item.click();
                        modelItemClicked = true;
                        clickedName = text;
                        break;
                    } else if (targetTag === '3.5' && (text.includes('3.5') || text.includes('Flash-Lite'))) {
                        item.click();
                        modelItemClicked = true;
                        clickedName = text;
                        break;
                    }
                }

                // If menu closed on model selection, re-open if we need to toggle thinking
                return { modelItemClicked, clickedName };
            }
        """, {"targetModel": target_model, "enableThinking": enable_thinking})
        print("MODEL_CLICKED:", result)
        await asyncio.sleep(1.0)

        # 3. Check and toggle thinking if needed
        # Open menu again if thinking state needs verification
        btn_text = await page.evaluate("() => document.querySelector('button.input-area-switch')?.innerText.trim() || ''")
        has_thinking_in_button = 'Rozszerzony' in btn_text

        if enable_thinking != has_thinking_in_button:
            print(f"Thinking toggle needed (desired={enable_thinking}, current_has_rozszerzony={has_thinking_in_button})")
            # Open menu to toggle
            await page.evaluate("""
                () => {
                    const btn = document.querySelector('button.input-area-switch');
                    if (btn) btn.click();
                }
            """)
            await asyncio.sleep(1.0)
            await page.evaluate("""
                () => {
                    const items = Array.from(document.querySelectorAll('gem-menu-item, [role="menuitem"]'));
                    const thinkingItem = items.find(i => (i.innerText || '').includes('Myślenie rozszerzone'));
                    if (thinkingItem) thinkingItem.click();
                }
            """)
            await asyncio.sleep(1.0)

        # 4. Final check
        final_btn = await page.evaluate("() => document.querySelector('button.input-area-switch')?.innerText.trim() || ''")
        print("FINAL_BUTTON_LABEL:", final_btn)
        return final_btn

    # Test 1: Switch to 3.7 Flash Rozszerzony
    btn1 = await switch_model_ui("gemini-3.7-flash", enable_thinking=True)
    assert "Flash" in btn1 and "Rozszerzony" in btn1, f"Expected 3.7 Flash Rozszerzony, got: {btn1}"
    print("SUCCESS: 3.7 Flash Rozszerzony activated!")

    # Test 2: Switch to 3.1 Pro Rozszerzony
    btn2 = await switch_model_ui("gemini-3.1-pro", enable_thinking=True)
    assert "Pro" in btn2 and "Rozszerzony" in btn2, f"Expected 3.1 Pro Rozszerzony, got: {btn2}"
    print("SUCCESS: 3.1 Pro Rozszerzony activated!")

    await mgr.close()

if __name__ == "__main__":
    asyncio.run(test_switch())
