"""Record reviewed upstream bytes so container builds can verify the skill without Git."""
import hashlib
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
dependency=root/'deps/novel-to-game'
if subprocess.check_output(['git','-C',str(dependency),'status','--porcelain'],text=True).strip():
    raise SystemExit('NovelToGame has local changes; keep the upstream dependency unmodified')
value=dict(revision=subprocess.check_output(['git','-C',str(dependency),'rev-parse','HEAD'],text=True).strip(),
    files={p.relative_to(dependency).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted((dependency/'skills').rglob('*.md'))})
(root/'deps/novel-to-game.lock.json').write_text(json.dumps(value,indent=2)+'\n')
