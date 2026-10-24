import sys
sys.path.insert(0, ".")
from core.tts import normalize_tts_rate as n

for v in ("25", "+25%", "-25%", "+0%", "0", "", None, "+200%", "-150%"):
    try:
        print(repr(v), "->", repr(n(v)))
    except Exception as e:
        print(repr(v), "-> EXC", type(e).__name__, e)
