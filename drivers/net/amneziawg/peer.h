/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Copyright (C) 2015-2019 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
 */

#ifndef _WG_PEER_H
#define _WG_PEER_H

#include "device.h"
#include "messages.h"
#include "noise.h"
#include "cookie.h"
#include "type.h"

#include <linux/types.h>
#include <linux/netfilter.h>
#include <linux/spinlock.h>
#include <linux/kref.h>
#include <net/dst_cache.h>

struct amn_wg_device;

struct amn_endpoint {
	union {
		struct amn_sockaddr_inet addr;     /* Large enough for both address families */
		struct sockaddr_in addr4;
		struct sockaddr_in6 addr6;
	};
	union {
		struct {
			struct in_addr src4;
			/* Essentially the same as addr6->scope_id */
			int src_if4;
		};
		struct in6_addr src6;
	};
};

struct amn_wg_peer {
	struct amn_wg_device *device;
	struct amn_prev_queue tx_queue, rx_queue;
	struct sk_buff_head staged_packet_queue;
	int serial_work_cpu;
	bool is_dead;
	bool timer_need_another_keepalive;
	bool sent_lastminute_handshake;
	struct amn_noise_keypairs keypairs;
	struct amn_endpoint endpoint;
	struct dst_cache endpoint_cache;
	rwlock_t endpoint_lock;
	struct amn_noise_handshake handshake;
	atomic64_t last_sent_handshake;
	struct work_struct transmit_handshake_work, clear_peer_work, transmit_packet_work;
	struct amn_cookie latest_cookie;
	struct hlist_node pubkey_hash;
	u64 rx_bytes, tx_bytes;
	struct timer_list timer_retransmit_handshake, timer_send_keepalive;
	struct timer_list timer_new_handshake, timer_zero_key_material;
	struct timer_list timer_persistent_keepalive;
	unsigned int timer_handshake_attempts;
	unsigned int max_handshake_attempts;
	u32 persistent_keepalive_interval;
	struct timespec64 walltime_last_handshake;
	struct kref refcount;
	struct rcu_head rcu;
	struct list_head peer_list;
	struct list_head allowedips_list;
	struct napi_struct napi;
	u64 internal_id;
	atomic_t jp_packet_counter;
	unsigned int udp_window;
};

struct amn_wg_peer *wg_peer_create(struct amn_wg_device *wg,
			       const u8 public_key[NOISE_PUBLIC_KEY_LEN],
			       const u8 preshared_key[NOISE_SYMMETRIC_KEY_LEN]);

struct amn_wg_peer *__must_check wg_peer_get_maybe_zero(struct amn_wg_peer *peer);
static inline struct amn_wg_peer *wg_peer_get(struct amn_wg_peer *peer)
{
	kref_get(&peer->refcount);
	return peer;
}
void wg_peer_put(struct amn_wg_peer *peer);
void wg_peer_remove(struct amn_wg_peer *peer);
void wg_peer_remove_all(struct amn_wg_device *wg);

int wg_peer_init(void);
void wg_peer_uninit(void);

static inline void wg_peer_reset_last_sent_handshake(struct amn_wg_peer *peer)
{
	u16 timeout = !u16_range_is_zero(peer->device->rekey_timeout) ? u16_range_lo(peer->device->rekey_timeout) : REKEY_TIMEOUT;
	atomic64_set(&peer->last_sent_handshake, ktime_get_coarse_boottime_ns() -
				       (u64)(timeout + 1) * NSEC_PER_SEC);
}

static inline unsigned int wg_peer_skb_random_trailer(struct amn_wg_peer *peer,
									struct amn_wg_device *wg, unsigned int size)
{
	unsigned int udp_window = peer
		? READ_ONCE(peer->udp_window)
		: DEFAULT_UDP_WINDOW;

	return wg->random_trailers && udp_window > size
		? get_random_u32_below(udp_window - size)
		: 0;
}

static inline unsigned int wg_peer_skb_randomize_padding_addition(struct amn_wg_peer *peer,
									  			struct amn_wg_device *wg, unsigned int size)
{
	unsigned int udp_window = peer
		? READ_ONCE(peer->udp_window)
		: DEFAULT_UDP_WINDOW;
	u16 add, space;

	if (udp_window < size)
		return 0;

	add = u16_range_pick_one(wg->content_padding_addition);
	space = udp_window - size;
	return min(add, space);
}

#endif /* _WG_PEER_H */
