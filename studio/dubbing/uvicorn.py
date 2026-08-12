import sys
import os

# Intercept and replace literal "$PORT", "${PORT}", or invalid non-digit port strings in sys.argv
port_val = os.environ.get("PORT", "8000")
new_argv = []
i = 0
while i < len(sys.argv):
    arg = sys.argv[i]
    if arg == "--port" and i + 1 < len(sys.argv):
        val = sys.argv[i + 1]
        if not val.isdigit():
            new_argv.append(arg)
            new_argv.append(port_val)
            i += 2
            continue
    elif arg in ("$PORT", "${PORT}"):
        new_argv.append(port_val)
        i += 1
        continue
    new_argv.append(arg)
    i += 1

sys.argv = new_argv

# Temporarily remove current directory from sys.path to load real uvicorn module
cwd = os.path.abspath(os.getcwd())
sys.path = [p for p in sys.path if p and os.path.abspath(p) != cwd]

import uvicorn.main
sys.exit(uvicorn.main.main())
