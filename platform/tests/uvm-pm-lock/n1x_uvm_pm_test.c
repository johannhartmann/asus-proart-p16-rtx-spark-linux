// SPDX-License-Identifier: GPL-2.0-only
/* Actual UVM PM callbacks, mocked GPUs, real Linux locks; disposable QEMU only. */
#include <linux/completion.h>
#include <linux/debug_locks.h>
#include <linux/delay.h>
#include <linux/dmi.h>
#include <linux/kthread.h>
#include <linux/list.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/rwsem.h>

static bool run_test, positive;
static unsigned int va_spaces = 1;
module_param(run_test, bool, 0400);
module_param(positive, bool, 0400);
module_param(va_spaces, uint, 0400);
#define NV_OK 0
typedef int NV_STATUS;
typedef unsigned int uvm_gpu_id_t;
typedef struct { struct mutex m; } uvm_mutex_t;
typedef struct { struct rw_semaphore sem; } uvm_rwsem_t;
typedef struct {
 uvm_mutex_t serialize_writers_lock, read_acquire_write_release_lock;
 uvm_rwsem_t lock;
 struct list_head list_node;
} uvm_va_space_t;
struct queue { unsigned int id; };
struct parent_gpu {
 struct { struct queue bottom_half_q, kill_channel_q;
          struct { bool handling; } non_replayable_faults; } isr;
 bool suspended, ignored;
};
typedef struct { struct parent_gpu *parent; } uvm_gpu_t;
static struct {
 struct { uvm_rwsem_t lock; bool is_suspended; } pm;
 struct { uvm_mutex_t lock; struct list_head list; } va_spaces;
 struct queue global_q, deferred_release_q;
 unsigned int retained_gpus;
} g_uvm_global;
static uvm_va_space_t spaces[8];
static struct parent_gpu parents[2];
static uvm_gpu_t gpus[2];
static bool tracking_disabled;
static unsigned int failures, global_flushes, deferred_flushes, mutations;
static DECLARE_COMPLETION(mutator_start);
static DECLARE_COMPLETION(mutator_entered);
static DECLARE_COMPLETION(mutator_done);
#define check(x) do { if (!(x)) { pr_err("UVM_PM_CHECK %s:%d: %s\n", __func__, __LINE__, #x); failures++; } } while (0)
#define uvm_mutex_lock(x) mutex_lock(&(x)->m)
#define uvm_mutex_unlock(x) mutex_unlock(&(x)->m)
#define uvm_down_write(x) down_write(&(x)->sem)
#define uvm_up_write(x) up_write(&(x)->sem)
#define uvm_assert_mutex_interrupts() check(!irqs_disabled() && !in_interrupt())
#define uvm_assert_rwsem_locked_write(x) do { check(rwsem_is_locked(&(x)->sem)); lockdep_assert_held_write(&(x)->sem); } while (0)
static void uvm_thread_context_lock_disable_tracking(void) { check(!tracking_disabled); tracking_disabled = true; }
static void uvm_thread_context_lock_enable_tracking(void) { check(tracking_disabled); tracking_disabled = false; }
static void nv_kthread_q_flush(struct queue *q)
{
 if (q->id == 1) { check(rwsem_is_locked(&g_uvm_global.pm.lock.sem)); global_flushes++; }
 else if (q->id == 2) { lockdep_assert_not_held(&g_uvm_global.pm.lock.sem); deferred_flushes++; }
}
#define for_each_gpu_id_in_mask(id, mask) for ((id) = 0; (id) < *(mask); (id)++)
static uvm_gpu_t *uvm_gpu_get(unsigned int id) { check(id < 2); return &gpus[id]; }
static void uvm_gpu_replayable_buffer_flush(uvm_gpu_t *gpu) { check(gpu->parent != NULL); }
static void uvm_parent_gpu_access_counters_set_ignore(struct parent_gpu *p, bool value) { p->ignored = value; }
static void uvm_parent_gpu_set_isr_suspended(struct parent_gpu *p, bool value) { p->suspended = value; }
static void uvm_parent_gpu_fault_buffer_resume(struct parent_gpu *p) { check(p->suspended && p->ignored); }
#include "callbacks.inc"

/* Release and creation both take PM read grants before mutating the VA list. */
static int mutator(void *unused)
{
 wait_for_completion(&mutator_start);
 complete(&mutator_entered);
 down_read(&g_uvm_global.pm.lock.sem);
 mutex_lock(&g_uvm_global.va_spaces.lock.m);
 mutations++;
 mutex_unlock(&g_uvm_global.va_spaces.lock.m);
 up_read(&g_uvm_global.pm.lock.sem);
 complete(&mutator_done);
 while (!kthread_should_stop()) {
  set_current_state(TASK_INTERRUPTIBLE);
  if (!kthread_should_stop()) schedule();
 }
 __set_current_state(TASK_RUNNING);
 return 0;
}
static int __init test_init(void)
{
 unsigned int i, cycle, count;
 int expected;
 if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU")) return -ENODEV;
 if (!IS_ENABLED(CONFIG_LOCKDEP) || !debug_locks || va_spaces > ARRAY_SIZE(spaces) || (positive && !va_spaces)) return -EINVAL;
 init_rwsem(&g_uvm_global.pm.lock.sem);
 mutex_init(&g_uvm_global.va_spaces.lock.m);
 INIT_LIST_HEAD(&g_uvm_global.va_spaces.list);
 g_uvm_global.global_q.id = 1;
 g_uvm_global.deferred_release_q.id = 2;
 g_uvm_global.retained_gpus = 2;
 for (i = 0; i < 2; i++) {
  gpus[i].parent = &parents[i];
  parents[i].isr.non_replayable_faults.handling = true;
 }
 for (i = 0; i < va_spaces; i++) {
  mutex_init(&spaces[i].serialize_writers_lock.m);
  mutex_init(&spaces[i].read_acquire_write_release_lock.m);
  init_rwsem(&spaces[i].lock.sem);
  list_add_tail(&spaces[i].list_node, &g_uvm_global.va_spaces.list);
 }
 count = FIXED ? 4 : 1;
 for (cycle = 0; cycle < count; cycle++) {
  struct task_struct *task;
  reinit_completion(&mutator_start); reinit_completion(&mutator_entered); reinit_completion(&mutator_done);
  task = kthread_run(mutator, NULL, "uvm-pm-mutator");
  if (IS_ERR(task)) return PTR_ERR(task);
  check(uvm_suspend() == NV_OK);
  check(g_uvm_global.pm.is_suspended && !tracking_disabled);
  for (i = 0; i < va_spaces; i++) check(rwsem_is_locked(&spaces[i].lock.sem));
  complete(&mutator_start);
  check(wait_for_completion_timeout(&mutator_entered, HZ) != 0);
  check(wait_for_completion_timeout(&mutator_done, msecs_to_jiffies(20)) == 0);
  check(mutations == cycle);
  check(uvm_resume() == NV_OK);
  check(wait_for_completion_timeout(&mutator_done, HZ) != 0);
  kthread_stop(task);
  check(mutations == cycle + 1 && !g_uvm_global.pm.is_suspended && !tracking_disabled);
  check(!rwsem_is_locked(&g_uvm_global.pm.lock.sem));
  for (i = 0; i < va_spaces; i++) {
   check(!rwsem_is_locked(&spaces[i].lock.sem));
   check(!mutex_is_locked(&spaces[i].serialize_writers_lock.m));
   check(!mutex_is_locked(&spaces[i].read_acquire_write_release_lock.m));
  }
  for (i = 0; i < 2; i++) check(!parents[i].suspended && !parents[i].ignored);
 }
 check(global_flushes == count && deferred_flushes == count);
 if (positive) {
  /* A real illegal VA -> list acquisition must remain visible to Lockdep. */
  uvm_va_space_down_write(&spaces[0]);
  mutex_lock(&g_uvm_global.va_spaces.lock.m);
  mutex_unlock(&g_uvm_global.va_spaces.lock.m);
  uvm_va_space_up_write(&spaces[0]);
 }
 expected = (!FIXED && va_spaces) || positive ? 0 : 1;
 check(debug_locks == expected);
 pr_info("UVM_PM_LOCK_RESULT fixed=%d va_spaces=%u positive=%u cycles=%u mutations=%u debug_locks=%d expected=%d failures=%u\n", FIXED, va_spaces, positive, count, mutations, debug_locks, expected, failures);
 if (failures) return -EINVAL;
 pr_info("UVM_PM_LOCK_TEST_PASS\n");
 return 0;
}
static void __exit test_exit(void) {}
module_init(test_init);
module_exit(test_exit);
MODULE_LICENSE("GPL");

MODULE_DESCRIPTION("QEMU-only UVM PM lock regression using vendor callbacks");
