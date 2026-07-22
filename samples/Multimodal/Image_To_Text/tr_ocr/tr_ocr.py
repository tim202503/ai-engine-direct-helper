# ---------------------------------------------------------------------
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
# ---------------------------------------------------------------------
"""
TrOCR Inference Script
Optical Character Recognition on Snapdragon X Elite NPU

Model  : microsoft/trocr-base-printed  (encoder-decoder)
Format : QNN_DLC (encoder.dlc + decoder.dlc)
Runtime: qai_appbuilder.QNNContext  (HTP / NPU)
Device : Snapdragon X Elite

Architecture:
  encoder.dlc  - ViT image encoder (ViT-Base-384)
    IN  pixel_values [1,384,384,3] float32  NHWC  value_range [0,1]
    OUT kv_cache_key/val_0..5  [1,8,578,32] float32  (cross-attn KV)

  decoder.dlc  - Autoregressive text decoder (RoBERTa BPE)
    IN  index      [1]      int32   current decode step (0..19)
    IN  input_ids  [1,1]    int32   current token id
    IN  kv_{0..5}_attn_key/val    [1,8,19,32]  float32  self-attn KV (past tokens)
    IN  kv_{0..5}_cross_attn_key/val [1,8,578,32] float32  cross-attn from encoder
    OUT next_token  [1]  int32   predicted next token (already argmax)
    OUT kv_cache_key/val_{0..5}  [1,8,20,32] float32  updated self-attn KV

Key Notes:
  - decoder getInputName() order: [index, input_ids, kv_0_attn_key, kv_0_attn_val,
    kv_0_cross_attn_key, kv_0_cross_attn_val, ...] (index BEFORE input_ids)
  - MAX decode steps = 20 (index range 0..19, enforced by KV cache size)
  - KV cache update: output [1,8,20,32] -> drop oldest: [:,:,1:,:] -> [1,8,19,32]
  - Tokenizer: RoBERTa BPE, BOS=0, EOS=2, vocab=50265
  - Image preprocessing: ViTImageProcessor, resize to 384x384, normalize [0,1]
    (AI Hub bakes normalization into model: mean=[0,0,0], std=[1,1,1])
  - Input layout: NHWC [1,384,384,3] (ViTImageProcessor outputs NCHW, must transpose)

Usage:
  python tr_ocr.py --image path/to/image.jpg
"""

import sys
import os
import time
import zipfile
import argparse
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Paths ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "..", "..", "common"))
from install import download_url, detect_device_model

# ── Model download URL ─────────────────────────────────────────────────────
MODEL_NAME = "trocr"
MODEL_URL  = "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/trocr/releases/v0.57.1/trocr-qnn_dlc-float.zip"

MODELS_DIR    = os.path.join(_SCRIPT_DIR, "models")
TOKENIZER_DIR = os.path.join(MODELS_DIR, "tokenizer")

# ── Constants (from metadata.json + getInputName() verification) ───────────
IMG_SIZE        = 384
NUM_LAYERS      = 6
NUM_HEADS       = 8
HEAD_DIM        = 32
CROSS_SEQ_LEN   = 578
SELF_KV_IN_LEN  = 19
MAX_GEN_TOKENS  = 20    # decoder index range = [0..19]


# ── Model download ─────────────────────────────────────────────────────────
def model_download():
    """Download and extract the TrOCR model zip.

    Model files (encoder.dlc / decoder.dlc) are placed directly under MODELS_DIR,
    NOT in a subdirectory named after the zip file.
    """
    import shutil

    device_model = detect_device_model()
    print(f"[INFO] Detected device: {device_model}")

    zip_name = MODEL_URL.split("/")[-1]   # trocr-qnn_dlc-float.zip

    encoder_dlc = os.path.join(MODELS_DIR, "encoder.dlc")
    decoder_dlc = os.path.join(MODELS_DIR, "decoder.dlc")

    if os.path.exists(encoder_dlc) and os.path.exists(decoder_dlc):
        print(f"[INFO] Model already exists: {MODELS_DIR}")
        return MODELS_DIR

    os.makedirs(MODELS_DIR, exist_ok=True)
    zip_path = os.path.join(MODELS_DIR, zip_name)

    print(f"[INFO] Downloading model from:\n       {MODEL_URL}")
    ret = download_url(MODEL_URL, zip_path, desc=f"Downloading {MODEL_NAME} model...")
    if not ret or not os.path.exists(zip_path):
        print(f"[ERROR] Failed to download model. Please download manually:\n  {MODEL_URL}")
        sys.exit(1)

    print(f"[INFO] Extracting {zip_name} ...")
    # Extract into a temp dir, then copy all files flat into MODELS_DIR
    tmp_dir = os.path.join(MODELS_DIR, "_tmp_extract")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)

    # Delete the zip archive
    os.remove(zip_path)
    print(f"[INFO] Removed archive: {zip_name}")

    # Walk the extracted tree and copy all files directly into MODELS_DIR
    print(f"[INFO] Copying model files to: {MODELS_DIR}")
    for root, dirs, files in os.walk(tmp_dir):
        # Skip any tokenizer sub-folder that may be bundled in the zip
        dirs[:] = [d for d in dirs if d != "tokenizer"]
        for fname in files:
            src = os.path.join(root, fname)
            dst = os.path.join(MODELS_DIR, fname)
            shutil.copy2(src, dst)
            print(f"      Copied: {fname}")

    shutil.rmtree(tmp_dir, ignore_errors=True)

    if not os.path.exists(encoder_dlc) or not os.path.exists(decoder_dlc):
        print(f"[ERROR] encoder.dlc / decoder.dlc not found in: {MODELS_DIR}")
        sys.exit(1)

    print(f"[INFO] Model ready: {MODELS_DIR}")
    return MODELS_DIR


# ── Step 0: Download model ─────────────────────────────────────────────────
print("[0/5] Checking / downloading model...")
MODEL_DIR   = model_download()
ENCODER_DLC = os.path.join(MODEL_DIR, "encoder.dlc")
DECODER_DLC = os.path.join(MODEL_DIR, "decoder.dlc")

# ── Step 1: Initialize QNN (MUST be first qai_appbuilder call) ─────────────
print("[1/5] Initializing QNN HTP backend ...")
from qai_appbuilder import QNNContext, QNNConfig, Runtime, LogLevel, ProfilingLevel
QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.OFF)
print("      QNN backend ready.")

# ── Step 2: Load tokenizer ─────────────────────────────────────────────────
print("[2/5] Loading tokenizer ...")
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
from transformers import RobertaTokenizer, TrOCRProcessor, ViTImageProcessor

# Check that the tokenizer directory exists AND contains the required config file
_tokenizer_ready = (
    os.path.exists(TOKENIZER_DIR)
    and os.path.exists(os.path.join(TOKENIZER_DIR, "tokenizer_config.json"))
)
if _tokenizer_ready:
    tokenizer = RobertaTokenizer.from_pretrained(TOKENIZER_DIR)
else:
    print(f"      Tokenizer not found locally, downloading from HuggingFace...")
    os.makedirs(TOKENIZER_DIR, exist_ok=True)
    tokenizer = RobertaTokenizer.from_pretrained(
        "microsoft/trocr-base-printed", cache_dir=TOKENIZER_DIR
    )
    # Save files locally so future runs work offline
    tokenizer.save_pretrained(TOKENIZER_DIR)
    print(f"      Tokenizer saved to: {TOKENIZER_DIR}")

BOS_ID = tokenizer.bos_token_id   # 0  (<s>)
EOS_ID = tokenizer.eos_token_id   # 2  (</s>)
print(f"      vocab={tokenizer.vocab_size}  BOS={BOS_ID}  EOS={EOS_ID}")

# TrOCR uses standard ViT normalization: mean=0.5, std=0.5 -> output range [-1, 1]
# The model's value_range [0,1] refers to the raw pixel input before normalization.
image_processor = ViTImageProcessor(
    do_resize=True,
    size={"height": IMG_SIZE, "width": IMG_SIZE},
    do_normalize=True,
    image_mean=[0.5, 0.5, 0.5],
    image_std=[0.5, 0.5, 0.5],
)

# ── Step 3: Load encoder + decoder on NPU ─────────────────────────────────
print("[3/5] Loading encoder.dlc (NPU) ...")
t0 = time.time()
encoder = QNNContext("trocr_encoder", ENCODER_DLC)
enc_in_names  = encoder.getInputName()
enc_out_names = encoder.getOutputName()
print(f"      Loaded in {(time.time()-t0)*1000:.0f} ms")
print(f"      Inputs : {enc_in_names}")
print(f"      Outputs: {enc_out_names}")

print("[3/5] Loading decoder.dlc (NPU) ...")
t0 = time.time()
decoder = QNNContext("trocr_decoder", DECODER_DLC)
dec_in_names  = decoder.getInputName()
dec_out_names = decoder.getOutputName()
print(f"      Loaded in {(time.time()-t0)*1000:.0f} ms")
print(f"      Inputs : {dec_in_names}")
print(f"      Outputs: {dec_out_names}")


# ── Step 4: Preprocessing ─────────────────────────────────────────────────
def preprocess_image(image_path: str) -> np.ndarray:
    """
    Load and preprocess image for TrOCR encoder.
    The QNN DLC model expects NHWC [1,384,384,3] float32 with value_range [0,1].
    ViTImageProcessor outputs NCHW [1,3,H,W]; we transpose to NHWC.
    Normalization: mean=0.5, std=0.5 -> output range [-1, 1].
    """
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    result = image_processor(images=img, return_tensors="np")
    pv = result["pixel_values"]               # [1, 3, 384, 384] NCHW float32
    print(f"      [DEBUG] pv NCHW shape={pv.shape} min={pv.min():.3f} max={pv.max():.3f}")
    nhwc = pv.transpose(0, 2, 3, 1).astype(np.float32)  # [1, 384, 384, 3] NHWC
    print(f"      [DEBUG] nhwc shape={nhwc.shape} min={nhwc.min():.3f} max={nhwc.max():.3f}")
    return nhwc


# ── Step 5: OCR inference ──────────────────────────────────────────────────
def ocr(image_path: str, verbose: bool = True) -> str:
    """
    Run TrOCR encoder-decoder on an image and return the recognized text.

    KV cache strategy (sliding window):
      - self-attn KV input:  [1, 8, 19, 32]  (past N tokens)
      - self-attn KV output: [1, 8, 20, 32]  (past N+1 tokens)
      - next input:          output[:, :, 1:, :]  (drop oldest, keep last 19)
    """
    if verbose:
        print(f"\n[OCR] Image: {image_path}")

    pixel_values = preprocess_image(image_path)
    if verbose:
        print(f"      pixel_values: shape={pixel_values.shape}  "
              f"min={pixel_values.min():.3f}  max={pixel_values.max():.3f}")

    # ── Encoder ──────────────────────────────────────────────────────────
    t_enc = time.time()
    enc_in_list = [{"pixel_values": pixel_values}[n] for n in enc_in_names]
    enc_outs = encoder.Inference(enc_in_list)
    enc_ms = (time.time() - t_enc) * 1000
    enc_out_dict = dict(zip(enc_out_names, enc_outs))

    if verbose:
        cross_norm = float(np.linalg.norm(np.array(enc_out_dict["kv_cache_key_0"])))
        print(f"      Encoder: {enc_ms:.0f} ms  (cross-KV[0] norm={cross_norm:.1f})")

    # ── Initialize decoder KV caches ────────────────────────────────────
    self_kv_key = [np.zeros((1, NUM_HEADS, SELF_KV_IN_LEN, HEAD_DIM), dtype=np.float32)
                   for _ in range(NUM_LAYERS)]
    self_kv_val = [np.zeros((1, NUM_HEADS, SELF_KV_IN_LEN, HEAD_DIM), dtype=np.float32)
                   for _ in range(NUM_LAYERS)]
    cross_kv_key = [np.array(enc_out_dict[f"kv_cache_key_{i}"], dtype=np.float32)
                    for i in range(NUM_LAYERS)]
    cross_kv_val = [np.array(enc_out_dict[f"kv_cache_val_{i}"], dtype=np.float32)
                    for i in range(NUM_LAYERS)]

    # ── Autoregressive decoding ──────────────────────────────────────────
    current_token = np.array([[BOS_ID]], dtype=np.int32)
    generated_ids = []
    t_dec = time.time()

    for step in range(MAX_GEN_TOKENS):
        index = np.array([step], dtype=np.int32)

        # Build input dict (use getInputName() order — Issue 12)
        dec_in_dict = {
            "index":    index,
            "input_ids": current_token,
        }
        for i in range(NUM_LAYERS):
            dec_in_dict[f"kv_{i}_attn_key"]       = self_kv_key[i]
            dec_in_dict[f"kv_{i}_attn_val"]        = self_kv_val[i]
            dec_in_dict[f"kv_{i}_cross_attn_key"]  = cross_kv_key[i]
            dec_in_dict[f"kv_{i}_cross_attn_val"]  = cross_kv_val[i]

        dec_in_list = [dec_in_dict[n] for n in dec_in_names]
        dec_outs = decoder.Inference(dec_in_list)

        if not dec_outs:
            if verbose:
                print(f"      [WARN] Decoder inference returned empty at step {step}")
            break

        dec_out_dict = dict(zip(dec_out_names, dec_outs))
        next_token_id = int(np.array(dec_out_dict["next_token"], dtype=np.int32).flat[0])

        if next_token_id == EOS_ID:
            if verbose:
                print(f"      EOS at step {step}")
            break

        generated_ids.append(next_token_id)
        current_token[0, 0] = next_token_id

        # Update self-attn KV cache.
        # The decoder output kv_cache [1,8,20,32] contains the updated cache after
        # processing the current token at position `step`.
        # The next step's input needs [1,8,19,32] = the last 19 positions of the output.
        # This is always: output[:,:,1:,:] — drop position 0 (oldest), keep positions 1..19.
        for i in range(NUM_LAYERS):
            new_k = np.array(dec_out_dict[f"kv_cache_key_{i}"], dtype=np.float32)  # [1,8,20,32]
            new_v = np.array(dec_out_dict[f"kv_cache_val_{i}"], dtype=np.float32)
            self_kv_key[i] = new_k[:, :, 1:, :]   # -> [1,8,19,32]
            self_kv_val[i] = new_v[:, :, 1:, :]

    dec_ms = (time.time() - t_dec) * 1000
    n_tokens = len(generated_ids)

    text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    if verbose:
        print(f"      Decoder: {dec_ms:.0f} ms  "
              f"({n_tokens} tokens, {dec_ms/max(n_tokens,1):.1f} ms/tok)")
        print(f"[OCR] Result: \"{text}\"")

    return text


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TrOCR inference on Snapdragon X Elite NPU (QNN DLC)"
    )
    parser.add_argument(
        "--image",
        type=str,
        default=os.path.join(_SCRIPT_DIR, "english.png"),
        help="Path to input image (default: english.png in script directory)"
    )
    args = parser.parse_args()

    print("\n[4/5] Models loaded. Starting OCR inference ...")
    print("=" * 60)

    result = ocr(args.image, verbose=True)

    print("\n" + "=" * 60)
    print("[5/5] TrOCR inference complete on Snapdragon X Elite NPU.")
    print(f"      Final OCR text: \"{result}\"")


if __name__ == "__main__":
    main()
