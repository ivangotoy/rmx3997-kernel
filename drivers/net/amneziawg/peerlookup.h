/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Copyright (C) 2015-2019 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
 */

#ifndef _WG_PEERLOOKUP_H
#define _WG_PEERLOOKUP_H

#include "messages.h"

#include <linux/hashtable.h>
#include <linux/mutex.h>
#include <linux/siphash.h>

struct amn_wg_peer;

struct amn_pubkey_hashtable {
	/* TODO: move to rhashtable */
	DECLARE_HASHTABLE(hashtable, 11);
	siphash_key_t key;
	struct mutex lock;
};

struct amn_pubkey_hashtable *wg_pubkey_hashtable_alloc(void);
void wg_pubkey_hashtable_add(struct amn_pubkey_hashtable *table,
			     struct amn_wg_peer *peer);
void wg_pubkey_hashtable_remove(struct amn_pubkey_hashtable *table,
				struct amn_wg_peer *peer);
struct amn_wg_peer *
wg_pubkey_hashtable_lookup(struct amn_pubkey_hashtable *table,
			   const u8 pubkey[NOISE_PUBLIC_KEY_LEN]);

struct amn_index_hashtable {
	/* TODO: move to rhashtable */
	DECLARE_HASHTABLE(hashtable, 13);
	spinlock_t lock;
};

enum amn_index_hashtable_type {
	INDEX_HASHTABLE_HANDSHAKE = 1U << 0,
	INDEX_HASHTABLE_KEYPAIR = 1U << 1
};

struct amn_index_hashtable_entry {
	struct amn_wg_peer *peer;
	struct hlist_node index_hash;
	enum amn_index_hashtable_type type;
	__le32 index;
};

struct amn_index_hashtable *wg_index_hashtable_alloc(void);
__le32 wg_index_hashtable_insert(struct amn_index_hashtable *table,
				 struct amn_index_hashtable_entry *entry);
bool wg_index_hashtable_replace(struct amn_index_hashtable *table,
				struct amn_index_hashtable_entry *old,
				struct amn_index_hashtable_entry *new);
void wg_index_hashtable_remove(struct amn_index_hashtable *table,
			       struct amn_index_hashtable_entry *entry);
struct amn_index_hashtable_entry *
wg_index_hashtable_lookup(struct amn_index_hashtable *table,
			  const enum amn_index_hashtable_type type_mask,
			  const __le32 index, struct amn_wg_peer **peer);

#endif /* _WG_PEERLOOKUP_H */
