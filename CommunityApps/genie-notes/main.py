"""
Genie Notes — summarize and tidy plain-text notes on-device with a local Genie LLM.

A minimal, dependency-light reference for the QAI AppBuilder Genie flow: it talks
to the locally running GenieAPIService (OpenAI-compatible) at
http://127.0.0.1:8910/v1/chat/completions and prints a summary + action items.
Your notes never leave the device.

Prerequisite:
    Start GenieAPIService first (see samples/genie/python/GenieAPIService.py or
    the WebUI launcher). By default it listens on port 8910.

Usage:
    python main.py [path/to/notes.txt]
    # with no argument, a short built-in sample note is used.

Standards & review criteria: ../../docs/community.md
"""

import json
import sys
import urllib.error
import urllib.request

# Local Genie service — OpenAI-compatible chat completions endpoint.
GENIE_URL = "http://127.0.0.1:8910/v1/chat/completions"
MODEL = "llama-3.2-3b-instruct"  # any model loaded by your GenieAPIService

SAMPLE_NOTE = """\
Standup 7/22 — Discussed the Q3 on-device demo. Ana will finish the NPU
benchmark script by Thursday. We agreed to drop the cloud fallback for the
offline showcase. Ravi flagged the model download is 1.9GB — need a progress
bar. Next sync Friday 10am.
"""

SYSTEM_PROMPT = (
    "You are a concise note-taking assistant. Given raw notes, reply with:\n"
    "1) a 2-3 sentence summary, then\n"
    "2) an 'Action items:' list with owner and due date where available.\n"
    "Keep it short. Do not invent facts."
)


def summarize(note_text: str) -> str:
    """Send the note to the local Genie LLM and return the model's reply text."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": note_text},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    req = urllib.request.Request(
        GENIE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            note_text = f.read()
        print(f"Summarizing: {sys.argv[1]}\n")
    else:
        note_text = SAMPLE_NOTE
        print("No file given — using the built-in sample note.\n")

    try:
        result = summarize(note_text)
    except urllib.error.URLError as exc:
        print("Could not reach the Genie service at", GENIE_URL)
        print("Start GenieAPIService first (it listens on port 8910). Details:", exc)
        sys.exit(1)

    print("=" * 60)
    print(result)
    print("=" * 60)


if __name__ == "__main__":
    main()
