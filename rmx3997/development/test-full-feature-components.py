#!/usr/bin/python3
"""Exercise actual changed C functions with explicit host kernel-service shims.

These tests establish component logic, not kernel runtime, KMI or phone boot.
Use the retained /usr/bin/python3 and disk-backed task scratch.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
ROOT = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
OUT = ROOT / 'host-components'
ENV = dict(os.environ, TMPDIR=str(ROOT), PYTHONPYCACHEPREFIX=str(ROOT / 'pycache'))


def function(text, name):
    match = re.search(r'^(?:static|void|bool|int|ssize_t|struct|const)\b[^\n;{]*\b' +
                      name + r'\([^;{}]*?\)\s*(?:__[^\n]+\n\s*)*\{', text, re.M)
    if not match:
        raise ValueError(name)
    start = match.start()
    brace = text.index('{', match.start())
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef int32_t s32;
#define BIT(n) (1UL << (n))
#define min(a,b) ((a) < (b) ? (a) : (b))
#define min_t(t,a,b) min((t)(a),(t)(b))
#define max_t(t,a,b) ((t)(a) > (t)(b) ? (t)(a) : (t)(b))
#define unlikely(a) (a)
'''


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    OUT = parser.parse_args().output
    OUT.mkdir(exist_ok=False)
    records = []

    def run(label, body, inputs):
        src = OUT / (label + '.c')
        exe = OUT / label
        src.write_text(PRELUDE + body)
        argv = ['/usr/bin/cc', '-O2', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-unused-function',
                str(src), '-o', str(exe)]
        log = OUT / (label + '.log')
        with log.open('x') as stream:
            build = subprocess.run(argv, cwd=REPO, env=ENV, stdout=stream, stderr=subprocess.STDOUT)
            result = subprocess.run([str(exe)], cwd=REPO, env=ENV, stdout=stream,
                                    stderr=subprocess.STDOUT) if not build.returncode else None
        records.append({'label': label, 'compile_argv': argv, 'run_argv': [str(exe)],
                        'cwd': str(REPO), 'environment_overrides': {k: ENV[k] for k in ['TMPDIR', 'PYTHONPYCACHEPREFIX']},
                        'compile_exit': build.returncode, 'run_exit': result.returncode if result else None,
                        'log': str(log), 'fixture_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                        'inputs': {n: hashlib.sha256((REPO / n).read_bytes()).hexdigest() for n in inputs}})
        (OUT / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
        if build.returncode or result.returncode:
            raise SystemExit('FAILED ' + label + ': ' + str(log))
        print('PASS', label, flush=True)

    susfs = (REPO / 'fs/susfs.c').read_text()
    helpers = function(susfs, 'susfs_switch_to_ksu_domain') + function(susfs, 'susfs_restore_creds')
    run('susfs-creds', r'''
struct cred { unsigned int refs, domain; } real = {1, 0};
const struct cred *subject = &real;
int allocations, fail_alloc, fail_domain;
static struct cred *prepare_creds(void) {
    if (fail_alloc) return NULL;
    struct cred *c = malloc(sizeof(*c)); assert(c);
    *c = *subject; c->refs = 1; allocations++; return c;
}
static void put_cred(const struct cred *c) {
    struct cred *m = (struct cred *)c;
    if (!--m->refs) { assert(m != &real); free(m); allocations--; }
}
static const struct cred *override_creds(const struct cred *c) {
    const struct cred *old = subject;
    ((struct cred *)c)->refs++; subject = c; return old;
}
static void revert_creds(const struct cred *old) {
    const struct cred *c = subject; subject = old; put_cred(c);
}
static void setup_selinux(const char *name, struct cred *c) {
    assert(!strcmp(name, "u:r:ksu:s0")); if (!fail_domain) c->domain = 1;
}
static bool susfs_is_current_ksu_domain(void) { return subject->domain == 1; }
''' + helpers + r'''
int main(void) {
    for (int i=0; i<1000; i++) {
        const struct cred *a = susfs_switch_to_ksu_domain();
        assert(a == &real && subject != &real && subject->domain == 1);
        const struct cred *b = susfs_switch_to_ksu_domain();
        assert(b && b != &real); susfs_restore_creds(b);
        susfs_restore_creds(a);
        assert(subject == &real && real.domain == 0 && real.refs == 1 && !allocations);
        fail_alloc = 1; assert(!susfs_switch_to_ksu_domain()); fail_alloc = 0;
        fail_domain = 1; assert(!susfs_switch_to_ksu_domain()); fail_domain = 0;
        susfs_restore_creds(NULL); assert(subject == &real && !allocations);
    }
    puts("1000 nested/success/allocation/domain-failure credential cycles; real creds untouched");
}
''', ['fs/susfs.c'])

    hdr = (REPO / 'net/ipv4/tcp_bbr3_compat.h').read_text()
    a = hdr.index('static inline bool tcp_bbr3_skb_valid')
    b = hdr.index('static inline bool tcp_ca_wants_ce_events', a)
    sent = function((REPO / 'net/ipv4/tcp_rate.c').read_text(), 'tcp_rate_skb_sent')
    run('bbr-snapshots', r'''
#define TCPCB_LOST 4
#define TCPCB_IN_FLIGHT_MAX ((1U << 20) - 1)
struct tx { u32 in_flight:30, is_app_limited:1, unused:1; u32 delivered; u64 first_tx_mstamp, delivered_mstamp; };
struct control { unsigned char prefix[24]; struct tx tx; };
struct sk_buff { unsigned char cb[48]; u32 android_kabi_reserved1_padding3; u64 android_kabi_reserved2; u64 stamp; u32 pcount; };
struct tcp_sock { u32 packets_out, delivered, app_limited, lost, delivered_ce, flight; u64 first_tx_mstamp, delivered_mstamp; };
struct sock { struct tcp_sock tp; bool bbr; };
#define tcp_sk(sk) (&(sk)->tp)
#define tcp_bbr3_enabled(sk) ((sk)->bbr)
#define tcp_skb_pcount(skb) ((skb)->pcount)
#define tcp_skb_timestamp_us(skb) ((skb)->stamp)
#define tcp_packets_in_flight(tp) ((tp)->flight)
#define TCP_SKB_CB(skb) ((struct control *)(skb)->cb)
''' + hdr[a:b] + sent + r'''
int main(void) {
    struct sock sk = {0}; struct sk_buff s = {0}, copy = {0};
    u32 rng = 0x3997; sk.bbr = true; sk.tp.packets_out = 1;
    for (unsigned int i=0; i<100000; i++) {
        rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5;
        sk.tp.first_tx_mstamp = (1ULL << 48) + rng;
        sk.tp.delivered_mstamp = (1ULL << 50) + rng;
        sk.tp.lost = rng; sk.tp.delivered_ce = ~rng;
        sk.tp.flight = rng % 1000000; s.pcount = 17;
        TCP_SKB_CB(&s)->tx.in_flight = 1234567;
        tcp_rate_skb_sent(&sk, &s);
        assert(TCP_SKB_CB(&s)->tx.in_flight == 1234567);
        assert(TCP_SKB_CB(&s)->tx.first_tx_mstamp == sk.tp.first_tx_mstamp);
        assert(TCP_SKB_CB(&s)->tx.delivered_mstamp == sk.tp.delivered_mstamp);
        assert(tcp_bbr3_skb_lost(&s) == rng && tcp_bbr3_skb_ce(&s) == ~rng);
        assert(tcp_bbr3_skb_valid(&s));
        assert(tcp_bbr3_skb_inflight(&s) == sk.tp.flight + 17);
        memset(copy.cb, 0x5a, sizeof(copy.cb)); tcp_bbr3_skb_copy(&copy, &s);
        assert(tcp_bbr3_skb_inflight(&copy) == tcp_bbr3_skb_inflight(&s));
        assert(copy.cb[0] == 0x5a && copy.cb[47] == 0x5a);
        sk.bbr = false; tcp_rate_skb_sent(&sk, &s);
        assert(!tcp_bbr3_skb_valid(&s) && TCP_SKB_CB(&s)->tx.in_flight == 1234567);
        sk.bbr = true;
    }
    puts("100000 actual transmit snapshot cases: full counters/timestamps and TCP byte field preserved");
}
''', ['net/ipv4/tcp_bbr3_compat.h', 'net/ipv4/tcp_rate.c'])

    cpufreq = (REPO / 'drivers/cpufreq/cpufreq.c').read_text()
    start = cpufreq.index('struct cpufreq_min_limit {')
    end = cpufreq.index('/* Macros to iterate', start)
    funcs = cpufreq[start:end]
    for name in ['store_scaling_min_freq', 'show_scaling_min_freq_limit', 'store_scaling_min_freq_limit']:
        funcs += function(cpufreq, name)
    run('cpufreq-limit', r'''
#define NR_CPUS 8
struct freq_qos_request { struct { int prio; } pnode; } request = {{300}};
struct cpufreq_policy { unsigned int *related_cpus; struct freq_qos_request *min_freq_req; struct {unsigned int min_freq;} cpuinfo; };
#define cpumask_first(mask) (*(mask))
int fail_qos;
static int freq_qos_update_request(struct freq_qos_request *r, int v) {
    if (fail_qos) return -EIO;
    r->pnode.prio = v; return 1;
}
static int kstrtouint(const char *s, int base, unsigned int *v) {
    char *end; if (*s == '-') return -EINVAL;
    unsigned long x = strtoul(s, &end, base);
    if (end == s || (*end && strcmp(end, "\n")) || x > UINT_MAX) return -EINVAL;
    *v = x; return 0;
}
''' + funcs + r'''
int main(void) {
    unsigned int key = 2; char out[32];
    struct cpufreq_policy p = {&key, &request, {100}};
    assert(store_scaling_min_freq(&p, "900", 3) == 3 && request.pnode.prio == 900);
    assert(store_scaling_min_freq_limit(&p, "400", 3) == 3 && request.pnode.prio == 400);
    assert(store_scaling_min_freq_limit(&p, "800", 3) == 3 && request.pnode.prio == 800);
    assert(store_scaling_min_freq_limit(&p, "2147483647", 10) == 10 && request.pnode.prio == 900);
    assert(store_scaling_min_freq(&p, "200", 3) == 3 && request.pnode.prio == 200);
    assert(store_scaling_min_freq_limit(&p, "99", 2) == -EINVAL);
    assert(store_scaling_min_freq(&p, "-1", 2) == -EINVAL);
    assert(store_scaling_min_freq(&p, "300garbage", 10) == -EINVAL);
    fail_qos=1; assert(store_scaling_min_freq_limit(&p,"500",3)==-EIO);
    assert(request.pnode.prio==200 && min_limits[2].requested==200 && min_limits[2].limit==INT_MAX);
    show_scaling_min_freq_limit(&p,out); assert(!strcmp(out,"2147483647\n"));
    puts("userspace cap/release/restoration/invalid-input/QoS failure cases PASS");
}
''', ['drivers/cpufreq/cpufreq.c'])

    signal = (REPO / 'kernel/signal.c').read_text()
    funcs = ''.join(function(signal, n) for n in ['ptrace_stop', 'ptrace_do_notify', 'ptrace_notify_message', 'ptrace_notify'])
    run('ptrace-message', r'''
#define __releases(x)
#define __acquires(x)
#define TASK_TRACED 8
#define TASK_RUNNING 0
#define CLD_STOPPED 5
#define CLD_TRAPPED 4
#define SIGTRAP 5
#define PTRACE_EVENT_STOP 128
#define JOBCTL_STOP_PENDING 1
#define JOBCTL_TRAP_STOP 2
#define JOBCTL_TRAP_NOTIFY 4
#define JOBCTL_LISTENING 8
typedef struct {int si_signo, si_code, si_pid, si_uid;} kernel_siginfo_t;
struct task {unsigned long ptrace_message, jobctl; int exit_code, task_works; kernel_siginfo_t *last_siginfo; struct {int siglock;} *sighand;} task;
#define current (&task)
int tracer=1, scheduled, tasklist_lock;
unsigned long expected, observed;
#define arch_ptrace_stop_needed(a,b) 0
#define arch_ptrace_stop(a,b) ((void)0)
#define spin_lock_irq(x) ((void)0)
#define spin_unlock_irq(x) ((void)0)
#define read_lock(x) ((void)0)
#define read_unlock(x) ((void)0)
#define set_special_state(x) ((void)0)
#define __set_current_state(x) ((void)0)
#define smp_wmb() ((void)0)
#define task_participate_group_stop(x) false
#define task_clear_jobctl_pending(x,y) ((void)0)
#define task_clear_jobctl_trapping(x) ((void)0)
#define may_ptrace_stop() tracer
#define ptrace_reparented(x) false
#define preempt_disable() ((void)0)
#define cgroup_enter_frozen() ((void)0)
#define preempt_enable_no_resched() ((void)0)
#define cgroup_leave_frozen(x) ((void)0)
#define recalc_sigpending_tsk(x) ((void)0)
#define BUG_ON(x) assert(!(x))
#define clear_siginfo(x) memset(x,0,sizeof(*(x)))
#define task_pid_vnr(x) 77
#define current_uid() 0
#define current_user_ns() 0
#define from_kuid_munged(a,b) 0
static void do_notify_parent_cldstop(struct task *t, bool ptrace, int why) {assert(t->ptrace_message==expected);}
static void freezable_schedule(void) {observed=task.ptrace_message; scheduled++;}
static void task_work_run(void) { task.ptrace_message=0xdead; }
''' + funcs + r'''
int main(void) {
    for (unsigned long i=0;i<1000;i++) {
        expected=0x39970000+i; task.task_works=1;
        ptrace_notify_message((1<<8)|SIGTRAP,expected);
        assert(observed==expected && !task.ptrace_message && !task.last_siginfo);
        expected=0; ptrace_notify(SIGTRAP);
        assert(!observed && !task.ptrace_message);
    }
    tracer=0; expected=99; ptrace_notify_message((1<<8)|SIGTRAP,expected);
    assert(!task.ptrace_message && !task.exit_code);
    tracer=1; expected=0; task.ptrace_message=0xdead;
    ptrace_stop(19,CLD_STOPPED,0,0,NULL); assert(!observed && !task.ptrace_message);
    puts("1000 actual ptrace stop/event/legacy/task-work cycles plus absent-tracer and group-stop cases PASS");
}
''', ['kernel/signal.c'])


if __name__ == '__main__':
    main()
