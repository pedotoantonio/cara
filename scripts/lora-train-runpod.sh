#!/usr/bin/env bash
#
# LoRA training runbook for CARA on a RunPod (or any x86_64 + CUDA GPU).
#
# This script is NOT meant to run on the NanoPC-T6. Copy it to a rented
# GPU node along with the .jsonl files produced by export_lora_dataset.py
# and execute there.
#
# Recommended GPU:  RTX A6000 48GB (RunPod, ~$0.79/h)
# Image:            runpod/pytorch:2.4.0-py3.11-cuda12.4.1
# Wallclock:        ~5 hours for 1.5B base, 200-500 examples, 3 epochs
#
# Output:           ./lora-out/cara-qwen-1p5b-lora.rkllm
#
# After training, scp the .rkllm back to the NanoPC, drop it into
# /opt/cara/data/models/, then `docker restart cara-backend`. The
# admin can flip llm_quality_mode → custom (to be wired in v1.1) or
# overwrite the default model symlink.
set -euo pipefail

DATASET_DIR="${1:-/workspace/cara_lora}"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
OUT_DIR="${OUT_DIR:-./lora-out}"
EPOCHS="${EPOCHS:-3}"
LORA_R="${LORA_R:-16}"
LORA_ALPHA="${LORA_ALPHA:-32}"
LR="${LR:-1e-4}"

if [[ ! -d "$DATASET_DIR" ]]; then
  echo "Missing dataset dir: $DATASET_DIR" >&2
  exit 2
fi

echo "=== Preparing environment ==="
pip install -q -U \
  "transformers>=4.45" "peft>=0.13" "accelerate>=1.0" "trl>=0.11" \
  "datasets>=3.0" "bitsandbytes>=0.44" "sentencepiece" "protobuf"

mkdir -p "$OUT_DIR"

echo "=== Merging the three datasets into a single train.jsonl ==="
cat "$DATASET_DIR"/cara_persona.jsonl \
    "$DATASET_DIR"/cara_tool_calls.jsonl \
    "$DATASET_DIR"/cara_skill_dispatch.jsonl \
  > "$DATASET_DIR/train.jsonl"

echo "=== Running SFT with LoRA ==="
python - <<'PY'
import json
import os
from datasets import Dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer
from transformers import AutoModelForCausalLM, AutoTokenizer

dataset_path = os.path.join(os.environ.get("DATASET_DIR", "/workspace/cara_lora"), "train.jsonl")
base_model  = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
out_dir     = os.environ.get("OUT_DIR", "./lora-out")
epochs      = int(os.environ.get("EPOCHS", 3))
lora_r      = int(os.environ.get("LORA_R", 16))
lora_alpha  = int(os.environ.get("LORA_ALPHA", 32))
lr          = float(os.environ.get("LR", 1e-4))

with open(dataset_path) as f:
    rows = [json.loads(line) for line in f if line.strip()]
print(f"Loaded {len(rows)} training rows")

ds = Dataset.from_list(rows)
tok = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    base_model, torch_dtype="bfloat16", device_map="auto",
    trust_remote_code=True,
)

trainer = SFTTrainer(
    model=model,
    args=SFTConfig(
        output_dir=out_dir, num_train_epochs=epochs,
        per_device_train_batch_size=2, gradient_accumulation_steps=4,
        learning_rate=lr, warmup_ratio=0.05,
        logging_steps=10, save_strategy="epoch",
        max_seq_length=2048,
    ),
    train_dataset=ds,
    peft_config=LoraConfig(
        r=lora_r, lora_alpha=lora_alpha, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    ),
    processing_class=tok,
)
trainer.train()
trainer.save_model(out_dir)
PY

echo "=== Merging LoRA → base + exporting to .rkllm ==="
python - <<'PY'
# Merge LoRA weights into base, then convert via rkllm-toolkit.
import os
from peft import PeftModel
from transformers import AutoModelForCausalLM

base = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
out  = os.environ.get("OUT_DIR", "./lora-out")
merged_dir = os.path.join(out, "merged")

m = AutoModelForCausalLM.from_pretrained(base, torch_dtype="bfloat16", trust_remote_code=True)
m = PeftModel.from_pretrained(m, out)
m = m.merge_and_unload()
m.save_pretrained(merged_dir)
PY

echo "=== Exporting to RKLLM (Rockchip toolkit) ==="
python - <<'PY'
from rkllm.api import RKLLM
out = "./lora-out"
merged = f"{out}/merged"
rkllm = RKLLM()
ret = rkllm.load_huggingface(model=merged, model_lora=None, device="cpu")
if ret != 0:
    raise SystemExit("rkllm load_huggingface failed")
ret = rkllm.build(
    do_quantization=True, optimization_level=1,
    quantized_dtype="w8a8_g128", quantized_algorithm="normal",
    target_platform="rk3588", num_npu_core=3,
    extra_qparams=None, dataset=None,
)
if ret != 0:
    raise SystemExit("rkllm build failed")
ret = rkllm.export_rkllm(f"{out}/cara-qwen-1p5b-lora.rkllm")
if ret != 0:
    raise SystemExit("rkllm export failed")
print("Export OK")
PY

echo "=== Done. Artifact: $OUT_DIR/cara-qwen-1p5b-lora.rkllm ==="
ls -lh "$OUT_DIR"/*.rkllm
