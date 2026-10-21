/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Fake bds: real nonblocking PTY + poll + both read entry points.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
extern ssize_t __read_chk(int, void *, size_t, size_t);
static unsigned long long clock_ms(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (unsigned long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
int main(int argc, char **argv) {
  unsigned char b[1024], cmd[] = {1, 0x1a, 0x0c, 1, 2};
  struct termios term;
  struct pollfd p;
  unsigned turn = 0;
  ssize_t n;
  unsigned long long end;
  int out, fd;
  if (argc != 4)
    return 2;
  fd = open(argv[1], O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd < 0)
    return 3;
  if (tcgetattr(fd, &term))
    return 4;
  cfmakeraw(&term);
  if (tcsetattr(fd, TCSANOW, &term))
    return 5;
  out = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (out < 0)
    return 6;
  if (write(fd, cmd, sizeof cmd) != (ssize_t)sizeof cmd)
    return 7;
  end = clock_ms() + (unsigned)atoi(argv[3]);
  while (clock_ms() < end) {
    p.fd = fd;
    p.events = POLLIN;
    p.revents = 0;
    if (poll(&p, 1, 40) < 0)
      return 8;
    /* Also call read after timeout: it must return EAGAIN without waiting. */
    n = (turn++ & 1) ? __read_chk(fd, b, sizeof b, sizeof b)
                     : read(fd, b, sizeof b);
    if (n > 0 && write(out, b, (size_t)n) != n)
      return 9;
  }
  close(fd);
  close(out);
  return 0;
}
