#!/usr/bin/python3
"""Test the actual multi-codec frontend with host LZO/Zstd reference codecs.

Host liblzo supplies LZO1X, not the kernel's LZO-RLE encoder. This exercises
frontend framing, selection, decoder dispatch and errors, not kernel codec
performance, OEM execution, or exact firmware/source equivalence.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parents[2]
root = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
out = root / 'oem-multi-codec-host'
out.mkdir(exist_ok=False)
source = repo / 'crypto/zram_multi.c'
text = source.read_text()
body = text[text.index('#define ZRAM_MULTI_HEADER'):text.index('static struct crypto_alg zram_multi_alg')]
shim = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <lzo/lzo1x.h>
#include <zstd.h>
typedef uint8_t u8;
#define PAGE_SIZE 4096
#define GFP_KERNEL 0
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
struct crypto_tfm {void *ctx;};
#define crypto_tfm_ctx(tfm) ((tfm)->ctx)
struct crypto_comp {int dense; void *workspace;};
static int live, scratch_live, alloc_call, fail_alloc, fail_scratch, fail_fast, fail_dense;
static struct crypto_comp *crypto_alloc_comp(const char *name,int a,int b) {
    if (++alloc_call == fail_alloc) return (void *)(intptr_t)-ENOMEM;
    struct crypto_comp *c=malloc(sizeof(*c)); assert(c); live++;
    c->dense=!strcmp(name,"zstd");
    assert(c->dense || !strcmp(name,"lzo-rle"));
    c->workspace=malloc(LZO1X_1_MEM_COMPRESS); assert(c->workspace); return c;
}
static void crypto_free_comp(struct crypto_comp *c) {free(c->workspace);free(c);live--;}
static void *kmalloc(size_t size,int flags) {
    if (fail_scratch) return NULL;
    void *p=malloc(size); if(p)scratch_live++; return p;
}
static void kfree(void *p) {if(p){scratch_live--;free(p);}}
static int crypto_comp_compress(struct crypto_comp *c,const u8 *src,unsigned int len,u8 *dst,unsigned int *cap) {
    if ((c->dense && fail_dense) || (!c->dense && fail_fast)) return -EIO;
    if(c->dense) {
        size_t n=ZSTD_compress(dst,*cap,src,len,3);
        if(ZSTD_isError(n))return -ENOSPC;
        *cap=n;return 0;
    }
    u8 tmp[8192];lzo_uint n=sizeof(tmp);
    int err=lzo1x_1_compress(src,len,tmp,&n,c->workspace);
    if(err!=LZO_E_OK || n>*cap)return -ENOSPC;
    memcpy(dst,tmp,n);*cap=n;return 0;
}
static int crypto_comp_decompress(struct crypto_comp *c,const u8 *src,unsigned int len,u8 *dst,unsigned int *cap) {
    if(c->dense) {
        size_t n=ZSTD_decompress(dst,*cap,src,len);
        if(ZSTD_isError(n))return -EINVAL;
        *cap=n;return 0;
    }
    lzo_uint n=*cap;int err=lzo1x_decompress_safe(src,len,dst,&n,NULL);
    if(err!=LZO_E_OK)return -EINVAL;
    *cap=n;return 0;
}
'''
tests = r'''
int main(void) {
    assert(lzo_init()==LZO_E_OK);
    struct zram_multi_ctx ctx={0};struct crypto_tfm tfm={&ctx};
    for(int which=1;which<=2;which++) {
        fail_alloc=which;alloc_call=0;
        assert(zram_multi_init(&tfm)==-ENOMEM && !live && !scratch_live);
    }
    fail_alloc=0;fail_scratch=1;alloc_call=0;
    assert(zram_multi_init(&tfm)==-ENOMEM && !live && !scratch_live);
    fail_scratch=0;assert(!zram_multi_init(&tfm));
    u8 input[4096],packed[8192+32],stored[8192],decoded[4096+32];
    unsigned int rng=0x3997, count[2]={0};
    for(int i=0;i<1000;i++) {
        for(unsigned int j=0;j<sizeof(input);j++) {
            rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
            input[j]= i%3==0 ? 0 : i%3==1 ? (j%31) : rng;
        }
        memset(packed,0xa5,sizeof(packed)); memset(decoded,0x5a,sizeof(decoded));
        unsigned int n=8192, size=4096;
        assert(!zram_multi_compress(&tfm,input,4096,packed,&n));
        assert(n<=8192 && packed[3]<=1);count[packed[3]]++;
        /* Hybrid swap transports compressed bytes without decoding them. */
        memcpy(stored,packed,n);
        assert(!zram_multi_decompress(&tfm,stored,n,decoded,&size));
        assert(size==4096 && !memcmp(input,decoded,4096));
        for(int j=0;j<32;j++)assert(packed[8192+j]==0xa5 && decoded[4096+j]==0x5a);
        size=4095; assert(zram_multi_decompress(&tfm,stored,n,decoded,&size)==-EINVAL);
        size=4096;stored[3]=2;assert(zram_multi_decompress(&tfm,stored,n,decoded,&size)==-EINVAL);
    }
    /* Force each frontend branch using real reference codec output. */
    for(int mode=0;mode<2;mode++) {
        fail_dense=!mode;fail_fast=mode;
        unsigned int n=8192,size=4096;
        assert(!zram_multi_compress(&tfm,input,4096,packed,&n));
        assert(packed[3]==mode);assert(!zram_multi_decompress(&tfm,packed,n,decoded,&size));
        assert(!memcmp(input,decoded,4096));
    }
    fail_fast=fail_dense=1;
    unsigned int n=8192;assert(zram_multi_compress(&tfm,input,4096,packed,&n)==-ENOSPC);
    fail_fast=fail_dense=0;n=4;assert(zram_multi_compress(&tfm,input,4096,packed,&n)==-ENOSPC);
    n=8192;assert(zram_multi_compress(&tfm,input,4095,packed,&n)==-EINVAL);
    unsigned int size=4096;assert(zram_multi_decompress(&tfm,packed,4,decoded,&size)==-EINVAL);
    zram_multi_exit(&tfm);assert(!live && !scratch_live);
    printf("PASS:1000 reference-codec page roundtrips; selection counts fast=%u dense=%u; both decoder branches, bounds, malformed headers and init unwind; LZO=%s Zstd=%s\n",count[0],count[1],lzo_version_string(),ZSTD_versionString());
}
'''
fixture = out / 'frontend.c'
fixture.write_text(shim + body + tests)
argv = ['/usr/bin/cc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
        str(fixture), '-llzo2', '-lzstd', '-o', str(out / 'frontend')]
env = dict(os.environ, TMPDIR=str(root), PYTHONPYCACHEPREFIX=str(root / 'pycache'))
with (out / 'result.log').open('x') as stream:
    build = subprocess.run(argv, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.run([str(out / 'frontend')], cwd=repo, env=env,
                            stdout=stream, stderr=subprocess.STDOUT) if not build.returncode else None
record = {'scope': __doc__, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'compile_argv': argv, 'run_argv': [str(out / 'frontend')], 'cwd': str(repo),
          'environment_overrides': {k: env[k] for k in ['TMPDIR', 'PYTHONPYCACHEPREFIX']},
          'compile_exit': build.returncode, 'run_exit': result.returncode if result else None,
          'log': str(out / 'result.log'), 'kernel_runtime_proof': False}
(out / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
raise SystemExit(build.returncode or result.returncode)
