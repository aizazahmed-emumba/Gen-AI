import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from common.groq_client import ask

if __name__ == "__main__":
    result = ask("Say hello in one sentence.")
    print(result)
