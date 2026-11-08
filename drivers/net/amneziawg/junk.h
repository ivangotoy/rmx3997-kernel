#ifndef _AWG_JUNK_H
#define _AWG_JUNK_H

#include <linux/list.h>
#include <linux/mutex.h>

struct amn_wg_peer;

typedef void(*amn_jp_modifier_func)(char*, int, struct amn_wg_peer*);

struct amn_jp_tag
{
    u8* pkt;
    amn_jp_modifier_func func;
    struct list_head head;
    int pkt_size;
};

void jp_tag_free(struct amn_jp_tag* tag);
int jp_parse_tags(char* str, struct list_head* head);

struct amn_jp_modifier
{
    amn_jp_modifier_func func;
    char* buf;
    int buf_len;
};

struct amn_jp_spec
{
    char *desc;
    u8 *pkt;
    struct amn_jp_modifier *mods;
    struct mutex lock;
    int pkt_size;
    int mods_size;
};

void jp_spec_free(struct amn_jp_spec* spec);
int jp_spec_setup(struct amn_jp_spec* spec, const char* desc);
void jp_spec_applymods(struct amn_jp_spec* spec, struct amn_wg_peer* peer);

#endif