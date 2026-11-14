#!/usr/bin/python3
"""Controlled child groups only; no real memory pressure or swap changes."""
import argparse,importlib.util,json,pathlib,sys
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();root=pathlib.Path(a.output);root.mkdir(exist_ok=False)
spec=importlib.util.spec_from_file_location('guard',pathlib.Path(__file__).with_name('resource-guard.py'));guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
results={}
for leader_code in [0,7]:
 name='leader-'+str(leader_code);pidfile=root/(name+'.pid')
 program='import os,time,pathlib; p=os.fork(); (time.sleep(30) if p==0 else (pathlib.Path('+repr(str(pidfile))+').write_text(str(p)),os._exit('+str(leader_code)+')))'
 code=guard.guarded([sys.executable,'-c',program],root/(name+'.log'),root/(name+'.json'))
 # A command that exits with live descendants is aborted (125), whatever its own code.
 record=json.loads((root/(name+'.json')).read_text())
 assert code==125 and record['reason']=='command exited with live descendants',(code,record['reason'])
 child=int(pidfile.read_text());stat=pathlib.Path('/proc')/str(child)/'stat'
 assert not stat.exists() or stat.read_text().split()[2]=='Z','orphan child alive'
 results[name]='PASS parent exit with live child aborts and kills the child'
for leader_code in [0,7]:
 name='clean-'+str(leader_code)
 code=guard.guarded([sys.executable,'-c','import os; os._exit(%d)'%leader_code],root/(name+'.log'),root/(name+'.json'))
 record=json.loads((root/(name+'.json')).read_text())
 assert code==leader_code and record['reason']=='completed',(code,record['reason'])
 results[name]='PASS exit code passed through'
(root/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(results)
