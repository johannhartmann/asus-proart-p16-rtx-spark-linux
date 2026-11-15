// SPDX-License-Identifier: GPL-2.0-only
/* Exercise real bus_register()/bus_notify() in disposable QEMU only. */
#include <linux/debug_locks.h>
#include <linux/device.h>
#include <linux/dmi.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>

static bool run_test, same_bus, expect_clean;
module_param(run_test, bool, 0400);
module_param(same_bus, bool, 0400);
module_param(expect_clean, bool, 0400);
static DEFINE_MUTEX(outer_gate);
static DEFINE_MUTEX(callback_gate);
static struct bus_type bus_a = { .name = "notifier-test-a" };
static struct bus_type bus_b = { .name = "notifier-test-b" };

static int empty_callback(struct notifier_block *nb, unsigned long event, void *data)
{
	return NOTIFY_DONE;
}

static int callback(struct notifier_block *nb, unsigned long event, void *data)
{
	if (event == BUS_NOTIFY_ADD_DEVICE) {
		mutex_lock(&callback_gate);
		mutex_unlock(&callback_gate);
	}
	return NOTIFY_DONE;
}

static struct notifier_block nb = { .notifier_call = callback };
static struct notifier_block nb_a = { .notifier_call = empty_callback };

static void release(struct device *dev)
{
	kfree(dev);
}

static int __init core_test_init(void)
{
	struct device *dev;
	int ret;
	bool clean;

	if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU"))
		return -ENODEV;
	if (!IS_ENABLED(CONFIG_LOCKDEP) || !debug_locks)
		return -EUCLEAN;
	ret = bus_register(&bus_a);
	if (ret)
		return ret;
	ret = bus_register(&bus_b);
	if (ret)
		goto unregister_a;
	ret = bus_register_notifier(&bus_b, &nb);
	if (ret)
		goto unregister_b;
	ret = bus_register_notifier(&bus_a, &nb_a);
	if (ret)
		goto unregister_notifier;
	dev = kzalloc(sizeof(*dev), GFP_KERNEL);
	if (!dev) {
		ret = -ENOMEM;
		goto unregister_notifier_a;
	}
	device_initialize(dev);
	dev->bus = same_bus ? &bus_b : &bus_a;
	dev->release = release;
	ret = dev_set_name(dev, "notifier-test-device");
	if (ret)
		goto put_device;
	/* outer -> bus-A (or bus-B for the real-cycle positive control). */
	mutex_lock(&outer_gate);
	ret = device_add(dev);
	mutex_unlock(&outer_gate);
	if (ret)
		goto put_device;
	/* bus-B -> callback gate, through driver-core's actual notifier call. */
	if (!same_bus) {
		struct device *other = kzalloc(sizeof(*other), GFP_KERNEL);

		if (!other) {
			ret = -ENOMEM;
			goto delete_device;
		}
		device_initialize(other);
		other->bus = &bus_b;
		other->release = release;
		ret = dev_set_name(other, "notifier-test-other");
		if (!ret)
			ret = device_add(other);
		if (!ret)
			device_del(other);
		put_device(other);
		if (ret)
			goto delete_device;
	}
	mutex_lock(&callback_gate);
	mutex_lock(&outer_gate);
	mutex_unlock(&outer_gate);
	mutex_unlock(&callback_gate);
	clean = !!debug_locks;
	pr_info("BUS_CORE_RESULT same_bus=%u debug_locks=%u expected=%u\n",
		same_bus, clean, expect_clean);
	ret = clean == expect_clean ? 0 : -EINVAL;
delete_device:
	device_del(dev);
put_device:
	put_device(dev);
unregister_notifier_a:
	bus_unregister_notifier(&bus_a, &nb_a);
unregister_notifier:
	bus_unregister_notifier(&bus_b, &nb);
unregister_b:
	bus_unregister(&bus_b);
unregister_a:
	bus_unregister(&bus_a);
	return ret;
}

static void __exit core_test_exit(void) { }
module_init(core_test_init);
module_exit(core_test_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU-only real driver-core notifier regression");
