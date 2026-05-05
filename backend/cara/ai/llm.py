"""LLMService — single-instance Qwen2.5 inference for the CARA backend.

Architecture:

- One RKLLM handle per process (NPU memory caps at ~3 GB on RK3588 → max one
  Qwen2.5-1.5B w8a8 instance per worker).
- `rkllm_run` blocks until generation completes; tokens stream through a C
  callback. We bridge the callback (called from a runtime-owned thread) to
  Python via a thread-safe `queue.Queue`, then drain that queue from the
  asyncio loop with `loop.run_in_executor` so FastAPI handlers remain async.
- An `asyncio.Lock` serialises calls to `generate()` because RKLLM does NOT
  accept concurrent `rkllm_run` invocations on the same handle. Concurrent
  requests at the API layer queue on this lock.
- For >1 concurrent generation, run uvicorn with `--workers N` (each worker
  loads its own model) — capped by NPU memory, so realistically N=2 max.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import queue
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import structlog

from cara.ai import _rkllm_bindings as rk
from cara.config import settings

logger = structlog.get_logger(__name__)

_FINISH_SENTINEL: object = object()
_ERROR_SENTINEL: object = object()


@dataclass(slots=True)
class TokenChunk:
    text: str
    token_id: int


@dataclass(slots=True)
class GenerationStats:
    first_token_seconds: float
    total_seconds: float
    token_count: int

    @property
    def tokens_per_second(self) -> float:
        return self.token_count / max(self.total_seconds, 1e-6)


class LLMUnavailableError(RuntimeError):
    """Raised when the LLM is disabled or failed to initialise."""


class LLMService:
    """Async-safe singleton wrapper around librkllmrt.so.

    Instantiate once at app startup via `lifespan`, expose to handlers with
    `get_llm_service()`. Call `await aclose()` at shutdown.

    Supports hot-swap between size variants via `set_mode("fast"|"quality")`:
    the NPU memory cap (~3 GB on RK3588) means we can only hold one model
    loaded at a time, so a switch is destroy + load (~10 s once warmed).
    """

    def __init__(
        self,
        model_path: str | os.PathLike[str],
        lib_path: str | os.PathLike[str],
        max_context_len: int,
        max_new_tokens: int,
        *,
        models: dict[str, str] | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        repeat_penalty: float | None = None,
    ) -> None:
        # Backwards compatibility: if no `models` map is provided, the
        # legacy single-model boot still works (the only mode = "default"
        # and points at `model_path`).
        self._models: dict[str, Path] = (
            {k: Path(v) for k, v in models.items()} if models
            else {"default": Path(model_path)}
        )
        self._mode: str = next(iter(self._models))
        self._model_path = self._models[self._mode]
        self._lib_path = Path(lib_path)
        self._max_context_len = max_context_len
        self._default_max_new_tokens = max_new_tokens
        # Sampling defaults baked into the model at init time. RKLLM 1.1.0
        # uses these for every rkllm_run; per-request overrides through the
        # public C API are not supported, so the only way to influence
        # sampling is at load. None → keep the runtime's createDefaultParam
        # value (RKLLM 1.1.0 defaults: temp=0.8, top_k=40, top_p=0.9, rp=1.1).
        self._init_temperature = temperature
        self._init_top_k = top_k
        self._init_top_p = top_p
        self._init_repeat_penalty = repeat_penalty
        self._lib: ctypes.CDLL | None = None
        self._handle: ctypes.c_void_p | None = None
        # CFUNCTYPE wrappers must outlive the C library or it crashes; keep a ref.
        self._cb_ref: ctypes.CFUNCTYPE | None = None  # type: ignore[type-arg]
        # Thread-safe queue used by the C callback thread; drained from asyncio.
        self._token_q: queue.Queue = queue.Queue()
        # Serialise rkllm_run calls (the runtime does not allow concurrency).
        self._gen_lock = asyncio.Lock()
        self._loaded = False
        # Lock for switch operations (destroy + reload sequence).
        self._switch_lock = asyncio.Lock()

    # ------------------------------------------------------------------ load

    async def aload(self) -> None:
        """Load the model on the executor thread (blocking, ~5s for 1.5B)."""
        if self._loaded:
            return
        if not self._model_path.is_file():
            raise LLMUnavailableError(f"model file missing: {self._model_path}")
        if not self._lib_path.is_file():
            raise LLMUnavailableError(f"runtime library missing: {self._lib_path}")

        log = logger.bind(model=str(self._model_path), lib=str(self._lib_path))
        log.info("llm.load.start")
        t0 = time.monotonic()
        await asyncio.to_thread(self._load_blocking)
        log.info("llm.load.done", seconds=round(time.monotonic() - t0, 2))

    def _load_blocking(self) -> None:
        self._lib = rk.load_lib(self._lib_path)
        self._cb_ref = rk.LLMResultCallback(self._on_result)

        param = self._lib.rkllm_createDefaultParam()
        param.model_path = str(self._model_path).encode("utf-8")
        param.max_context_len = self._max_context_len
        param.max_new_tokens = self._default_max_new_tokens
        param.skip_special_token = True
        param.is_async = False
        param.extend_param.base_domain_id = 0
        # Apply admin/config sampling defaults — without this the runtime's
        # createDefaultParam values win silently. We keep `None` semantics
        # so an empty config falls back to the runtime defaults.
        if self._init_temperature is not None:
            param.temperature = float(self._init_temperature)
        if self._init_top_k is not None:
            param.top_k = int(self._init_top_k)
        if self._init_top_p is not None:
            param.top_p = float(self._init_top_p)
        if self._init_repeat_penalty is not None:
            param.repeat_penalty = float(self._init_repeat_penalty)
        logger.info(
            "llm.load.sampling",
            temperature=float(param.temperature),
            top_k=int(param.top_k),
            top_p=float(param.top_p),
            repeat_penalty=float(param.repeat_penalty),
            max_new_tokens=int(param.max_new_tokens),
        )

        self._handle = ctypes.c_void_p()
        rc = self._lib.rkllm_init(
            ctypes.byref(self._handle), ctypes.byref(param), self._cb_ref
        )
        if rc != 0:
            raise LLMUnavailableError(f"rkllm_init failed: rc={rc}")
        self._loaded = True

    # --------------------------------------------------------------- callback

    def _on_result(self, result_ptr, _userdata, state: int) -> None:
        # Runs on a librkllmrt-owned thread. Must NOT touch asyncio directly.
        if state == rk.LLM_RUN_FINISH:
            self._token_q.put(_FINISH_SENTINEL)
            return
        if state == rk.LLM_RUN_ERROR:
            self._token_q.put(_ERROR_SENTINEL)
            return
        if state == rk.LLM_RUN_NORMAL and result_ptr:
            r = result_ptr.contents
            text = r.text.decode("utf-8", errors="replace") if r.text else ""
            self._token_q.put(TokenChunk(text=text, token_id=int(r.token_id)))
        # WAITING / GET_LAST_HIDDEN_LAYER are not used in this profile.

    # ---------------------------------------------------------------- generate

    async def generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        repeat_penalty: float | None = None,
        prompt_cache_path: str | os.PathLike[str] | None = None,
    ) -> AsyncIterator[TokenChunk]:
        """Stream `TokenChunk`s for `prompt`.

        Backpressure: the caller awaits each token; the runtime thread fills
        a thread-safe queue, the asyncio loop drains via `to_thread`.

        `prompt_cache_path`: when set, RKLLM persists the KV cache for this
        run to the given file (`save_prompt_cache=1`). The next generation
        that passes the same path skips prefill on the shared prefix —
        TTFT for follow-up turns drops from ~200 ms to ~50 ms in practice.
        Caller is responsible for invalidating the file when the prefix
        changes (system prompt edited, history truncated, …); see
        `cara.ai.kv_cache.flush_one`.
        """
        if not self._loaded or self._lib is None or self._handle is None:
            raise LLMUnavailableError("LLM not initialised")

        async with self._gen_lock:
            async for chunk in self._generate_locked(
                prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
                prompt_cache_path=prompt_cache_path,
            ):
                yield chunk

    async def _generate_locked(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None,
        temperature: float | None,
        top_k: int | None,
        top_p: float | None,
        repeat_penalty: float | None,
        prompt_cache_path: str | os.PathLike[str] | None = None,
    ) -> AsyncIterator[TokenChunk]:
        assert self._lib is not None and self._handle is not None  # noqa: S101

        # Drain stale tokens (defensive — should always be empty after a clean run)
        while not self._token_q.empty():
            self._token_q.get_nowait()

        # Per-request param overrides via createDefaultParam → modify → not
        # supported by the public API; we relied on init-time defaults. The
        # user-facing knobs that DO change at runtime are encoded in the
        # prompt itself (system message + chat template). For now, log if a
        # caller tried to vary sampling params and ignore them.
        if any(
            v is not None
            for v in (temperature, top_k, top_p, repeat_penalty)
        ):
            logger.debug(
                "llm.generate.sampling_overrides_ignored",
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
            )

        rkllm_input = rk.RKLLMInput()
        rkllm_input.input_type = rk.RKLLM_INPUT_PROMPT
        rkllm_input.prompt_input = prompt.encode("utf-8")

        infer = rk.RKLLMInferParam()
        infer.mode = rk.RKLLM_INFER_GENERATE
        infer.lora_params = None

        # Hold a reference to the cache-param struct so the C side keeps
        # seeing valid memory for the entire rkllm_run. Without this
        # local binding the GC could free the struct mid-call.
        cache_struct: rk.RKLLMPromptCacheParam | None = None
        if prompt_cache_path is not None:
            cache_struct = rk.RKLLMPromptCacheParam()
            cache_struct.save_prompt_cache = 1
            cache_struct.prompt_cache_path = str(prompt_cache_path).encode("utf-8")
            infer.prompt_cache_params = ctypes.pointer(cache_struct)
        else:
            infer.prompt_cache_params = None

        run_rc: dict[str, int | None] = {"value": None}
        finished = threading.Event()

        def _run() -> None:
            try:
                run_rc["value"] = self._lib.rkllm_run(  # type: ignore[union-attr]
                    self._handle, ctypes.byref(rkllm_input), ctypes.byref(infer), None
                )
            finally:
                finished.set()

        # Fire rkllm_run on a worker thread so the asyncio loop can drain tokens.
        worker = threading.Thread(target=_run, daemon=True, name="rkllm-run")
        worker.start()

        loop = asyncio.get_running_loop()
        n = 0
        t_start = time.monotonic()
        t_first: float | None = None
        max_n = max_new_tokens if max_new_tokens is not None else self._default_max_new_tokens

        try:
            while True:
                item = await loop.run_in_executor(None, self._token_q.get)
                if item is _FINISH_SENTINEL:
                    break
                if item is _ERROR_SENTINEL:
                    raise LLMUnavailableError(
                        f"rkllm callback reported ERROR (run rc={run_rc['value']})"
                    )
                if t_first is None:
                    t_first = time.monotonic() - t_start
                n += 1
                yield item  # type: ignore[misc]
                if n >= max_n:
                    # The runtime stops by itself at max_new_tokens (init param);
                    # this is just a safety bound for explicit per-request caps.
                    break
        finally:
            # If the consumer cancelled (client disconnect, max_n cap, error),
            # the worker is still running rkllm_run. Abort it and drain.
            if not finished.is_set():
                self._lib.rkllm_abort(self._handle)  # type: ignore[union-attr]
            await loop.run_in_executor(None, worker.join, 5.0)
            # Drain any tokens that arrived between abort and join.
            while not self._token_q.empty():
                self._token_q.get_nowait()
            t_total = time.monotonic() - t_start
            logger.info(
                "llm.generate.done",
                tokens=n,
                first_token_s=round(t_first or 0.0, 3),
                total_s=round(t_total, 2),
                tok_per_s=round(n / max(t_total, 1e-6), 2),
            )

        if run_rc["value"] not in (0, None):
            raise LLMUnavailableError(f"rkllm_run failed: rc={run_rc['value']}")

    # ----------------------------------------------------------------- validate

    async def validate(
        self,
        *,
        question: str,
        answer: str,
        validation_prompt: str,
        max_new_tokens: int = 160,
    ) -> str | None:
        """Run a self-critique pass.

        Returns:
          - None if the model approves the answer (replies "OK")
          - A rewritten answer string if the model says "RIVEDI" + content
        """
        # Reuse the Qwen2.5 chat template — the validation runs in a fresh
        # one-shot prompt so it does not see the live conversation memory.
        prompt = (
            "<|im_start|>system\n"
            f"{validation_prompt}\n"
            "<|im_end|>\n"
            "<|im_start|>user\n"
            f"Domanda: {question}\n\n"
            f"Risposta dell'assistente: {answer}\n"
            "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        buf: list[str] = []
        async for chunk in self.generate(prompt, max_new_tokens=max_new_tokens):
            buf.append(chunk.text)
        verdict = "".join(buf).strip()
        # First non-empty line is the verdict tag; subsequent lines (if any)
        # are the rewrite. We accept either "OK" or anything beginning with
        # "RIVEDI".
        lines = [ln.rstrip() for ln in verdict.splitlines() if ln.strip()]
        if not lines:
            return None
        head = lines[0].strip().upper()
        if head.startswith("OK"):
            return None
        if head.startswith("RIVEDI"):
            rest = "\n".join(lines[1:]).strip()
            return rest or None
        # Unknown verdict — be conservative and accept the original.
        return None

    # ------------------------------------------------------------------ swap

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def available_modes(self) -> list[str]:
        return list(self._models)

    async def set_mode(self, new_mode: str) -> None:
        """Hot-swap the active model variant.

        NPU memory cap on RK3588 (~3 GB) means we can only hold one variant
        loaded; a switch is destroy + load. Acquires both the gen lock (so
        no in-flight generate is interrupted) and the switch lock (so
        concurrent swap requests serialise).
        """
        if new_mode not in self._models:
            raise ValueError(
                f"unknown LLM mode {new_mode!r}; available: {list(self._models)}"
            )
        if new_mode == self._mode and self._loaded:
            return
        async with self._switch_lock:
            if new_mode == self._mode and self._loaded:
                return
            log = logger.bind(from_mode=self._mode, to_mode=new_mode)
            log.info("llm.swap.start")
            t0 = time.monotonic()
            async with self._gen_lock:
                # Destroy current handle.
                if self._loaded and self._lib is not None and self._handle is not None:
                    await asyncio.to_thread(self._lib.rkllm_destroy, self._handle)
                    self._handle = None
                    self._loaded = False
                # Load new model.
                self._mode = new_mode
                self._model_path = self._models[new_mode]
                await asyncio.to_thread(self._load_blocking)
            log.info("llm.swap.done", seconds=round(time.monotonic() - t0, 2))

    # ------------------------------------------------------------------- close

    async def aclose(self) -> None:
        if self._loaded and self._lib is not None and self._handle is not None:
            await asyncio.to_thread(self._lib.rkllm_destroy, self._handle)
            self._handle = None
            self._loaded = False
            logger.info("llm.shutdown")


# --------------------------------------------------------------------- factory

_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """FastAPI dependency injection — returns the process-wide singleton."""
    if _service is None:
        raise LLMUnavailableError("LLMService not initialised (lifespan not run?)")
    return _service


async def init_llm_service() -> LLMService | None:
    """Build + load the singleton. Called from the FastAPI `lifespan`.

    Returns `None` if LLM is disabled via `LLM_ENABLED=false`. Raises
    `LLMUnavailableError` if enabled but loading fails.
    """
    global _service
    if not settings.llm_enabled:
        logger.info("llm.disabled")
        return None
    # Build the modes map. The "fast" mode = 1.5B (default), "quality" = 3B
    # if the file exists. We don't crash if the secondary model is missing —
    # the hot-swap simply isn't available.
    models: dict[str, str] = {"fast": settings.llm_model_path}
    quality_path = (settings.llm_model_path_quality or "").strip()
    if quality_path and Path(quality_path).is_file():
        models["quality"] = quality_path
    else:
        logger.info("llm.quality_mode_unavailable", reason="model file missing", path=quality_path)
    _service = LLMService(
        model_path=settings.llm_model_path,
        lib_path=settings.llm_runtime_lib_path,
        max_context_len=settings.llm_max_context_len,
        max_new_tokens=settings.llm_max_new_tokens,
        models=models,
        temperature=settings.llm_temperature,
        top_k=settings.llm_top_k,
        top_p=settings.llm_top_p,
        repeat_penalty=settings.llm_repeat_penalty,
    )
    await _service.aload()
    return _service


async def shutdown_llm_service() -> None:
    global _service
    if _service is not None:
        await _service.aclose()
        _service = None
