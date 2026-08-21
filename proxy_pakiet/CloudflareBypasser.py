import time
from DrissionPage import ChromiumPage

class CloudflareBypasser:
    def __init__(self, driver: ChromiumPage, max_retries: int = -1, log: bool = True, timeout: int = 120):
        self.driver = driver
        self.max_retries = max_retries
        self.log = log
        self.timeout = timeout

    def search_recursively_shadow_root_with_iframe(self,ele):
        if ele.shadow_root:
            if ele.shadow_root.child().tag == "iframe":
                return ele.shadow_root.child()
        else:
            for child in ele.children():
                result = self.search_recursively_shadow_root_with_iframe(child)
                if result:
                    return result
        return None

    def search_recursively_shadow_root_with_cf_input(self,ele):
        if ele.shadow_root:
            if ele.shadow_root.ele("tag:input"):
                return ele.shadow_root.ele("tag:input")
        else:
            for child in ele.children():
                result = self.search_recursively_shadow_root_with_cf_input(child)
                if result:
                    return result
        return None
    
    def locate_cf_button(self):
        button = None
        eles = self.driver.eles("tag:input")
        for ele in eles:
            if "name" in ele.attrs.keys() and "type" in ele.attrs.keys():
                if "turnstile" in ele.attrs["name"] and ele.attrs["type"] == "hidden":
                    button = ele.parent().shadow_root.child()("tag:body").shadow_root("tag:input")
                    break
            
        if button:
            return button
        else:
            # If the button is not found, search it recursively
            self.log_message("Basic search failed. Searching for button recursively.")
            ele = self.driver.ele("tag:body")
            iframe = self.search_recursively_shadow_root_with_iframe(ele)
            if iframe:
                button = self.search_recursively_shadow_root_with_cf_input(iframe("tag:body"))
            else:
                self.log_message("Iframe not found. Button search failed.")
            return button

    def log_message(self, message):
        if self.log:
            print(message)

    def click_verification_button(self):
        try:
            button = self.locate_cf_button()
            if button:
                self.log_message("Verification button found. Attempting to click.")
                button.click()
            else:
                self.log_message("Verification button not found.")

        except Exception as e:
            self.log_message(f"Error clicking verification button: {e}")

    def is_bypassed(self) -> bool:
        try:
            raw_title = self.driver.title
            if not raw_title:
                return False
            title = str(raw_title).strip().lower()
            if not title:
                return False
            
            block_phrases = [
                "just a moment",
                "attention required",
                "security check",
                "cloudflare",
                "turnstile",
                "chwileczkę",
            ]
            for phrase in block_phrases:
                if phrase in title:
                    return False
            return True
        except Exception as e:
            self.log_message(f"Error checking page title: {e}")
            return False

    def bypass(self) -> bool:
        try_count = 0
        start_time = time.time()

        while not self.is_bypassed():
            if self.max_retries > 0 and try_count >= self.max_retries:
                self.log_message("Exceeded maximum retries. Bypass failed.")
                break

            if time.time() - start_time > self.timeout:
                self.log_message(f"Bypass timed out after {self.timeout} seconds.")
                break

            self.log_message(f"Attempt {try_count + 1}: Verification page detected. Trying to bypass...")
            self.click_verification_button()

            try_count += 1
            time.sleep(2)

        if self.is_bypassed():
            self.log_message("Bypass successful.")
            return True
        else:
            self.log_message("Bypass failed.")
            return False
