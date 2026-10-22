/* Minimal dlfcn surface for host syntax checks of vn_vbs_dl.c on machines
 * without glibc headers (Windows/zig). Not shipped in any build; the car and
 * Linux host builds use the real <dlfcn.h>.
 */
#ifndef VIETNAV_TEST_DLFCN_STUB_H
#define VIETNAV_TEST_DLFCN_STUB_H
#define RTLD_LAZY 1
#define RTLD_NOW 2
#define RTLD_GLOBAL 0x100
#define RTLD_DEFAULT ((void *)0)
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern char *dlerror(void);
#endif
