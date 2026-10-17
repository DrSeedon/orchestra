import re, sys, pathlib
C = pathlib.Path("/home/kesha/bench910/corpus/.orchestra")
f, h = sys.argv[1], sys.argv[2]
t = (C/f).read_text(); parts = re.split(r"(?m)^(##+ .*)$", t)
for i in range(1, len(parts), 2):
    if parts[i].strip("# ").strip().startswith(h):
        print("=====", f, "|", parts[i]); print(parts[i+1][:int(sys.argv[3]) if len(sys.argv)>3 else 1800]); break
