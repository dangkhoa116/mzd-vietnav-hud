/* Minimal host-test shim: only what aa_nav16_msg.h needs to compile off-Linux. */
#pragma once
#include <stddef.h>
typedef unsigned socklen_t;
#ifndef AF_UNIX
#define AF_UNIX 1
#endif
