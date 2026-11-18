// SPDX-License-Identifier: GPL-2.0-only
#include <linux/init.h>
#include <linux/debug_locks.h>
#include <linux/mm.h>
#include <linux/mmu_notifier.h>
#include <linux/module.h>

static bool pre_register = true;
module_param(pre_register, bool, 0444);
MODULE_PARM_DESC(pre_register, "Pre-register while holding mmap write lock, then insert under read lock");

static struct mmu_interval_notifier notifier;

static bool invalidate(struct mmu_interval_notifier *sub,
                       const struct mmu_notifier_range *range,
                       unsigned long seq)
{
    return true;
}

static const struct mmu_interval_notifier_ops ops = {
    .invalidate = invalidate,
};

static int __init n1x_mmu_notifier_lock_test_init(void)
{
    struct mm_struct *mm = current->mm;
    int ret;

    if (!mm)
        return -EINVAL;

    if (pre_register) {
        mmap_write_lock(mm);
        ret = __mmu_notifier_register(NULL, mm);
        mmap_write_unlock(mm);
        if (ret)
            return ret;
        mmap_read_lock(mm);
    }

    ret = mmu_interval_notifier_insert(&notifier, mm, 0x10000, PAGE_SIZE, &ops);
    if (pre_register)
        mmap_read_unlock(mm);
    if (ret)
        return ret;

    mmu_interval_notifier_remove(&notifier);
    pr_info("N1X_MMU_NOTIFIER_TEST_PASS pre_register=%d debug_locks=%d\n",
            pre_register, READ_ONCE(debug_locks));
    return 0;
}

static void __exit n1x_mmu_notifier_lock_test_exit(void)
{
}

module_init(n1x_mmu_notifier_lock_test_init);
module_exit(n1x_mmu_notifier_lock_test_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("MMU notifier insertion with an existing mmap read lock");
