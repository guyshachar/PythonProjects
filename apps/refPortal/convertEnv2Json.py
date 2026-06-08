import json
import sys

prefix = sys.argv[1]
with open(f"{prefix}") as f:
    lines = f.readlines()

env_dict = {
    "Variables": {
        line.split("=", 1)[0]: line.split("=", 1)[1].strip().rstrip(",")
        for line in lines if "=" in line
    }
}

with open(f"{prefix}.json", "w") as out:
    json.dump(env_dict, out, indent=2)
