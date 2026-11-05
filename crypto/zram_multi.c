// SPDX-License-Identifier: GPL-2.0-only
/*
 * Page compressor for OEM ZRAM providers exposing the synchronous Crypto API.
 * Each stored frame chooses the smaller LZO-RLE/Zstd result and carries its
 * decoder tag. This adds no fields or flags to the provider's ZRAM structures.
 * Like the underlying compressors, each tfm must be serialized by its caller;
 * the RMX3997 provider supplies one locked stream per CPU.
 */
#include <linux/crypto.h>
#include <linux/err.h>
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/slab.h>

#define ZRAM_MULTI_HEADER 4
#define ZRAM_MULTI_BUFFER (2 * PAGE_SIZE)

struct zram_multi_ctx {
	struct crypto_comp *fast;
	struct crypto_comp *dense;
	u8 *scratch;
};

static int zram_multi_init(struct crypto_tfm *tfm)
{
	struct zram_multi_ctx *ctx = crypto_tfm_ctx(tfm);
	int err;

	ctx->fast = crypto_alloc_comp("lzo-rle", 0, 0);
	if (IS_ERR(ctx->fast))
		return PTR_ERR(ctx->fast);
	ctx->dense = crypto_alloc_comp("zstd", 0, 0);
	if (IS_ERR(ctx->dense)) {
		err = PTR_ERR(ctx->dense);
		goto free_fast;
	}
	ctx->scratch = kmalloc(ZRAM_MULTI_BUFFER, GFP_KERNEL);
	if (!ctx->scratch) {
		err = -ENOMEM;
		crypto_free_comp(ctx->dense);
		goto free_fast;
	}
	return 0;
free_fast:
	crypto_free_comp(ctx->fast);
	return err;
}

static void zram_multi_exit(struct crypto_tfm *tfm)
{
	struct zram_multi_ctx *ctx = crypto_tfm_ctx(tfm);

	kfree(ctx->scratch);
	crypto_free_comp(ctx->dense);
	crypto_free_comp(ctx->fast);
}

static int zram_multi_compress(struct crypto_tfm *tfm, const u8 *src,
			       unsigned int slen, u8 *dst, unsigned int *dlen)
{
	struct zram_multi_ctx *ctx = crypto_tfm_ctx(tfm);
	unsigned int capacity = *dlen;
	unsigned int fast_len, dense_len = ZRAM_MULTI_BUFFER;
	int fast_err, dense_err;
	u8 tag;

	if (slen != PAGE_SIZE)
		return -EINVAL;
	if (capacity <= ZRAM_MULTI_HEADER)
		return -ENOSPC;
	fast_len = capacity - ZRAM_MULTI_HEADER;
	fast_err = crypto_comp_compress(ctx->fast, src, slen,
				       dst + ZRAM_MULTI_HEADER, &fast_len);
	dense_err = crypto_comp_compress(ctx->dense, src, slen,
					ctx->scratch, &dense_len);
	if (!dense_err && dense_len <= capacity - ZRAM_MULTI_HEADER &&
	    (fast_err || dense_len < fast_len)) {
		memcpy(dst + ZRAM_MULTI_HEADER, ctx->scratch, dense_len);
		*dlen = dense_len + ZRAM_MULTI_HEADER;
		tag = 1;
	} else if (!fast_err && fast_len <= capacity - ZRAM_MULTI_HEADER) {
		*dlen = fast_len + ZRAM_MULTI_HEADER;
		tag = 0;
	} else {
		return -ENOSPC;
	}
	dst[0] = 'Z';
	dst[1] = 'M';
	dst[2] = 1;
	dst[3] = tag;
	return 0;
}

static int zram_multi_decompress(struct crypto_tfm *tfm, const u8 *src,
				 unsigned int slen, u8 *dst, unsigned int *dlen)
{
	struct zram_multi_ctx *ctx = crypto_tfm_ctx(tfm);
	unsigned int size = PAGE_SIZE;
	int err;

	if (slen <= ZRAM_MULTI_HEADER || slen > ZRAM_MULTI_BUFFER ||
	    *dlen < PAGE_SIZE || src[0] != 'Z' || src[1] != 'M' ||
	    src[2] != 1 || src[3] > 1)
		return -EINVAL;
	err = crypto_comp_decompress(src[3] ? ctx->dense : ctx->fast,
			src + ZRAM_MULTI_HEADER, slen - ZRAM_MULTI_HEADER,
			dst, &size);
	if (err)
		return err;
	if (size != PAGE_SIZE)
		return -EINVAL;
	*dlen = size;
	return 0;
}

static struct crypto_alg zram_multi_alg = {
	.cra_name = "zram-multi",
	.cra_driver_name = "zram-multi-lzo-zstd",
	.cra_flags = CRYPTO_ALG_TYPE_COMPRESS,
	.cra_ctxsize = sizeof(struct zram_multi_ctx),
	.cra_module = THIS_MODULE,
	.cra_init = zram_multi_init,
	.cra_exit = zram_multi_exit,
	.cra_u = { .compress = {
		.coa_compress = zram_multi_compress,
		.coa_decompress = zram_multi_decompress,
	} },
};

static int __init zram_multi_register(void)
{
	return crypto_register_alg(&zram_multi_alg);
}

static void __exit zram_multi_unregister(void)
{
	crypto_unregister_alg(&zram_multi_alg);
}

module_init(zram_multi_register);
module_exit(zram_multi_unregister);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Per-page LZO-RLE/Zstd selection for OEM ZRAM Crypto API providers");
MODULE_ALIAS_CRYPTO("zram-multi");
