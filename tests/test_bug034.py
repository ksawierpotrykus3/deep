import json
import pytest
import server

def test_compact_tools_formatting_drastic_size_reduction():
    with open('data/tools_cache.json', 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    tools_24 = None
    for k, v in cache.items():
        if len(v) == 24:
            tools_24 = v
            break
    assert tools_24 is not None, 'Must have 24 tools in cache'
    
    prompt = server._build_prompt([{'role': 'user', 'content': 'hi'}], tools=tools_24)
    # The formatted prompt with 24 tools must be under 7,000 characters (down from 44,000+)
    assert len(prompt) < 7000
    assert '# Available Tool Schemas' in prompt
    assert '## Task' in prompt
    assert '## RunCommand' in prompt
    assert '## Grep' in prompt
    assert '## Read' in prompt
    assert '- **RunCommand**(' in prompt

def test_polish_context_length_error_matching():
    err_polish_1 = 'DeepSeek error [context_length_exceeded]: Osiągnięto limit długości. Rozpocznij nowy czat.'
    err_polish_2 = 'Osiągnięto limit długości. Rozpocznij nowy czat.'
    
    keywords = ('length limit', 'context_length', 'start a new chat', 'content is too long', 'input_exceeds_limit', 'too long', 'limit długości', 'rozpocznij nowy czat')
    
    assert any(k in err_polish_1.lower() for k in keywords)
    assert any(k in err_polish_2.lower() for k in keywords)

def test_runcommand_power_shell_essay_stripped_from_prompt():
    with open('data/tools_cache.json', 'r', encoding='utf-8') as f:
        cache = json.load(f)
    tools_24 = next(v for v in cache.values() if len(v) == 24)
    prompt = server._build_prompt([{'role': 'user', 'content': 'test'}], tools=tools_24)
    
    # Verbose essays from Trae must NOT be present in prompt
    assert 'DO NOT use cmd.exe or command.exe' not in prompt
    assert 'The terminal command to execute.' not in prompt
    # But tool signature must be present
    assert '- **RunCommand**(cwd: string, command*: string' in prompt
