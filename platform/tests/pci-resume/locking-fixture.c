// SPDX-License-Identifier: GPL-2.0-only
/* Actual PCI callbacks with a lock-order recorder and real topology mutex contention. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint16_t u16;typedef uint64_t u64;
#define PCI_COMMAND 4
#define PCI_COMMAND_MASTER 4
#define PCI_COMMAND_SERR 256
#define PCI_COMMAND_INTX_DISABLE 1024
#define PCI_DEVFN(a,b) ((a)*8+(b))
#define PCI_RESET_DO_RESET 1
#define PCI_RESET_PROBE 0
#define ctrl_dbg(...) ((void)0)
#define ctrl_err(...) ((void)0)
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
struct list_head {struct list_head *next,*prev;};
#define list_entry(p,t,m) container_of(p,t,m)
#define list_for_each_entry(p,h,m) for(p=list_entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_entry((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_safe_reverse(p,t,h,m) for(p=list_entry((h)->prev,__typeof__(*p),m),t=list_entry((p)->m.prev,__typeof__(*p),m);&(p)->m!=(h);p=t,t=list_entry((t)->m.prev,__typeof__(*t),m))
static void list_init(struct list_head *h) {h->next=h->prev=h;}
static bool list_empty(struct list_head *h) {return h->next==h;}
static void list_add(struct list_head *p,struct list_head *h) {p->prev=h->prev;p->next=h;h->prev->next=p;h->prev=p;}
static void list_del(struct list_head *p) {p->prev->next=p->next;p->next->prev=p->prev;}
static _Thread_local unsigned held;static unsigned edges[4],cycles;
static void learn(unsigned id,bool attempt) {assert(!(held&(1u<<id)));if(!attempt)for(unsigned i=0;i<4;i++)if(held&(1u<<i))edges[i]|=1u<<id;held|=1u<<id;}
static void drop(unsigned id) {assert(held&(1u<<id));held&=~(1u<<id);}
struct mutex {pthread_mutex_t raw;unsigned id;};
static struct mutex pci_rescan_remove_lock={PTHREAD_MUTEX_INITIALIZER,0},pci_slot_mutex={PTHREAD_MUTEX_INITIALIZER,1},device_lock={PTHREAD_MUTEX_INITIALIZER,3};
static void mutex_lock(struct mutex *m) {assert(!pthread_mutex_lock(&m->raw));learn(m->id,false);}
static void mutex_unlock(struct mutex *m) {drop(m->id);assert(!pthread_mutex_unlock(&m->raw));}
static bool mutex_trylock(struct mutex *m) {int ret=pthread_mutex_trylock(&m->raw);if(ret==EBUSY)return false;assert(!ret);learn(m->id,true);return true;}
struct rwsem {bool locked;};
static void down_read_nested(struct rwsem *s,unsigned depth) {assert(!s->locked);s->locked=true;learn(2,false);}
static void up_read(struct rwsem *s) {assert(s->locked);s->locked=false;drop(2);}
static void pci_lock_rescan_remove(void) {mutex_lock(&pci_rescan_remove_lock);}
static void pci_unlock_rescan_remove(void) {mutex_unlock(&pci_rescan_remove_lock);}
struct pci_bus {struct list_head devices,slots;int number;};
struct pci_slot {struct list_head list;};
struct pci_dev {struct pci_bus *subordinate,*bus;struct pci_slot *slot;struct list_head bus_list;int refs;};
#define for_each_pci_bridge(p,b) list_for_each_entry(p,&(b)->devices,bus_list) if((p)->subordinate)
struct pcie_device {struct pci_dev *port;};
struct controller {struct pcie_device *pcie;struct rwsem reset_lock;unsigned depth;u64 dsn;};
static struct pci_bus bus;static struct pci_dev devices[2],bridge;static struct pci_slot slot;
static struct pcie_device pcie;static struct controller ctrl;
static unsigned scan_result,removed,reset_calls,unsafe_reset;static int reset_error,probe_error;
static int pci_domain_nr(struct pci_bus *b) {return 0;}
static struct pci_dev *pci_dev_get(struct pci_dev *p) {p->refs++;return p;}
static void pci_dev_put(struct pci_dev *p) {assert(p->refs>0);p->refs--;}
static struct pci_dev *pci_get_slot(struct pci_bus *b,unsigned devfn) {if(list_empty(&b->devices))return NULL;return pci_dev_get(list_entry(b->devices.next,struct pci_dev,bus_list));}
static unsigned pci_scan_slot(struct pci_bus *b,unsigned devfn) {mutex_lock(&pci_slot_mutex);if(scan_result)list_add(&devices[0].bus_list,&b->devices);mutex_unlock(&pci_slot_mutex);return scan_result;}
static void pci_hp_add_bridge(struct pci_dev *d) {}
static void pci_assign_unassigned_bridge_resources(struct pci_dev *d) {}
static void pcie_bus_configure_settings(struct pci_bus *b) {}
static void pci_bus_add_devices(struct pci_bus *b) {mutex_lock(&device_lock);mutex_unlock(&device_lock);}
static u64 pci_get_dsn(struct pci_dev *d) {return 0x123456789abcdefULL;}
static void pci_dev_set_disconnected(void) {}
#define pci_walk_bus(...) ((void)0)
static void pci_stop_and_remove_bus_device(struct pci_dev *d) {assert(held&1u);assert(!(held&4u));mutex_lock(&device_lock);removed++;list_del(&d->bus_list);mutex_unlock(&device_lock);}
static void pci_read_config_word(struct pci_dev *d,unsigned reg,u16 *v) {*v=0xffff;}
static void pci_write_config_word(struct pci_dev *d,unsigned reg,u16 v) {assert(!(v&(PCI_COMMAND_MASTER|PCI_COMMAND_SERR)));assert(v&PCI_COMMAND_INTX_DISABLE);}
static int pci_probe_reset_slot(struct pci_slot *s) {return s?probe_error:-ENOTTY;}
static int execute_reset(void) {reset_calls++;if(!(held&1u))unsafe_reset++;down_read_nested(&ctrl.reset_lock,0);up_read(&ctrl.reset_lock);return reset_error;}
static int pci_try_reset_slot(struct pci_slot *s) {return execute_reset();}
static int pci_slot_reset(struct pci_slot *s,int action) {return execute_reset();}
static int pci_try_reset_bus(struct pci_bus *b) {return execute_reset();}
static int pci_bus_reset(struct pci_bus *b,int action) {return execute_reset();}
#include "locking.inc"
static void reset(void) {assert(!held);list_init(&bus.devices);list_init(&bus.slots);memset(devices,0,sizeof(devices));for(unsigned i=0;i<2;i++)devices[i].bus=&bus;bridge.subordinate=&bus;pcie.port=&bridge;ctrl.pcie=&pcie;ctrl.reset_lock.locked=false;ctrl.dsn=99;scan_result=1;removed=reset_calls=unsafe_reset=0;reset_error=probe_error=0;list_init(&slot.list);}
static void *contended(void *unused) {int ret=pci_reset_bus(&devices[0]);assert(ret==(LEGACY?0:-EAGAIN));return NULL;}
int main(void) {
 reset();down_read_nested(&ctrl.reset_lock,0);assert(!pciehp_configure_device(&ctrl));assert(ctrl.reset_lock.locked && ctrl.dsn==0x123456789abcdefULL && !devices[0].refs);up_read(&ctrl.reset_lock);
 /* Existing device and empty scan preserve DSN and return with reset_lock held. */
 ctrl.dsn=77;down_read_nested(&ctrl.reset_lock,0);assert(pciehp_configure_device(&ctrl)==-EEXIST && ctrl.dsn==77);up_read(&ctrl.reset_lock);
 list_add(&devices[1].bus_list,&bus.devices);down_read_nested(&ctrl.reset_lock,0);pciehp_unconfigure_device(&ctrl,false);assert(removed==2 && ctrl.reset_lock.locked && list_empty(&bus.devices));up_read(&ctrl.reset_lock);
 reset();scan_result=0;down_read_nested(&ctrl.reset_lock,0);assert(pciehp_configure_device(&ctrl)==-ENODEV && ctrl.dsn==99);up_read(&ctrl.reset_lock);
 reset();list_add(&devices[0].bus_list,&bus.devices);down_read_nested(&ctrl.reset_lock,0);pciehp_unconfigure_device(&ctrl,true);assert(removed==1);up_read(&ctrl.reset_lock);
 /* Slot and bus fallback, success/error unwind, never lose topology lock balance. */
 for(int slots=0;slots<2;slots++)for(int err=0;err<2;err++)for(int restore=0;restore<2;restore++) {
  reset();if(slots)list_add(&slot.list,&bus.slots);reset_error=err?-EIO:0;
  assert(pci_reset_bridge(&bridge,restore)==reset_error && reset_calls==1);assert(!held);
 }
 reset();bridge.subordinate=NULL;assert(pci_reset_bridge(&bridge,true)==-ENOTTY && !held);bridge.subordinate=&bus;
 /* Removal may wait for this reset work. A contended reset must never block. */
 reset();pci_lock_rescan_remove();pthread_t worker;assert(!pthread_create(&worker,NULL,contended,NULL));assert(!pthread_join(worker,NULL));assert(reset_calls==(unsigned)LEGACY && unsafe_reset==(unsigned)LEGACY);pci_unlock_rescan_remove();
#if !LEGACY
 reset();pci_lock_rescan_remove();assert(pci_reset_bridge(&bridge,true)==-EAGAIN && !reset_calls);pci_unlock_rescan_remove();
 reset();pci_lock_rescan_remove();assert(!pci_reset_bus_unlocked(&devices[0]) && reset_calls==1 && !unsafe_reset);pci_unlock_rescan_remove();
#endif
 for(unsigned k=0;k<4;k++)for(unsigned i=0;i<4;i++)if(edges[i]&(1u<<k))edges[i]|=edges[k];
 for(unsigned i=0;i<4;i++)if(edges[i]&(1u<<i))cycles++;
 assert((cycles>0)==LEGACY);
 printf("Actual PCI scan/remove/reset callbacks: legacy=%d lock-order-cycles=%u contention/error cases PASS\n",LEGACY,cycles);
 return 0;
}
