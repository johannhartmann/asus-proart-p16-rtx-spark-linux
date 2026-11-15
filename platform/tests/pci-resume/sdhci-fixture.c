// SPDX-License-Identifier: GPL-2.0-only
/* Run the extracted production SDHCI callbacks; only their OS/MMIO edges are mocked. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define WQ_UNBOUND 1
#define WQ_MEM_RECLAIM 2
#define WQ_HIGHPRI 4
#define MMC_CAP2_CQE 1
#define SDHCI_QUIRK_BROKEN_CQE 1
#define MMC_PM_KEEP_POWER 1
#define SDHCI_QUIRK2_HOST_OFF_CARD_ON 2
#define SDHCI_USE_SDMA 1
#define SDHCI_USE_ADMA 2
#define SDHCI_USE_64_BIT_DMA 4
#define SDHCI_DEVICE_DEAD 8
#define MMC_POWER_ON 2
#define SDHCI_INT_ENABLE 0
#define SDHCI_SIGNAL_ENABLE 4
#define pr_err(...) ((void)0)
#define pr_info(...) ((void)0)
#define INIT_WORK(...) ((void)0)
#define timer_setup(...) ((void)0)
#define init_waitqueue_head(...) ((void)0)
#define timer_delete_sync(...) ((void)0)
#define spin_lock_irqsave(p,f) ((f)=0)
#define spin_unlock_irqrestore(p,f) ((void)(f))
struct mmc_host;
struct mmc_ios {int power_mode;};
struct mmc_ops {int (*start_signal_voltage_switch)(struct mmc_host*,struct mmc_ios*);void (*set_ios)(struct mmc_host*,struct mmc_ios*);};
struct mmc_host {unsigned caps2,pm_flags;void *cqe_ops;struct mmc_ops *ops;struct mmc_ios ios;struct {void *vqmmc;} supply;};
struct sdhci_host;
struct sdhci_ops {int (*enable_dma)(struct sdhci_host*);};
struct sdhci_host {struct mmc_host *mmc;struct sdhci_ops *ops;unsigned flags,quirks,quirks2,ier,pwr,clock;bool reinit_uhs,irq_requested,irq_wake_enabled,use_external_dma,sdhci_core_to_disable_vqmmc;int irq,lock;void *complete_wq,*align_buffer,*adma_table;size_t align_buffer_sz,adma_table_sz,align_addr;};
static bool irq_live,may_wake,wake_available,fail_irq,fail_wq;
static unsigned free_count,double_free,request_count,wake_depth;static int led_error,mmc_error;
static void *alloc_workqueue(const char *n,unsigned f,int count) {(void)n;(void)f;(void)count;return fail_wq?NULL:(void*)1;}
static int request_irq_action(struct sdhci_host *host) {assert(!irq_live);request_count++;if(fail_irq)return -EIO;irq_live=true;return 0;}
#define request_threaded_irq(...) request_irq_action(host)
static void free_irq(int irq,void *host) {if(!irq_live)double_free++;else irq_live=false;free_count++;}
static bool device_may_wakeup(void *dev) {return may_wake;}
static void *mmc_dev(struct mmc_host *mmc) {return mmc;}
static void sdhci_disable_card_detection(struct sdhci_host *h) {}
static void sdhci_enable_card_detection(struct sdhci_host *h) {}
static void mmc_retune_timer_stop(struct mmc_host *h) {}
static int disable_irq_wake(int irq) {assert(wake_depth);wake_depth--;return 0;}
static bool sdhci_enable_irq_wakeups(struct sdhci_host *h) {h->irq_wake_enabled=wake_available;if(wake_available)wake_depth++;return wake_available;}
static void sdhci_disable_irq_wakeups(struct sdhci_host *h) {disable_irq_wake(h->irq);h->irq_wake_enabled=false;}
static void sdhci_writel(struct sdhci_host *h,unsigned v,unsigned r) {}
static void sdhci_init(struct sdhci_host *h,int soft) {}
static int sdhci_led_register(struct sdhci_host *h) {return led_error;}
static void sdhci_led_unregister(struct sdhci_host *h) {}
static int mmc_add_host(struct mmc_host *h) {return mmc_error;}
static void mmc_remove_host(struct mmc_host *h) {}
static void sdhci_reset_for_all(struct sdhci_host *h) {}
static void destroy_workqueue(void *w) {}
static bool sdhci_has_requests(struct sdhci_host *h) {return false;}
static void sdhci_error_out_mrqs(struct sdhci_host *h,int err) {}
static void regulator_disable(void *r) {}
static void dma_free_coherent(void *d,size_t s,void *p,size_t a) {}
static void sdhci_external_dma_release(struct sdhci_host *h) {}
#include "sdhci.inc"
static struct mmc_host mmc;static struct sdhci_host host;static struct sdhci_ops ops;
static void reset(void) {memset(&mmc,0,sizeof(mmc));memset(&host,0,sizeof(host));host.mmc=&mmc;host.ops=&ops;irq_live=may_wake=wake_available=fail_irq=fail_wq=false;led_error=mmc_error=0;free_count=double_free=request_count=wake_depth=0;}
static void add(void) {assert(!__sdhci_add_host(&host));assert(irq_live);if(!LEGACY)assert(host.irq_requested);}
int main(void) {
 reset();add();sdhci_remove_host(&host,0);assert(!irq_live && free_count==1 && !double_free);
 reset();add();assert(!sdhci_suspend_host(&host));assert(!irq_live && free_count==1);sdhci_remove_host(&host,1);assert(!irq_live && double_free==LEGACY && free_count==(LEGACY?2:1));
 reset();add();assert(!sdhci_suspend_host(&host));assert(!sdhci_resume_host(&host));assert(irq_live);sdhci_remove_host(&host,0);assert(!irq_live && free_count==2 && !double_free && request_count==2);
 reset();add();assert(!sdhci_suspend_host(&host));fail_irq=true;assert(sdhci_resume_host(&host)==-EIO);assert(!irq_live);sdhci_remove_host(&host,1);assert(double_free==LEGACY && free_count==(LEGACY?2:1));
 reset();add();may_wake=wake_available=true;assert(!sdhci_suspend_host(&host));assert(irq_live && !free_count);assert(!sdhci_resume_host(&host));assert(irq_live && request_count==1);sdhci_remove_host(&host,0);assert(!irq_live && free_count==1 && !double_free);
 reset();add();may_wake=wake_available=true;assert(!sdhci_suspend_host(&host));assert(irq_live && wake_depth==1);sdhci_remove_host(&host,1);assert(!irq_live && wake_depth==(unsigned)LEGACY);
 reset();add();may_wake=true;wake_available=false;assert(!sdhci_suspend_host(&host));assert(!irq_live);sdhci_remove_host(&host,1);assert(double_free==LEGACY);
 reset();fail_irq=true;assert(__sdhci_add_host(&host)==-EIO);assert(!free_count && !irq_live);
 reset();fail_wq=true;assert(__sdhci_add_host(&host)==-ENOMEM);assert(!free_count && !request_count);
 reset();led_error=-EIO;assert(__sdhci_add_host(&host)==-EIO);assert(free_count==1 && !irq_live && !double_free);
 reset();mmc_error=-EIO;assert(__sdhci_add_host(&host)==-EIO);assert(free_count==1 && !irq_live && !double_free);
 printf("SDHCI actual callbacks: legacy=%d, 11 lifecycle/error cases PASS\n",LEGACY);
 return 0;
}
