"""Paid game generation belongs to an explicit live command, never ordinary pytest."""
import json
from pathlib import Path
import subprocess
import sys


def test_live_example_defaults_to_zero_calls_and_creates_no_output(tmp_path):
    output=tmp_path/'live'
    script=Path(__file__).parents[1]/'scripts/run_novel_game_live_example.py'
    result=subprocess.run([sys.executable,'-B',str(script),'--output',str(output),'--env-file',str(tmp_path/'missing.env')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    plan=json.loads(result.stdout)
    assert plan['calls']==0 and plan['builder']=='novel-to-game'
    assert plan['model']=='gpt-6.1-sol' and plan['effort']=='low' and plan['human_selection_ui'] is True
    assert not output.exists()
