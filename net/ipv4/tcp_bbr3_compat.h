/* SPDX-License-Identifier: GPL-2.0-only */
/* RMX3997 ACK5.15 BBRv3 port: public TCP/KMI layouts remain unchanged. */
#ifndef _TCP_BBR3_COMPAT_H
#define _TCP_BBR3_COMPAT_H
#include <net/tcp.h>
#define GSO_LEGACY_MAX_SIZE 65536u
#define TCP_ECN_LOW 16
#define TCP_ECN_ECT_PERMANENT 32
#define TCP_CONG_WANTS_CE_EVENTS 0x4
#define CA_EVENT_TLP_RECOVERY ((enum tcp_ca_event)6)
#define TCPCB_IN_FLIGHT_MAX ((1U << 20) - 1)
struct tcp_plb_sysctl_params {
	u8 sysctl_tcp_plb_enabled;
	u8 sysctl_tcp_plb_idle_rehash_rounds;
	u8 sysctl_tcp_plb_rehash_rounds;
	u8 sysctl_tcp_plb_suspend_rto_sec;
	int sysctl_tcp_plb_cong_thresh;
};

struct tcp_plb_net_context {
	struct tcp_plb_sysctl_params params;
	struct ctl_table_header *sysctl_header;
};

extern unsigned int tcp_plb_net_id;

struct tcp_plb_net_context *tcp_get_plb_ctx(struct net *net);


struct tcp_bbr3_rate_sample {
	union {
		struct rate_sample base;
		struct {
	u64  prior_mstamp; /* starting timestamp for interval */
	u32  prior_delivered;	/* tp->delivered at "prior_mstamp" */
	s32  delivered;		/* number of packets delivered over interval */
	long interval_us;	/* time for tp->delivered to incr "delivered" */
	u32 snd_interval_us;	/* snd interval for delivered packets */
	u32 rcv_interval_us;	/* rcv interval for delivered packets */
	long rtt_us;		/* RTT of last (S)ACKed packet (or -1) */
	int  losses;		/* number of packets marked lost upon ACK */
	u32  acked_sacked;	/* number of packets newly (S)ACKed upon ACK */
	u32  prior_in_flight;	/* in flight before this ACK */
	u32  last_end_seq;	/* end_seq of most recently ACKed packet */
	bool is_app_limited;	/* is sample from packet with bubble in pipe? */
	bool is_retrans;	/* is sample from retransmission? */
	bool is_ack_delayed;	/* is this (likely) a delayed ACK? */
		};
	};
	bool snapshot_valid;
	bool is_acking_tlp_retrans_seq;
	bool is_ece;
	u32 tx_in_flight;
	s32 lost, delivered_ce;
	u32 prior_delivered_ce, prior_lost;
};
static inline struct tcp_bbr3_rate_sample *tcp_bbr3_rs(const struct rate_sample *rs)
{
	return container_of(rs, struct tcp_bbr3_rate_sample, base);
}
/* Metadata uses existing reserve2 and reserve1 padding3, not TCP's skb cb.
 * The high bit in padding3 marks valid snapshots. No allocation or lifetime
 * ownership is added. __copy_skb_header and TCP fragmentation copy these slots.
 */
static inline bool tcp_bbr3_skb_valid(const struct sk_buff *skb)
{
	return skb->android_kabi_reserved1_padding3 & BIT(31);
}
static inline u32 tcp_bbr3_skb_inflight(const struct sk_buff *skb)
{
	return skb->android_kabi_reserved1_padding3 & ~BIT(31);
}
static inline void tcp_bbr3_skb_set_inflight(struct sk_buff *skb, u32 count)
{
	skb->android_kabi_reserved1_padding3 = BIT(31) | count;
}
static inline u32 tcp_bbr3_skb_lost(const struct sk_buff *skb)
{
	return skb->android_kabi_reserved2 >> 32;
}
static inline u32 tcp_bbr3_skb_ce(const struct sk_buff *skb)
{
	return (u32)skb->android_kabi_reserved2;
}
static inline void tcp_bbr3_skb_copy(struct sk_buff *to, const struct sk_buff *from)
{
	to->android_kabi_reserved1_padding3 = from->android_kabi_reserved1_padding3;
	to->android_kabi_reserved2 = from->android_kabi_reserved2;
}
static inline bool tcp_skb_tx_in_flight_is_suspicious(u32 pcount,
						    u32 flags, u32 inflight)
{
	return pcount > inflight && !(flags & TCPCB_LOST);
}
static inline bool tcp_ca_wants_ce_events(const struct sock *sk)
{
	return inet_csk(sk)->icsk_ca_ops->flags &
		(TCP_CONG_NEEDS_ECN | TCP_CONG_WANTS_CE_EVENTS);
}
static inline void tcp_set_ecn_low_from_dst(struct sock *sk, const struct dst_entry *dst)
{
	if (dst_feature(dst, RTAX_FEATURE_ECN_LOW))
		tcp_sk(sk)->ecn_flags |= TCP_ECN_LOW;
}
/* tcp_plb.c */

/*
 * Scaling factor for fractions in PLB. For example, tcp_plb_update_state
 * expects cong_ratio which represents fraction of traffic that experienced
 * congestion over a single RTT. In order to avoid floating point operations,
 * this fraction should be mapped to (1 << TCP_PLB_SCALE) and passed in.
 */
#define TCP_PLB_SCALE 8

/* State for PLB (Protective Load Balancing) for a single TCP connection. */
struct tcp_plb_state {
	u8	consec_cong_rounds:5, /* consecutive congested rounds */
		unused:3;
	u32	pause_until; /* jiffies32 when PLB can resume rerouting */
};

static inline void tcp_plb_init(const struct sock *sk,
				struct tcp_plb_state *plb)
{
	plb->consec_cong_rounds = 0;
	plb->pause_until = 0;
}
void tcp_plb_update_state(const struct sock *sk, struct tcp_plb_state *plb,
			  const int cong_ratio);
void tcp_plb_check_rehash(struct sock *sk, struct tcp_plb_state *plb);
void tcp_plb_update_state_upon_rto(struct sock *sk, struct tcp_plb_state *plb);

/* BBR3 congestion control block */
struct bbr3 {
	u32	min_rtt_us;	        /* min RTT in min_rtt_win_sec window */
	u32	min_rtt_stamp;	        /* timestamp of min_rtt_us */
	u32	probe_rtt_done_stamp;   /* end time for BBR_PROBE_RTT mode */
	u32	probe_rtt_min_us;	/* min RTT in probe_rtt_win_ms win */
	u32	probe_rtt_min_stamp;	/* timestamp of probe_rtt_min_us*/
	u32     next_rtt_delivered; /* scb->tx.delivered at end of round */
	u64	cycle_mstamp;	     /* time of this cycle phase start */
	u32     mode:2,		     /* current bbr_mode in state machine */
		prev_ca_state:3,     /* CA state on previous ACK */
		round_start:1,	     /* start of packet-timed tx->ack round? */
		ce_state:1,          /* If most recent data has CE bit set */
		bw_probe_up_rounds:5,   /* cwnd-limited rounds in PROBE_UP */
		try_fast_path:1,	/* can we take fast path? */
		idle_restart:1,	     /* restarting after idle? */
		probe_rtt_round_done:1,  /* a BBR_PROBE_RTT round at 4 pkts? */
		init_cwnd:7,         /* initial cwnd */
		unused_1:10;
	u32	pacing_gain:10,	/* current gain for setting pacing rate */
		cwnd_gain:10,	/* current gain for setting cwnd */
		full_bw_reached:1,   /* reached full bw in Startup? */
		full_bw_cnt:2,	/* number of rounds without large bw gains */
		cycle_idx:2,	/* current index in pacing_gain cycle array */
		has_seen_rtt:1, /* have we seen an RTT sample yet? */
		unused_2:6;
	u32	prior_cwnd;	/* prior cwnd upon entering loss recovery */
	u32	full_bw;	/* recent bw, to estimate if pipe is full */

	/* For tracking ACK aggregation: */
	u64	ack_epoch_mstamp;	/* start of ACK sampling epoch */
	u16	extra_acked[2];		/* max excess data ACKed in epoch */
	u32	ack_epoch_acked:20,	/* packets (S)ACKed in sampling epoch */
		extra_acked_win_rtts:5,	/* age of extra_acked, in round trips */
		extra_acked_win_idx:1,	/* current index in extra_acked array */
	/* BBR v3 state: */
		full_bw_now:1,		/* recently reached full bw plateau? */
		startup_ecn_rounds:2,	/* consecutive hi ECN STARTUP rounds */
		loss_in_cycle:1,	/* packet loss in this cycle? */
		ecn_in_cycle:1,		/* ECN in this cycle? */
		unused_3:1;
	u32	loss_round_delivered; /* scb->tx.delivered ending loss round */
	u32	undo_bw_lo;	     /* bw_lo before latest losses */
	u32	undo_inflight_lo;    /* inflight_lo before latest losses */
	u32	undo_inflight_hi;    /* inflight_hi before latest losses */
	u32	bw_latest;	 /* max delivered bw in last round trip */
	u32	bw_lo;		 /* lower bound on sending bandwidth */
	u32	bw_hi[2];	 /* max recent measured bw sample */
	u32	inflight_latest; /* max delivered data in last round trip */
	u32	inflight_lo;	 /* lower bound of inflight data range */
	u32	inflight_hi;	 /* upper bound of inflight data range */
	u32	bw_probe_up_cnt; /* packets delivered per inflight_hi incr */
	u32	bw_probe_up_acks;  /* packets (S)ACKed since inflight_hi incr */
	u32	probe_wait_us;	 /* PROBE_DOWN until next clock-driven probe */
	u32	prior_rcv_nxt;	/* tp->rcv_nxt when CE state last changed */
	u32	ecn_eligible:1,	/* sender can use ECN (RTT, handshake)? */
		ecn_alpha:9,	/* EWMA delivered_ce/delivered; 0..256 */
		bw_probe_samples:1,    /* rate samples reflect bw probing? */
		prev_probe_too_high:1, /* did last PROBE_UP go too high? */
		stopped_risky_probe:1, /* last PROBE_UP stopped due to risk? */
		rounds_since_probe:8,  /* packet-timed rounds since probed bw */
		loss_round_start:1,    /* loss_round_delivered round trip? */
		loss_in_round:1,       /* loss marked in this round trip? */
		ecn_in_round:1,	       /* ECN marked in this round trip? */
		ack_phase:3,	       /* bbr_ack_phase: meaning of ACKs */
		loss_events_in_round:4,/* losses in STARTUP round */
		initialized:1;	       /* has bbr_init() been called? */
	u32	alpha_last_delivered;	 /* tp->delivered    at alpha update */
	u32	alpha_last_delivered_ce; /* tp->delivered_ce at alpha update */

	bool tlp_orig_data_app_limited;
	u8	unused_4;		/* to preserve alignment */
	struct tcp_plb_state plb;

	/* react to a specific lost skb (optional) */
	void (*skb_marked_lost)(struct sock *sk, const struct sk_buff *skb);
};

#if IS_ENABLED(CONFIG_TCP_CONG_BBR3)
bool tcp_bbr3_enabled(const struct sock *sk);
#else
static inline bool tcp_bbr3_enabled(const struct sock *sk) { return false; }
#endif
static inline struct bbr3 *tcp_bbr3_priv(const struct sock *sk)
{
	return tcp_bbr3_enabled(sk) ? *(struct bbr3 **)inet_csk_ca(sk) : NULL;
}
static inline bool tcp_bbr3_fast_ack(const struct sock *sk)
{
	struct bbr3 *bbr = tcp_bbr3_priv(sk);
	return bbr && bbr->initialized;
}
#endif
