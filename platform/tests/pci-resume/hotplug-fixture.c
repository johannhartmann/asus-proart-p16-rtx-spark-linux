// SPDX-License-Identifier: GPL-2.0-only
/* Execute actual noirq/system/runtime resume and request callbacks without hardware. */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define ON_STATE 1
#define BLINKINGOFF_STATE 2
#define OFF_STATE 3
#define PCI_EXP_SLTSTA_PDC 8
#define RERUN_ISR 16
#define ctrl_dbg(...) ((void)0)
#define atomic_or(v,p) (*(p)|=(v))
#define atomic_read(p) (*(p))
struct pci_bus {int dummy;};
struct pci_dev {struct pci_bus *subordinate;};
struct controller {unsigned cmd_started;bool cmd_busy;int state,pending_events;struct pcie_device *pcie;};
struct pcie_device {struct controller *ctrl;struct pci_dev *port;int irq;};
static bool pciehp_poll_mode,native,replaced,present;
static unsigned jiffies=123,wakes,early_wakes,cleared,marked,enabled,disabled;
static int phase;
static struct controller *get_service_data(struct pcie_device *d) {return d->ctrl;}
static bool pme_is_native(struct pcie_device *d) {return native;}
static void pcie_enable_interrupt(struct controller *c) {enabled++;}
static void pciehp_disable_interrupt(struct pcie_device *d) {disabled++;}
static bool pciehp_device_replaced(struct controller *c) {return replaced;}
static void pcie_clear_hotplug_events(struct controller *c) {cleared++;}
static void pci_dev_set_disconnected(void) {}
#define pci_walk_bus(...) (marked++)
static void irq_wake_thread(int irq,void *ctrl) {wakes++;if(phase<2)early_wakes++;}
#include "request.inc"
static void pciehp_check_presence(struct controller *c) {if(!present)pciehp_request(c,PCI_EXP_SLTSTA_PDC);}
#include "hotplug.inc"
int main(void) {
 unsigned cases=0;
 for(int state=ON_STATE;state<=OFF_STATE;state++)for(int rep=0;rep<2;rep++)for(int poll=0;poll<2;poll++)for(int nat=0;nat<2;nat++) {
  struct pci_bus bus={0};struct pci_dev port={&bus};struct pcie_device dev={.port=&port,.irq=7};struct controller ctrl={.state=state,.pcie=&dev};dev.ctrl=&ctrl;
  pciehp_poll_mode=poll;replaced=rep;native=nat;present=true;wakes=early_wakes=cleared=marked=enabled=disabled=0;phase=0;
  assert(!pciehp_resume_noirq(&dev));assert(ctrl.cmd_busy && ctrl.cmd_started==jiffies);
  bool replacement=state!=OFF_STATE && rep;assert(marked==replacement);assert(early_wakes==(unsigned)(LEGACY && replacement && !poll));
  if(!LEGACY && replacement)assert(ctrl.pending_events & PCI_EXP_SLTSTA_PDC);
  phase=2;
#if LEGACY
  assert(!pciehp_resume(&dev));
#else
  assert(!pciehp_system_resume(&dev));
#endif
  if(replacement && !poll)assert(wakes>0);
  assert(enabled==(unsigned)nat);assert(cleared==(unsigned)(state!=OFF_STATE));cases++;
 }
 /* Runtime resume still clears events and calls the original runtime policy. */
 struct pci_bus bus={0};struct pci_dev port={&bus};struct pcie_device dev={.port=&port};struct controller ctrl={.state=ON_STATE,.pcie=&dev};dev.ctrl=&ctrl;
 native=true;present=true;pciehp_poll_mode=false;phase=2;cleared=enabled=0;
 assert(!pciehp_runtime_resume(&dev));assert(cleared==1 && enabled==1);
 assert(!pciehp_runtime_suspend(&dev));
 /* Unrelated queued events are neither discarded nor rewritten by system resume. */
#if !LEGACY
 ctrl.pending_events=RERUN_ISR;wakes=0;assert(!pciehp_system_resume(&dev));assert(ctrl.pending_events==RERUN_ISR && wakes==1);
#endif
 printf("PCIe actual resume callbacks: legacy=%d, %u replacement/polling/PME cases PASS\n",LEGACY,cases);
 return 0;
}
