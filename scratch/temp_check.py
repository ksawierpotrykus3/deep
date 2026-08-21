with open('proxy_output.log', encoding='utf-8', errors='ignore') as f:
    text = f.read()
    idx = text.find('call_xk715oHTibeDnWHltvmMTp5f')
    print(text[idx:idx+400])
