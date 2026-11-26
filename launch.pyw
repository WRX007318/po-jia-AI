"""Windows GUI entry point. Keeps console windows hidden."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))
from app.main import Workbench

if __name__ == "__main__":
    Workbench().mainloop()
