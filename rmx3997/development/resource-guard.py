#!/usr/bin/python3
"""Abort the complete build process group before host memory pressure."""
import argparse,json,os,pathlib,signal,subprocess,sys,time,threading
FLOOR=8*1024**3
def available():
    data=dict(line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())
    return int(data['MemAvailable'].split()[0])*1024
def terminate(group):
    for sig in [signal.SIGSTOP,signal.SIGKILL]:
        try:os.killpg(group,sig)
        except ProcessLookupError:pass
def guarded(argv,log,result,simulate=False):
    start=time.time();minimum=available();events=[];proc=None
    record={'argv':argv,'cwd':os.getcwd(),'memory_floor_bytes':FLOOR,'poll_seconds':0.2,'started_utc':time.strftime('%FT%TZ',time.gmtime()),'test_only_injected_pressure':simulate}
    if minimum<FLOOR:raise RuntimeError('Insufficient initial MemAvailable for build guard')
    def interrupted(sig,frame):
        if proc is not None:terminate(proc.pid)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    code=1;reason='unstarted'
    try:
        with open(log,'xb',buffering=0) as f:
            proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
            log_limit=64*1024*1024
            log_full=threading.Event()
            def collect():
                retained=0
                while True:
                    chunk=proc.stdout.read(65536)
                    if not chunk:break
                    keep=min(len(chunk),log_limit-retained)
                    if keep:f.write(chunk[:keep]);retained+=keep
                    if keep<len(chunk):
                        log_full.set();terminate(proc.pid)
                        break
            collector=threading.Thread(target=collect,daemon=True)
            collector.start()
            record['log_limit_bytes']=log_limit
            record['process_group']=proc.pid
            print('guard started',proc.pid,'floorGiB',FLOOR//1024**3,flush=True)
            next_heartbeat=0
            while proc.poll() is None:
                real=available();minimum=min(minimum,real);elapsed=time.time()-start
                observed=0 if simulate and elapsed>0.8 else real
                if log_full.is_set():
                    reason='log_limit';code=125;break
                if observed<FLOOR:
                    events.append({'elapsed':elapsed,'MemAvailable_actual':real,'observed_for_test':observed,'action':'SIGSTOP then SIGKILL process group'})
                    terminate(proc.pid);reason='memory_floor';proc.wait(timeout=10);code=137;break
                if elapsed>5400:
                    terminate(proc.pid);reason='wall_limit';proc.wait(timeout=10);code=124;break
                if elapsed>=next_heartbeat:
                    print('guard heartbeat elapsed_s=%d available_GiB=%.2f'%(elapsed,real/1024**3),flush=True);next_heartbeat=elapsed+30
                time.sleep(0.2)
            else:
                code=proc.returncode;reason='completed'
            # The leader may exit leaving compiler grandchildren behind.
            terminate(proc.pid)
            proc.wait(timeout=10)
            collector.join(timeout=10)
            if collector.is_alive():raise RuntimeError('log collector did not finish')
            if log_full.is_set():code=125;reason='log_limit'
    except BaseException as e:
        if proc is not None:terminate(proc.pid);proc.wait(timeout=10)
        reason=repr(e);code=130
    finally:
        if proc is not None:terminate(proc.pid)
        record.update(exit_code=code,reason=reason,elapsed_seconds=time.time()-start,minimum_actual_MemAvailable_bytes=minimum,events=events,finished_utc=time.strftime('%FT%TZ',time.gmtime()))
        group=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
        record['cgroup']={name:(group/name).read_text().strip() for name in ['memory.high','memory.max','memory.swap.max','memory.events','memory.peak','memory.swap.peak'] if (group/name).exists()}
        pathlib.Path(result).write_text(json.dumps(record,indent=2)+'\n')
    print('guard finished',reason,'exit',code,flush=True)
    return code
def selftest(root):
    root=pathlib.Path(root);root.mkdir(parents=True,exist_ok=True);pidfile=root/'child.pid'
    program='import os,time,pathlib; p=os.fork(); pathlib.Path('+repr(str(pidfile))+').write_text(str(p)) if p else None; time.sleep(30)'
    result=root/'resource-guard-selftest.json'
    code=guarded([sys.executable,'-c',program],root/'resource-guard-selftest.log',result,True)
    assert code==137 and pidfile.exists()
    child=int(pidfile.read_text());status=pathlib.Path('/proc')/str(child)/'stat'
    assert not status.exists() or status.read_text().split()[2]=='Z','descendant still running'
    rec=json.loads(result.read_text());assert rec['events'] and rec['reason']=='memory_floor'
    print('PASS: injected low-memory sensor killed parent and forked descendant; no memory pressure generated')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test');p.add_argument('--log');p.add_argument('--result');p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.self_test:selftest(a.self_test)
    else:
        argv=a.argv[1:] if a.argv[:1]==['--'] else a.argv
        if not argv or not a.log or not a.result:p.error('command, --log and --result required')
        sys.exit(guarded(argv,a.log,a.result))
