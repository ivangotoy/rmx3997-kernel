#!/usr/bin/python3
"""Execute disassembled ARM64 object instructions in a bounded scalar host model.

This is an instruction-semantics simulation of the actual object, not ARM64
hardware/QEMU runtime or a performance benchmark. Every load is bounds checked.
"""
import argparse,hashlib,json,random,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--object',required=True);p.add_argument('--output',required=True);a=p.parse_args()
out=Path(a.output);out.mkdir(exist_ok=False)
obj=Path(a.object);disassembler='/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/kernel/prebuilts/clang/host/linux-x86/clang-r450784e/bin/llvm-objdump'
argv=[disassembler,'-d','--no-show-raw-insn',str(obj)]
dis=subprocess.check_output(argv,text=True);(out/'memcmp.asm').write_text(dis)
ins={}
for line in dis.splitlines():
 m=re.match(r'\s*([0-9a-f]+):\s+(\S+)\s*(.*)',line)
 if m:
  op=m[2];operands=m[3].split(' <',1)[0];args=[s.strip() for s in re.findall(r'\[[^]]+\]|[^,\s][^,]*',operands)]
  assert not re.search(r'\b[vqds]\d+\b',operands),'FPSIMD operand'
  ins[int(m[1],16)]=(op,args)
assert ins and len(ins)<100
loads=0

def execute(left,right,align1,align2):
 global loads
 n=len(left);r=[0]*31;r[:3]=[0x100000+align1,0x200000+align2,n];base1,base2=r[:2];pc=min(ins);z=False;c=False
 def value(s):return int(s.removeprefix('#'),0) if not s.startswith(('w','x')) else r[int(s[1:])]&((1<<(32 if s[0]=='w' else 64))-1)
 def store(s,v):r[int(s[1:])]=v&((1<<(32 if s[0]=='w' else 64))-1)
 def cond(s):return {'eq':z,'ne':not z,'lo':not c,'hi':c and not z,'ls':not c or z}[s]
 def load(addr,size):
  global loads
  for base,data in [(base1,left),(base2,right)]:
   if base<=addr and addr+size<=base+len(data):loads+=1;return int.from_bytes(data[addr-base:addr-base+size],'little')
  raise AssertionError(('out of bounds load',n,addr,size,pc))
 for step in range(10000):
  op,args=ins[pc];pc+=4
  if op in ['hint','nop']:continue
  if op=='ret':
   v=r[0]&0xffffffff;return v-(1<<32) if v&(1<<31) else v
  if op=='cmp':x,y=map(value,args);z=x==y;c=x>=y
  elif op=='ccmp':
   if cond(args[3]):x=value(args[0]);y=value(args[1]);z=x==y;c=x>=y
   else:flags=value(args[2]);z=bool(flags&4);c=bool(flags&2)
  elif op in ['add','sub','subs']:
   x=value(args[1]);y=value(args[2]);store(args[0],x+y if op=='add' else x-y)
   if op=='subs':z=x==y;c=x>=y
  elif op=='mov':store(args[0],value(args[1]))
  elif op=='rev':store(args[0],int.from_bytes(value(args[1]).to_bytes(8,'little'),'big'))
  elif op=='csel':store(args[0],value(args[1] if cond(args[3]) else args[2]))
  elif op=='cset':store(args[0],int(cond(args[1])))
  elif op=='cneg':store(args[0],-value(args[1]) if cond(args[2]) else value(args[1]))
  elif op=='b':pc=value(args[0])
  elif op.startswith('b.'):
   if cond(op[2:]):pc=value(args[0])
  elif op=='tbz':
   if not value(args[0])&(1<<value(args[1])):pc=value(args[2])
  elif op in ['ldp','ldr','ldur','ldrh','ldrb','ldurb']:
   mem=args[-1].strip('[]').split(',');addr=value(mem[0].strip())+(value(mem[1].strip()) if len(mem)>1 else 0)
   width=1 if op in ['ldrb','ldurb'] else 2 if op=='ldrh' else 4 if args[0][0]=='w' else 8
   store(args[0],load(addr,width))
   if op=='ldp':store(args[1],load(addr+width,width))
  else:raise AssertionError(op)
 raise AssertionError('loop')

rng=random.Random(3997);cases=0
for n in list(range(257))+[511,512,513,1023,1024,4095,4096]:
 left=bytes(rng.randrange(256) for _ in range(n))
 positions=range(n) if n<=128 else sorted({0,n//2,n-1})
 inputs=[left]+[left[:i]+bytes([left[i]^0x80])+left[i+1:] for i in positions]
 for right in inputs:
  result=execute(left,right,rng.randrange(16),rng.randrange(16));expected=(left>right)-(left<right)
  assert (result>0)-(result<0)==expected,(n,result,expected)
  cases+=1
result={'result':'PASS','scope':__doc__,'cases':cases,'bounds_checked_loads':loads,'object_sha256':hashlib.sha256(obj.read_bytes()).hexdigest(),'disassembly_argv':argv,'FPSIMD_operands':0}
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
