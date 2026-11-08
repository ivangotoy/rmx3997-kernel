/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Copyright (C) 2015-2019 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
 */

#ifndef _WG_DEVICE_H
#define _WG_DEVICE_H

#include "junk.h"
#include "noise.h"
#include "allowedips.h"
#include "peerlookup.h"
#include "cookie.h"
#include "header_protection.h"
#include "type.h"

#include <linux/types.h>
#include <linux/netdevice.h>
#include <linux/workqueue.h>
#include <linux/mutex.h>
#include <linux/net.h>
#include <linux/ptr_ring.h>

struct amn_wg_device;

struct amn_multicore_worker {
	void *ptr;
	struct work_struct work;
};

struct amn_crypt_queue {
	struct ptr_ring ring;
	struct amn_multicore_worker __percpu *worker;
	int last_cpu;
};

struct amn_prev_queue {
	struct sk_buff *head, *tail, *peeked;
	struct { struct sk_buff *next, *prev; } empty; // Match first 2 members of struct sk_buff.
	atomic_t count;
};

struct amn_wg_device {
	struct net_device *dev;
	struct amn_crypt_queue encrypt_queue, decrypt_queue, handshake_queue;
	struct sock __rcu *sock4, *sock6;
	struct net __rcu *creating_net;
	struct amn_noise_static_identity static_identity;
	struct workqueue_struct *packet_crypt_wq,*handshake_receive_wq, *handshake_send_wq;
	struct amn_cookie_checker cookie_checker;
	struct amn_pubkey_hashtable *peer_hashtable;
	struct amn_index_hashtable *index_hashtable;
	struct amn_allowedips peer_allowedips;
	struct mutex device_update_lock, socket_update_lock;
	struct list_head device_list, peer_list;
	struct amn_header_protection header_protection;
	struct amn_jp_spec ispecs[5];
	amn_u32_range_t init_header, resp_header, cookie_header, transport_header;
	amn_u16_range_t content_padding_addition, max_handshake_attempts;
	amn_u16_range_t rekey_after_time, rekey_timeout, reject_after_time, keepalive_timeout;
	atomic_t handshake_queue_len;
	unsigned int num_peers, device_update_gen;
	u32 fwmark;
	u16 init_padding, resp_padding, cookie_padding, transport_padding;
	u16 incoming_port;
	u16 jc, jmin, jmax;
	bool random_trailers, disable_cookies;
};

int wg_device_init(void);
void wg_device_uninit(void);

#endif /* _WG_DEVICE_H */
