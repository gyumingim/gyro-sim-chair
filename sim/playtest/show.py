import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
print(r["phases"][:30])
for x in r["said"][: int(sys.argv[2]) if len(sys.argv) > 2 else 40]:
    print(x["t"], x["phase"], x["text"][:110])
