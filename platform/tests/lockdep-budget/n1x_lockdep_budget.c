// SPDX-License-Identifier: GPL-2.0-only
/* Explicit QEMU-only regression for the exhausted dependency-entry budget. */
#include <linux/debug_locks.h>
#include <linux/dmi.h>
#include <linux/errno.h>
#include <linux/lockdep.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/sched.h>

#define TEST_LOCKS 300

static struct mutex locks[TEST_LOCKS];
static struct lock_class_key keys[TEST_LOCKS];
static bool run_test;
module_param(run_test, bool, 0400);
MODULE_PARM_DESC(run_test, "Explicitly run the dependency-budget test in QEMU");

static int __init budget_init(void)
{
	unsigned int i, j, dependencies = 0;

	/* No hardware access and no admission on the physical workstation. */
	if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU"))
		return -ENODEV;
	if (!IS_ENABLED(CONFIG_LOCKDEP) || !debug_locks)
		return -EUCLEAN;

	for (i = 0; i < TEST_LOCKS; i++) {
		mutex_init(&locks[i]);
		lockdep_set_class_and_name(&locks[i], &keys[i], "n1x-budget-lock");
	}
	/* A strictly ordered DAG has 44,850 edges, exceeding the old 32,768
	 * table without a real lock-order inversion or excessive nesting.
	 */
	for (i = 0; i < TEST_LOCKS; i++) {
		for (j = i + 1; j < TEST_LOCKS; j++) {
			mutex_lock(&locks[i]);
			mutex_lock(&locks[j]);
			mutex_unlock(&locks[j]);
			mutex_unlock(&locks[i]);
			dependencies++;
			if (!debug_locks) {
				pr_info("LOCKDEP_BUDGET_EXHAUSTED pairs=%u\n", dependencies);
				return -ENOSPC;
			}
		}
		cond_resched();
	}
	pr_info("LOCKDEP_BUDGET_PASS pairs=%u debug_locks=%d\n",
		dependencies, debug_locks);
	return 0;
}

static void __exit budget_exit(void)
{
	unsigned int i;

	for (i = 0; i < TEST_LOCKS; i++)
		mutex_destroy(&locks[i]);
}

module_init(budget_init);
module_exit(budget_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU-only Lockdep dependency-capacity regression");
