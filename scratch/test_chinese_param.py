import re
import json

def test_chinese_param():
    text = '<参数 name="description">Wywolanie</参数> <参数 name="query">tresc</参数>'
    pat = re.compile(r'<\s*(?:parameter|参数|參數)\s*name=(["\'])([^"\']+?)\1[^>]*>([\s\S]*?)</\s*(?:parameter|参数|參數)>', re.IGNORECASE)
    matches = list(pat.finditer(text))
    assert len(matches) == 2
    assert matches[0].group(2) == "description"
    assert matches[0].group(3) == "Wywolanie"
    assert matches[1].group(2) == "query"
    assert matches[1].group(3) == "tresc"
    print("Test passed!")

if __name__ == "__main__":
    test_chinese_param()
