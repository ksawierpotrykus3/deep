"""
DeepSeek Proof of Work Challenge Implementation
Author: @xtekky
Date: 2024

This module implements a proof-of-work challenge solver using WebAssembly (WASM)
for Custom sha3 hashing. It provides functionality to solve computational challenges
required for authentication or rate limiting purposes.
"""

import json
import base64
import struct
import wasmtime
from typing import Dict, Any
import os
import threading

WASM_DIR = f'{os.path.dirname(__file__)}/wasm'
_WASM_FILES = [f for f in os.listdir(WASM_DIR) if f.endswith('.wasm')]
WASM_PATH = f'{WASM_DIR}/{_WASM_FILES[0]}' if _WASM_FILES else ''

_GLOBAL_ENGINE = wasmtime.Engine()
_GLOBAL_MODULE = None

if WASM_PATH and os.path.exists(WASM_PATH):
    with open(WASM_PATH, 'rb') as _f:
        _GLOBAL_MODULE = wasmtime.Module(_GLOBAL_ENGINE, _f.read())

class DeepSeekHash:
    def __init__(self):
        self.instance = None
        self.memory   = None
        self.store    = None
        
    def init(self, wasm_path: str = WASM_PATH):
        global _GLOBAL_MODULE
        engine = _GLOBAL_ENGINE
        
        if _GLOBAL_MODULE is None:
            path = wasm_path or WASM_PATH
            with open(path, 'rb') as f:
                wasm_bytes = f.read()
            _GLOBAL_MODULE = wasmtime.Module(engine, wasm_bytes)
            
        module = _GLOBAL_MODULE
        
        self.store = wasmtime.Store(engine)
        linker     = wasmtime.Linker(engine)
        linker.define_wasi()
        
        self.instance = linker.instantiate(self.store, module)
        exports = self.instance.exports(self.store)
        self.memory   = exports["memory"]
        self._alloc   = exports["__wbindgen_export_0"]
        self._free    = exports["__wbindgen_export_2"]
        self._stack   = exports["__wbindgen_add_to_stack_pointer"]
        self._solve   = exports["wasm_solve"]
        
        return self
    
    def _write_to_memory(self, text: str) -> tuple[int, int]:
        encoded = text.encode('utf-8')
        length  = len(encoded)
        ptr     = self._alloc(self.store, length, 1)
        
        memory_view = self.memory.data_ptr(self.store)
        for i, byte in enumerate(encoded):
            memory_view[ptr + i] = byte
            
        return ptr, length
    
    def calculate_hash(self, algorithm: str, challenge: str, salt: str, 
                      difficulty: int, expire_at: int) -> int | None:
        
        prefix = f"{salt}_{expire_at}_"  
        retptr = None
        challenge_ptr = prefix_ptr = None
        challenge_len = prefix_len = 0
        solved = False
        
        try:
            retptr = self._stack(self.store, -16)
            challenge_ptr, challenge_len = self._write_to_memory(challenge)
            prefix_ptr, prefix_len       = self._write_to_memory(prefix)
            
            self._solve(
                self.store,
                retptr, 
                challenge_ptr, 
                challenge_len, 
                prefix_ptr, 
                prefix_len, 
                float(difficulty)
            )
            solved = True
            
            memory_view = self.memory.data_ptr(self.store)
            status      = int.from_bytes(bytes(memory_view[retptr:retptr + 4]), byteorder='little', signed=True)
            
            if status == 0:
                return None
            
            value_bytes = bytes(memory_view[retptr + 8:retptr + 16])
            value       = struct.unpack('<d', value_bytes)[0]
            
            return int(value)
            
        finally:
            if challenge_ptr is not None:
                try:
                    self._free(self.store, challenge_ptr, challenge_len, 1)
                except Exception:
                    pass
            if prefix_ptr is not None:
                try:
                    self._free(self.store, prefix_ptr, prefix_len, 1)
                except Exception:
                    pass
            if retptr is not None:
                try:
                    self._stack(self.store, 16)
                except Exception:
                    pass

class DeepSeekPOW:
    def __init__(self):
        self._local = threading.local()
    
    def _get_hasher(self) -> DeepSeekHash:
        if not hasattr(self._local, 'hasher'):
            self._local.hasher = DeepSeekHash().init(WASM_PATH)
        return self._local.hasher
    
    def solve_challenge(self, config: Dict[str, Any]) -> str:
        """Solves a proof-of-work challenge and returns the encoded response"""
        hasher = self._get_hasher()
        answer = hasher.calculate_hash(
            config['algorithm'],
            config['challenge'],
            config['salt'],
            config['difficulty'],
            config['expire_at']
        )
        
        result = {
            'algorithm': config['algorithm'],
            'challenge': config['challenge'],
            'salt': config['salt'],
            'answer': answer,
            'signature': config['signature'],
            'target_path': config['target_path']
        }
        
        return base64.b64encode(json.dumps(result).encode()).decode()