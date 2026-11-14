// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <pthread.h>
#include <unistd.h>
#include <stdlib.h>
static void *linger(void *arg) { (void)arg; for (;;) pause(); return NULL; }
static void *replace(void *arg) {
 (void)arg;usleep(1000);execl("/stress","stress",NULL);_exit(2);
}
int main(void) {
 pthread_t a,b,c;
 if(pthread_create(&a,NULL,linger,NULL)||pthread_create(&b,NULL,linger,NULL)||pthread_create(&c,NULL,replace,NULL))return 3;
 for(;;)pause();
}
