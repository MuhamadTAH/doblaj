import asyncio
import os
from pathlib import Path

def test_download_logic(output_path):
    print(f"Testing output_path: {output_path}")
    if output_path and output_path.startswith("/static"):
        output_path = output_path.lstrip("/")

    if output_path and "data/jobs/sessions" in output_path.replace("\\", "/"):
        output_path = "data/jobs/sessions" + output_path.replace("\\", "/").split("data/jobs/sessions")[1]

    if not output_path:
        print("EMPTY PATH")
        return

    static_root = Path("static").resolve()
    data_root = Path("data").resolve()
    print(f"static_root: {static_root}")
    print(f"data_root: {data_root}")

    try:
        resolved = Path(output_path).resolve()
        print(f"resolved: {resolved}")
    except (OSError, RuntimeError):
        print("OSError/RuntimeError")
        return
        
    is_safe_path = resolved.is_relative_to(static_root) or resolved.is_relative_to(data_root)
    print(f"is_safe_path: {is_safe_path}")
    
    is_file = resolved.is_file() if resolved else False
    print(f"is_file: {is_file}")

    if not is_safe_path or not is_file:
        print("REJECTED")
    else:
        print("SERVED")

test_download_logic("D:\\Pird\\studio\\dubbing\\data\\jobs\\sessions\\14\\assembled\\final_dubbed.mp4")
test_download_logic("/static/outputs/dubbed_16.mp4")
