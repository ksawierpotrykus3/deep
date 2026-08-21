import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import asyncio
from gemini_proxy.gemini_browser import GeminiBrowserManager

async def main():
    mgr = GeminiBrowserManager(headless=True)
    await mgr.start()
    
    dom_info = await mgr.page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('div[role="textbox"], rich-textarea, .ql-editor, textarea')).map(e => e.outerHTML.slice(0, 100));
            const signIns = Array.from(document.querySelectorAll('a[href*="accounts.google.com"], button[aria-label*="Sign in"], button[aria-label*="Zaloguj"], a[data-g-label*="Sign in"]')).map(e => e.outerHTML.slice(0, 100));
            const avatars = Array.from(document.querySelectorAll('a[aria-label*="Google Account"], a[aria-label*="Konto Google"], img[alt*="Google Account"], img[alt*="Konto Google"]')).map(e => e.outerHTML.slice(0, 100));
            return {
                title: document.title,
                url: window.location.href,
                inputs,
                signIns,
                avatars,
                bodyText: document.body.innerText.slice(0, 300)
            };
        }
    """)
    print("DOM_INFO:", dom_info)
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
