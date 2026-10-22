"""Proof that no platform credential is inside any hub workspace of ours (prints counts only)."""
import asyncio, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
os.environ.update({"MULTICODE_HUB_SSH": "<hub-user>@<hub-host>",
                   "MULTICODE_HUB_SSH_KEY": "/home/kesha/.ssh/multicode_hub_vps"})
from app import hub_workspace as hw

async def main():
    ssh = hw.HubSsh.from_env()
    known = hw.known_secret_values()
    pat = Path(tempfile.mkstemp(prefix="cred-")[1]); os.chmod(pat, 0o600)
    pat.write_text("\n".join(v for v in known if "\n" not in v) + "\n")
    states = sorted(hw.STATE_DIR.glob("hub-*.json"))
    print("known secret values checked:", len([v for v in known if '\n' not in v]), "workspaces:", len(states))
    for st in states:
        d = hw.WorkspaceState.load(st.stem).remote_dir
        out = await ssh.run(f"grep -rlF -f - {d}; echo ---; find {d} \\( -name '.env*' -o -name '*.pem' -o -name '.git' -o -name 'id_*' -o -name '*.token' \\); true", stdin=pat)
        hits, _, junk = out.decode().partition("---")
        print(st.stem, "files with a platform credential:", len([l for l in hits.splitlines() if l.strip()]),
              "| credential-named/.git files:", len([l for l in junk.splitlines() if l.strip()]))
    pat.unlink()
asyncio.run(main())
