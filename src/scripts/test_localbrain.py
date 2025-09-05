import requests
import base64
import json

API_KEY: str = "sk-535b1765b2c24696ae928e7efb391443" # Note by SysWhite: please use env vars in prod.
IMAGE_PATH: str = "./src/scripts/test2.jpeg"

def convert_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def chat_with_model() -> requests.Response:

    url = 'https://ai.syswhite.dev/api/chat/completions'
    headers = {
        'Authorization': f'Bearer {API_KEY}', 
        'Content-Type': 'application/json'
    }
    payload = {
      "model": "gemma3:12b",
      "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Task: Convert the entire page from an image or PDF 1:1 into Markdown text. Rules: Reading order: First analyze the columns and assemble the text in the correct order (from left to right, top to bottom). Text transfer: Transfer the text without omitting or adding anything—exactly like an OCR scanner. No changes to content, no summaries. Formatting: Headings → Markdown headings (#, ##, ...). Tables → Markdown tables, assign columns correctly. Lists → display with - or 1. Retain emphasis (bold, italics) if recognizable. Images and graphics: Insert them as Markdown image placeholders: ![Description](imageX.png). Additionally, create a short textual description of the content (e.g., “Bar chart showing sales figures for 2023”). Accuracy: Do not invent anything, do not interpret anything. If something is illegible, mark it as [illegible]. Goal: A perfect, cleanly formatted Markdown document that reproduces the page as it appears in the original. No additional comments. Translated with DeepL.com (free version)\n\n"},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," + convert_image_to_base64(IMAGE_PATH)
                    }}
                ]
            }
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    return response

def _print_response(resp: requests.Response) -> None:
    print("--- HTTP Status ---")
    print(resp.status_code)
    print("\n--- Headers ---")
    try:
        print(dict(resp.headers))
    except Exception:
        print("[Konnte Header nicht darstellen]")
    print("\n--- Body (raw) ---")
    try:
        # Gib den Body aus; ggf. gekürzt, falls sehr groß
        text = resp.text
        print(text if len(text) <= 8000 else text[:8000] + "\n...[gekürzt]...")
    except Exception as exc:
        print(f"[Konnte Body nicht lesen: {exc}]")
    # Optional: JSON versuchen
    print("\n--- JSON (parsed, optional) ---")
    try:
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False)[:8000])
    except Exception as exc:
        print(f"[Keine valide JSON-Response: {exc}]")


def main() -> None:
    resp = chat_with_model()
    _print_response(resp)

if __name__ == "__main__":
    main()