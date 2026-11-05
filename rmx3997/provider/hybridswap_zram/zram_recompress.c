// SPDX-License-Identifier: GPL-2.0-only
/* Included by zram_drv.c: all entry points share its slot/init ownership. */

static void zram_secondary_destroy(struct zram *zram)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(zram->secondary); i++) {
		if (zram->secondary[i])
			zcomp_destroy(zram->secondary[i]);
		zram->secondary[i] = NULL;
	}
}

static int zram_secondary_create(struct zram *zram)
{
	unsigned int i;
	int err;

	BUILD_BUG_ON(__NR_ZRAM_PAGEFLAGS > ZRAM_CODEC_SHIFT);
	BUILD_BUG_ON(BITS_PER_LONG < ZRAM_CODEC_SHIFT + 2);
	for (i = 0; i < ARRAY_SIZE(zram->secondary); i++) {
		struct zcomp *comp;

		if (!zram->secondary_name[i][0])
			continue;
		comp = zcomp_create(zram->secondary_name[i]);
		if (IS_ERR(comp)) {
			err = PTR_ERR(comp);
			zram_secondary_destroy(zram);
			return err;
		}
		zram->secondary[i] = comp;
	}
	return 0;
}

static ssize_t recomp_algorithm_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	struct zram *zram = dev_to_zram(dev);
	unsigned int i;
	ssize_t size = 0;

	down_read(&zram->init_lock);
	for (i = 1; i < ZRAM_MAX_COMPS; i++)
		if (zram->secondary_name[i - 1][0])
			size += scnprintf(buf + size, PAGE_SIZE - size,
				"#%u: %s\n", i, zram->secondary_name[i - 1]);
	up_read(&zram->init_lock);
	return size;
}

/* Configuration is immutable while any slot (including one on UFS) exists. */
static ssize_t recomp_algorithm_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t len)
{
	struct zram *zram = dev_to_zram(dev);
	char *copy, *cursor, *token, *algo = NULL;
	unsigned int priority = 1;
	bool seen_priority = false;
	int err = -EINVAL;

	copy = kstrdup(buf, GFP_KERNEL);
	if (!copy)
		return -ENOMEM;
	cursor = strim(copy);
	while ((token = strsep(&cursor, " \t\n"))) {
		if (!*token)
			continue;
		if (!strncmp(token, "algo=", 5) && !algo)
			algo = token + 5;
		else if (!strncmp(token, "priority=", 9) && !seen_priority) {
			if (kstrtouint(token + 9, 10, &priority))
				goto out;
			seen_priority = true;
		} else
			goto out;
	}
	if (!algo || !*algo || strlen(algo) >= CRYPTO_MAX_ALG_NAME ||
	    !priority || priority >= ZRAM_MAX_COMPS ||
	    !zcomp_available_algorithm(algo))
		goto out;
	down_write(&zram->init_lock);
	if (init_done(zram))
		err = -EBUSY;
	else {
		strcpy(zram->secondary_name[priority - 1], algo);
		err = len;
	}
	up_write(&zram->init_lock);
out:
	kfree(copy);
	return err;
}

enum recomp_type { RECOMP_IDLE, RECOMP_HUGE, RECOMP_HUGE_IDLE, RECOMP_ALL };

/* Caller owns init_lock read-side and a PAGE_SIZE scratch buffer. No sleeping
 * allocation or nested per-CPU stream lock while the slot spinlock is held.
 * A failed/non-improving attempt never changes handle, decoder or statistics.
 */
static int zram_recompress_one(struct zram *zram, u32 index,
		unsigned int priority, enum recomp_type type, unsigned int threshold,
		void *scratch)
{
	struct zcomp *old_comp, *new_comp;
	struct zcomp_strm *stream;
	unsigned long old_handle, new_handle;
	unsigned int old_size, size;
	void *src, *dst;
	int ret = 0;

	zram_slot_lock(zram, index);
	if (!zram_get_handle(zram, index) ||
	    zram_test_flag(zram, index, ZRAM_SAME) ||
	    zram_test_flag(zram, index, ZRAM_WB) ||
	    zram_test_flag(zram, index, ZRAM_UNDER_WB) ||
	    priority <= zram_get_priority(zram, index))
		goto unlock;
#ifdef CONFIG_HYBRIDSWAP_CORE
	if (zram_test_flag(zram, index, ZRAM_BATCHING_OUT))
		goto unlock;
#endif
	if ((type == RECOMP_IDLE || type == RECOMP_HUGE_IDLE) &&
	    !zram_test_flag(zram, index, ZRAM_IDLE))
		goto unlock;
	if ((type == RECOMP_HUGE || type == RECOMP_HUGE_IDLE) &&
	    !zram_test_flag(zram, index, ZRAM_HUGE))
		goto unlock;
	old_size = zram_get_obj_size(zram, index);
	if (old_size < threshold)
		goto unlock;
	new_comp = zram_comp(zram, priority);
	old_comp = zram_comp(zram, zram_get_priority(zram, index));
	if (!old_comp || !new_comp) {
		ret = -EINVAL;
		goto unlock;
	}
	old_handle = zram_get_handle(zram, index);
	stream = zcomp_stream_get(old_comp);
	src = zs_map_object(zram->mem_pool, old_handle, ZS_MM_RO);
	if (old_size == PAGE_SIZE)
		memcpy(scratch, src, PAGE_SIZE);
	else
		ret = zcomp_decompress(stream, src, old_size, scratch);
	zs_unmap_object(zram->mem_pool, old_handle);
	zcomp_stream_put(old_comp);
	if (ret)
		goto unlock;
	stream = zcomp_stream_get(new_comp);
	ret = zcomp_compress(stream, scratch, &size);
	if (ret || size >= old_size || size >= huge_class_size || !size)
		goto put_stream;
	new_handle = zs_malloc(zram->mem_pool, size,
			GFP_NOWAIT | __GFP_NOWARN | __GFP_HIGHMEM | __GFP_MOVABLE);
	if (!new_handle) {
		ret = -ENOMEM;
		goto put_stream;
	}
	update_used_max(zram, zs_get_total_pages(zram->mem_pool));
	if (zram->limit_pages && zs_get_total_pages(zram->mem_pool) > zram->limit_pages) {
		zs_free(zram->mem_pool, new_handle);
		ret = -ENOMEM;
		goto put_stream;
	}
	dst = zs_map_object(zram->mem_pool, new_handle, ZS_MM_WO);
	memcpy(dst, stream->buffer, size);
	zs_unmap_object(zram->mem_pool, new_handle);
#ifdef CONFIG_HYBRIDSWAP_CORE
	/* Keep the existing LRU/memcg identity and its compressed-byte accounting. */
	hybridswap_recompress_account(zram, index, (long)size - old_size);
#endif
	zram_set_handle(zram, index, new_handle);
	zram_set_obj_size(zram, index, size);
	zram_set_priority(zram, index, priority);
	if (zram_test_flag(zram, index, ZRAM_HUGE)) {
		zram_clear_flag(zram, index, ZRAM_HUGE);
		atomic64_dec(&zram->stats.huge_pages);
	}
	atomic64_add((long)size - old_size, &zram->stats.compr_data_size);
	zs_free(zram->mem_pool, old_handle);
	ret = 1;
put_stream:
	zcomp_stream_put(new_comp);
unlock:
	zram_slot_unlock(zram, index);
	return ret;
}

static ssize_t recompress_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t len)
{
	struct zram *zram = dev_to_zram(dev);
	char *copy, *cursor, *token;
	unsigned int priority = 1, threshold = 0, max_pages = UINT_MAX;
	unsigned int seen = 0;
	enum recomp_type type = RECOMP_IDLE;
	unsigned long index, pages;
	void *scratch;
	int ret = -EINVAL;

	copy = kstrdup(buf, GFP_KERNEL);
	if (!copy)
		return -ENOMEM;
	cursor = strim(copy);
	while ((token = strsep(&cursor, " \t\n"))) {
		if (!*token)
			continue;
		if (!strncmp(token, "type=", 5) && !(seen & 1)) {
			seen |= 1;
			if (!strcmp(token + 5, "idle")) type = RECOMP_IDLE;
			else if (!strcmp(token + 5, "huge")) type = RECOMP_HUGE;
			else if (!strcmp(token + 5, "huge_idle")) type = RECOMP_HUGE_IDLE;
			else if (!strcmp(token + 5, "all")) type = RECOMP_ALL;
			else goto out;
		} else if (!strncmp(token, "priority=", 9) && !(seen & 2)) {
			seen |= 2;
			if (kstrtouint(token + 9, 10, &priority)) goto out;
		} else if (!strncmp(token, "threshold=", 10) && !(seen & 4)) {
			seen |= 4;
			if (kstrtouint(token + 10, 10, &threshold)) goto out;
		} else if (!strncmp(token, "max_pages=", 10) && !(seen & 8)) {
			seen |= 8;
			if (kstrtouint(token + 10, 10, &max_pages)) goto out;
		} else goto out;
	}
	if (!seen || !priority || priority >= ZRAM_MAX_COMPS ||
	    threshold > PAGE_SIZE || !max_pages)
		goto out;
	scratch = kmalloc(PAGE_SIZE, GFP_KERNEL);
	if (!scratch) { ret = -ENOMEM; goto out; }
	down_read(&zram->init_lock);
	if (!init_done(zram) || !zram_comp(zram, priority)) {
		ret = -EINVAL;
		goto release;
	}
	pages = zram->disksize >> PAGE_SHIFT;
	for (index = 0; index < pages && max_pages; index++) {
		ret = zram_recompress_one(zram, index, priority, type, threshold, scratch);
		if (ret < 0)
			goto release;
		if (ret > 0)
			max_pages--;
		cond_resched();
	}
	ret = len;
release:
	up_read(&zram->init_lock);
	kfree(scratch);
out:
	kfree(copy);
	return ret;
}

static DEVICE_ATTR_RW(recomp_algorithm);
static DEVICE_ATTR_WO(recompress);
