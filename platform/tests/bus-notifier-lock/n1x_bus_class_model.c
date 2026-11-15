// SPDX-License-Identifier: GPL-2.0-only
/* Disposable-QEMU model of two distinct bus notifier heads. Never host-load. */
#include <linux/debug_locks.h>
#include <linux/dmi.h>
#include <linux/lockdep.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/notifier.h>
#include <linux/slab.h>

static bool run_test, unique, same_bus;
module_param(run_test, bool, 0400);
module_param(unique, bool, 0400);
module_param(same_bus, bool, 0400);
static DEFINE_MUTEX(model_mmap_gate);
static DEFINE_MUTEX(model_perf_gate);

struct model_bus {
	struct blocking_notifier_head head;
	struct lock_class_key key;
};

static noinline void init_bus(struct model_bus *bus)
{
	/* The native bus_register() initializes every head at one macro site. */
	BLOCKING_INIT_NOTIFIER_HEAD(&bus->head);
	if (unique) {
		lockdep_register_key(&bus->key);
		lockdep_set_class_and_name(&bus->head.rwsem, &bus->key,
					  "model bus notifier");
	}
}

static int bus_a_callback(struct notifier_block *nb, unsigned long event, void *data)
{
	return NOTIFY_DONE;
}

static int bus_b_callback(struct notifier_block *nb, unsigned long event, void *data)
{
	mutex_lock(&model_perf_gate);
	mutex_unlock(&model_perf_gate);
	return NOTIFY_DONE;
}

static struct notifier_block nb_a = { .notifier_call = bus_a_callback };
static struct notifier_block nb_b = { .notifier_call = bus_b_callback };

static int __init model_init(void)
{
	struct model_bus *buses;
	bool observed, expected;

	if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU"))
		return -ENODEV;
	if (!IS_ENABLED(CONFIG_LOCKDEP) || !debug_locks)
		return -EUCLEAN;
	buses = kcalloc(2, sizeof(*buses), GFP_KERNEL);
	if (!buses)
		return -ENOMEM;
	init_bus(&buses[0]);
	init_bus(&buses[1]);
	blocking_notifier_chain_register(&buses[0].head, &nb_a);
	blocking_notifier_chain_register(&buses[1].head, &nb_b);

	/* A -> bus-A. The same-bus positive control instead uses bus-B. */
	mutex_lock(&model_mmap_gate);
	blocking_notifier_call_chain(&buses[same_bus ? 1 : 0].head, 0, NULL);
	mutex_unlock(&model_mmap_gate);
	/* bus-B -> B. */
	blocking_notifier_call_chain(&buses[1].head, 0, NULL);
	/* B -> A closes a real cycle only if both edges used the same head. */
	mutex_lock(&model_perf_gate);
	mutex_lock(&model_mmap_gate);
	mutex_unlock(&model_mmap_gate);
	mutex_unlock(&model_perf_gate);
	observed = !!debug_locks;
	expected = unique && !same_bus;
	pr_info("BUS_CLASS_RESULT unique=%u same_bus=%u debug_locks=%u expected=%u\n",
		unique, same_bus, observed, expected);
	blocking_notifier_chain_unregister(&buses[0].head, &nb_a);
	blocking_notifier_chain_unregister(&buses[1].head, &nb_b);
	if (unique) {
		lockdep_unregister_key(&buses[0].key);
		lockdep_unregister_key(&buses[1].key);
	}
	kfree(buses);
	return observed == expected ? 0 : -EINVAL;
}

static void __exit model_exit(void) { }
module_init(model_init);
module_exit(model_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU-only independent bus notifier lock-class model");
