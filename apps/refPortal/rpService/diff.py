import os
import json
import sys
import asyncio
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers

class Diff():
    def __init__(self):
        pass

    async def start(self):
        prev = None
        current = None
        with open('./prev.json', 'r') as file:
            data = file.read().strip()
            data = eval(data)
            prev = json.loads(data)
        with open('./current.json', 'r') as file:
            data = file.read().strip()
            data = eval(data)
            current = json.loads(data)

        for pk in prev:
            prevRow = prev[pk]
            currentRow = current[pk]
            for key in prevRow:
                prevProp = prevRow[key]
                currentProp = currentRow[key]
                if prevProp != currentProp:
                    pass
                pass
            pass

if __name__ == "__main__":
    app = None
    try:
        print("Hello RefPortalllll")
        diff = Diff()
        asyncio.run(diff.start())
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass