import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def inspect_response():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    page = mgr.page
    
    print("Navigating to Gemini...")
    await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
    await asyncio.sleep(2.0)
    
    # Check input
    await mgr._inject_prompt_to_input("Odpowiedz krotko: Co to jest 5+5?")
    await asyncio.sleep(0.5)
    await mgr._click_send_button()
    print("Prompt sent. Waiting 5s for response rendering...")
    await asyncio.sleep(5.0)
    
    # Inspect all elements in conversation area
    dom_dump = await page.evaluate("""
        () => {
            const allElements = Array.from(document.querySelectorAll('*')).map(el => ({
                tag: el.tagName,
                className: typeof el.className === 'string' ? el.className : '',
                id: el.id,
                textSnippet: (el.innerText || '').slice(0, 100),
                role: el.getAttribute('role'),
                childrenCount: el.children.length
            }));

            // Filter for elements that contain '10' or '5+5'
            const candidateNodes = allElements.filter(e => 
                (e.textSnippet.includes('10') || e.textSnippet.includes('Co to jest 5+5')) &&
                e.childrenCount <= 5
            );

            return {
                candidates: candidateNodes.slice(0, 20),
                totalNodes: allElements.length
            };
        }
    """)
    print("RESPONSE_DOM_DUMP:", dom_dump)
    
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(inspect_response())
