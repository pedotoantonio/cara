"""ctypes bindings for librkllmrt.so v1.1.0.

Mirrors the C structs in include/rkllm.h byte-for-byte. Kept private to this
package — the public surface is `cara.ai.llm.LLMService`.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    Union,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_int32,
    c_size_t,
    c_uint8,
    c_void_p,
)
from pathlib import Path

LLM_RUN_NORMAL = 0
LLM_RUN_WAITING = 1
LLM_RUN_FINISH = 2
LLM_RUN_ERROR = 3
LLM_RUN_GET_LAST_HIDDEN_LAYER = 4

RKLLM_INPUT_PROMPT = 0
RKLLM_INPUT_TOKEN = 1
RKLLM_INPUT_EMBED = 2
RKLLM_INPUT_MULTIMODAL = 3

RKLLM_INFER_GENERATE = 0
RKLLM_INFER_GET_LAST_HIDDEN_LAYER = 1


class RKLLMExtendParam(Structure):
    _fields_ = [
        ("base_domain_id", c_int32),
        ("reserved", c_uint8 * 112),
    ]


class RKLLMParam(Structure):
    _fields_ = [
        ("model_path", c_char_p),
        ("max_context_len", c_int32),
        ("max_new_tokens", c_int32),
        ("top_k", c_int32),
        ("top_p", c_float),
        ("temperature", c_float),
        ("repeat_penalty", c_float),
        ("frequency_penalty", c_float),
        ("presence_penalty", c_float),
        ("mirostat", c_int32),
        ("mirostat_tau", c_float),
        ("mirostat_eta", c_float),
        ("skip_special_token", c_bool),
        ("is_async", c_bool),
        ("img_start", c_char_p),
        ("img_end", c_char_p),
        ("img_content", c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMEmbedInput(Structure):
    _fields_ = [
        ("embed", POINTER(c_float)),
        ("n_tokens", c_size_t),
    ]


class RKLLMTokenInput(Structure):
    _fields_ = [
        ("input_ids", POINTER(c_int32)),
        ("n_tokens", c_size_t),
    ]


class RKLLMMultiModelInput(Structure):
    _fields_ = [
        ("prompt", c_char_p),
        ("image_embed", POINTER(c_float)),
        ("n_image_tokens", c_size_t),
    ]


class _RKLLMInputUnion(Union):
    _fields_ = [
        ("prompt_input", c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModelInput),
    ]


class RKLLMInput(Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("input_type", c_int),
        ("u", _RKLLMInputUnion),
    ]


class RKLLMLoraParam(Structure):
    _fields_ = [("lora_adapter_name", c_char_p)]


class RKLLMPromptCacheParam(Structure):
    _fields_ = [
        ("save_prompt_cache", c_int),
        ("prompt_cache_path", c_char_p),
    ]


class RKLLMInferParam(Structure):
    _fields_ = [
        ("mode", c_int),
        ("lora_params", POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", POINTER(RKLLMPromptCacheParam)),
    ]


class RKLLMResultLastHiddenLayer(Structure):
    _fields_ = [
        ("hidden_states", POINTER(c_float)),
        ("embd_size", c_int),
        ("num_tokens", c_int),
    ]


class RKLLMResult(Structure):
    _fields_ = [
        ("text", c_char_p),
        ("token_id", c_int32),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
    ]


LLMResultCallback = CFUNCTYPE(None, POINTER(RKLLMResult), c_void_p, c_int)


def load_lib(path: str | Path) -> ctypes.CDLL:
    so_path = Path(path)
    if not so_path.exists():
        raise FileNotFoundError(f"librkllmrt.so not found at {so_path}")
    lib = ctypes.CDLL(str(so_path))

    lib.rkllm_createDefaultParam.argtypes = []
    lib.rkllm_createDefaultParam.restype = RKLLMParam

    lib.rkllm_init.argtypes = [POINTER(c_void_p), POINTER(RKLLMParam), LLMResultCallback]
    lib.rkllm_init.restype = c_int

    lib.rkllm_run.argtypes = [c_void_p, POINTER(RKLLMInput), POINTER(RKLLMInferParam), c_void_p]
    lib.rkllm_run.restype = c_int

    lib.rkllm_abort.argtypes = [c_void_p]
    lib.rkllm_abort.restype = c_int

    lib.rkllm_destroy.argtypes = [c_void_p]
    lib.rkllm_destroy.restype = c_int

    lib.rkllm_is_running.argtypes = [c_void_p]
    lib.rkllm_is_running.restype = c_int

    return lib
