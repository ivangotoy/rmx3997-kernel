#ifndef _AWG_HEADER_PROTECTION
#define _AWG_HEADER_PROTECTION

#include "messages.h"

#include <linux/types.h>
#include <crypto/chacha.h>

struct amn_wg_device;

enum amn_header_protection_lengths {
    HEADER_PROTECTION_KEY_SIZE = CHACHA_KEY_SIZE,
    HEADER_PROTECTION_NONCE_SIZE = 12,
};

struct amn_header_protection {
    u32 key[CHACHA_KEY_WORDS];
    struct rw_semaphore lock;
    bool has_protection;
};

bool awg_header_protection_init(struct amn_chacha_state *state, struct amn_wg_device *dev, u8 *nonce);
void awg_header_protection_set_key(struct amn_header_protection *p, u8 key[HEADER_PROTECTION_KEY_SIZE]);
void awg_header_protection_get_key(struct amn_header_protection *p, u8 key[HEADER_PROTECTION_KEY_SIZE]);

#endif
