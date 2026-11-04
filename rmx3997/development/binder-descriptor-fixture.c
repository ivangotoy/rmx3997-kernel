/* Host-only differential fixture for actual old/new allocator function bodies.
 * Minimal BST operations preserve ordering/ownership, not kernel RB balancing.
 */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
#include <stdbool.h>
struct rb_node { struct rb_node *rb_left, *rb_right, *parent; };
struct rb_root { struct rb_node *rb_node; };
#define rb_entry(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
static void rb_link_node(struct rb_node *n, struct rb_node *parent, struct rb_node **p)
{ n->rb_left=n->rb_right=NULL;n->parent=parent;*p=n; }
#define rb_insert_color(n,r) ((void)0)
static struct rb_node *rb_first(struct rb_root *r)
{ struct rb_node *n=r->rb_node; if(n)while(n->rb_left)n=n->rb_left;return n; }
static struct rb_node *rb_next(struct rb_node *n)
{
 if(n->rb_right){n=n->rb_right;while(n->rb_left)n=n->rb_left;return n;}
 while(n->parent && n==n->parent->rb_right)n=n->parent;
 return n->parent;
}
struct binder_proc;
struct binder_node { int refs; };
struct binder_context { struct binder_node *binder_context_mgr_node; };
struct binder_ref {
 struct { u32 debug_id,desc; } data;
 struct binder_proc *proc;struct binder_node *node;
 struct rb_node rb_node_node,rb_node_desc;int node_entry;
};
struct dbitmap { bool enabled; uint64_t used; };
struct binder_proc { struct rb_root refs_by_node,refs_by_desc;struct binder_context *context;int tsk,pid;struct dbitmap dmap; };
static struct binder_proc *proc_wrapper(struct binder_proc *p){return p;}
static void dbitmap_free(struct dbitmap *d){d->enabled=false;d->used=0;}
static int binder_last_id;
static int atomic_inc_return(int *v){return ++*v;}
#define binder_stats_created(x) ((void)0)
#define binder_node_lock(x) ((void)0)
#define binder_node_unlock(x) ((void)0)
#define hlist_add_head(x,y) ((void)0)
#define binder_debug(...) ((void)0)
#define trace_android_vh_binder_new_ref(...) ((void)0)
#define BUG() abort()
static int mode,inject_retry,retried;
static bool trace_android_vh_binder_find_desc_enabled(void){return mode>=1 && mode<=3;}
static void insert_desc(struct binder_proc *p,struct binder_ref *r)
{
 struct rb_node **n=&p->refs_by_desc.rb_node,*parent=NULL;
 while(*n){parent=*n;struct binder_ref *v=rb_entry(*n,struct binder_ref,rb_node_desc);
  if(v->data.desc==r->data.desc)abort();n=r->data.desc<v->data.desc?&(*n)->rb_left:&(*n)->rb_right;}
 rb_link_node(&r->rb_node_desc,parent,n);
}
static void trace_android_vh_binder_find_desc(struct binder_proc *p,u32 *desc,struct rb_node *node,bool *create)
{
 if(mode==2)*desc=17;
 if(mode==3||mode==4){*desc=100;struct binder_ref *r=rb_entry(node,struct binder_ref,rb_node_desc);insert_desc(p,r);*create=false;}
}
static u32 free_desc(struct binder_proc *p)
{
 u32 id=1;for(struct rb_node *n=rb_first(&p->refs_by_desc);n;n=rb_next(n)){
  struct binder_ref *r=rb_entry(n,struct binder_ref,rb_node_desc);
  if(r->data.desc>id)break;id=r->data.desc+1;
 }return id;
}
static int get_ref_desc_olocked(struct binder_proc *p,struct binder_node *n,u32 *out)
{
 if(inject_retry&&!retried++){return -EAGAIN;}
 if(n==p->context->binder_context_mgr_node){*out=0;return 0;}
 *out=free_desc(p);
 if(p->dmap.enabled){*out=1;while(p->dmap.used&(1ULL<<*out))++*out;p->dmap.used|=1ULL<<*out;}
 return 0;
}
/* ACTUAL_FUNCTIONS */
static u32 execute(unsigned mask,int which,bool manager,bool retry)
{
 struct binder_node nodes[10]={0};struct binder_ref refs[9]={0};
 struct binder_context ctx={.binder_context_mgr_node=manager?&nodes[9]:NULL};
 struct binder_proc p={.context=&ctx,.dmap={.enabled=true,.used=1}};
 for(unsigned i=0;i<8;i++)if(mask&(1U<<i)){
  struct binder_ref *r=&refs[i];r->node=&nodes[i];r->data.desc=i+1;r->proc=&p;
  struct rb_node **n=&p.refs_by_node.rb_node,*parent=NULL;
  while(*n){parent=*n;struct binder_ref *v=rb_entry(*n,struct binder_ref,rb_node_node);
   n=r->node<v->node?&(*n)->rb_left:&(*n)->rb_right;}
  rb_link_node(&r->rb_node_node,parent,n);insert_desc(&p,r);p.dmap.used|=1ULL<<(i+1);
 }
 inject_retry=retry;retried=0;
 struct binder_ref *answer=which?binder_new(&p,&nodes[9],&refs[8]):binder_old(&p,&nodes[9],&refs[8]);
 if(answer!=&refs[8])abort();
 unsigned count=0;u32 last=0;
 for(struct rb_node *n=rb_first(&p.refs_by_desc);n;n=rb_next(n)){
  struct binder_ref *r=rb_entry(n,struct binder_ref,rb_node_desc);
  if(count&&r->data.desc<=last)abort();last=r->data.desc;count++;
 }
 if(count!=(unsigned)__builtin_popcount(mask)+1)abort();
 if(which&&mode&&p.dmap.enabled)abort();
 return answer->data.desc;
}
int main(void)
{
 unsigned cases=0;
 for(unsigned mask=0;mask<256;mask++)for(mode=0;mode<5;mode++)
 for(int cm=0;cm<2;cm++)for(int retry=0;retry<2;retry++){
  u32 old=execute(mask,0,cm,retry),now=execute(mask,1,cm,retry);
  if(old!=now){printf("FAIL mask=%u mode=%d cm=%d retry=%d old=%u new=%u\n",mask,mode,cm,retry,old,now);return 1;}
  cases++;
 }
 printf("PASS cases=%u actual old/new bodies, descriptor identity and ownership\n",cases);return 0;
}
