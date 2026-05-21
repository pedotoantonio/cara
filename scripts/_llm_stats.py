#!/usr/bin/env python3
"""Aggregate Cara LLM metrics from `docker logs cara-backend` on stdin."""
import re, sys, statistics

window = sys.argv[1] if len(sys.argv) > 1 else "24h"

re_gen = re.compile(r"llm\.generate\.done.*?first_token_s=([\d.]+).*?tok_per_s=([\d.]+).*?tokens=(\d+).*?total_s=([\d.]+)")
re_prompt = re.compile(r"chat\.prompt_built.*?approx_tokens=(\d+)")
re_load = re.compile(r"llm\.load\.done.*?seconds=([\d.]+)")
re_unavail = re.compile(r"chat\.llm_unavailable|rkllm_run failed|rkllm_init failed|LLMUnavailableError")

ttft, tps, toks, total, prompt_sz, load_s = [], [], [], [], [], []
silent = unavail = gens = 0

for line in sys.stdin:
    if m := re_gen.search(line):
        ft, tp, n, t = float(m.group(1)), float(m.group(2)), int(m.group(3)), float(m.group(4))
        if n > 0:
            ttft.append(ft); tps.append(tp); toks.append(n); total.append(t); gens += 1
        else:
            silent += 1
    elif m := re_prompt.search(line):
        prompt_sz.append(int(m.group(1)))
    elif m := re_load.search(line):
        load_s.append(float(m.group(1)))
    elif re_unavail.search(line):
        unavail += 1


def pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[int(round((p / 100) * (len(xs) - 1)))]


def fmt(label, xs, unit=""):
    if not xs:
        print(f"  {label}: (no data)")
        return
    print(
        f"  {label}: n={len(xs)}  p50={pct(xs,50):.2f}{unit}  p95={pct(xs,95):.2f}{unit}  "
        f"mean={statistics.mean(xs):.2f}{unit}  max={max(xs):.2f}{unit}"
    )


print(f"=== Cara LLM stats — last {window} ===")
print(f"Generazioni riuscite: {gens}")
print(f"Generazioni vuote (0 tokens): {silent}")
print(f"Errori rkllm/unavailable: {unavail}")
print(f"Token totali generati: {sum(toks)}")
print()
print("Timing:")
fmt("TTFT", ttft, "s")
fmt("tok/s", tps)
fmt("total_s", total, "s")
print()
print("Prompt size (approx_tokens):")
fmt("size", prompt_sz, " tok")
print()
print("Model load:")
fmt("load_seconds", load_s, "s")

if silent > 0 and (gens + silent) > 0:
    rate = silent / (gens + silent) * 100
    print(f"\nSilent failure rate: {rate:.1f}% ({silent}/{gens+silent})")
if unavail > 0:
    print(f"LLM unavailable events: {unavail}")
