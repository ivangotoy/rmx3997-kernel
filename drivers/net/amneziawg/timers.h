/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Copyright (C) 2015-2019 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
 */

#ifndef _WG_TIMERS_H
#define _WG_TIMERS_H

#include <linux/ktime.h>

struct amn_wg_peer;

void wg_timers_init(struct amn_wg_peer *peer);
void wg_timers_stop(struct amn_wg_peer *peer);
void wg_timers_data_sent(struct amn_wg_peer *peer);
void wg_timers_data_received(struct amn_wg_peer *peer);
void wg_timers_any_authenticated_packet_sent(struct amn_wg_peer *peer);
void wg_timers_any_authenticated_packet_received(struct amn_wg_peer *peer);
void wg_timers_handshake_initiated(struct amn_wg_peer *peer);
void wg_timers_handshake_complete(struct amn_wg_peer *peer);
void wg_timers_session_derived(struct amn_wg_peer *peer);
void wg_timers_any_authenticated_packet_traversal(struct amn_wg_peer *peer);

static inline bool wg_birthdate_has_expired(u64 birthday_nanoseconds,
					    u64 expiration_seconds)
{
	return (s64)(birthday_nanoseconds + expiration_seconds * NSEC_PER_SEC)
		<= (s64)ktime_get_coarse_boottime_ns();
}

#endif /* _WG_TIMERS_H */
