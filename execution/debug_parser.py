import re
import sys
from bs4 import BeautifulSoup

def debug_file(file_path: str):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    print(f"\n{'='*60}")
    print(f"FILE: {file_path}")
    print(f"SIZE: {len(content)} chars")
    print(f"\n--- FIRST 500 CHARS ---")
    print(repr(content[:500]))
    print(f"\n--- FIRST 500 CHARS (RAW) ---")
    print(content[:500])

    # Try WhatsApp patterns
    patterns = [
        # Standard: 1/15/24, 10:32 AM - Name: msg
        r"\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[AP]M)?\s*-\s*([^:]+):\s*(.+)",
        # EU format: 15.01.24, 10:32 - Name: msg
        r"\d{1,2}\.\d{1,2}\.\d{2,4},\s*\d{1,2}:\d{2}(?:\s*[AP]M)?\s*-\s*([^:]+):\s*(.+)",
        # Bracket format: [1/15/24, 10:32 AM] Name: msg
        r"\[\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?\]\s*([^:]+):\s*(.+)",
        # 24hr EU bracket: [15/01/2024, 10:32:00]
        r"\[\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}:\d{2}\]\s*([^:]+):\s*(.+)",
    ]

    print(f"\n--- TRYING WHATSAPP PATTERNS ---")
    for i, pat in enumerate(patterns):
        hits = 0
        senders = set()
        for line in content.splitlines():
            m = re.match(pat, line.strip())
            if m:
                hits += 1
                senders.add(m.group(1).strip())
        print(f"Pattern {i+1}: {hits} matches, senders: {senders}")

    # Try HTML
    if file_path.lower().endswith((".html", ".htm")):
        print(f"\n--- HTML ANALYSIS ---")
        soup = BeautifulSoup(content, "html.parser")
        all_classes = set()
        for tag in soup.find_all(True):
            for cls in tag.get("class", []):
                all_classes.add(cls)
        print(f"All classes found: {sorted(all_classes)[:50]}")

        divs = soup.find_all("div")
        print(f"Total divs: {len(divs)}")
        print(f"\nFirst 5 divs with class:")
        for d in divs[:20]:
            if d.get("class"):
                print(f"  class={d.get('class')} text={d.get_text(strip=True)[:80]}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python execution/debug_parser.py <your_chat_file>")
    else:
        debug_file(sys.argv[1])
