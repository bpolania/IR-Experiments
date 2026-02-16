/*
Frozen Experiment 1 LLI shim

ABI authority for candidate function:
  int64_t f(uint8_t* in_ptr, int32_t in_len, uint8_t* out_ptr, int32_t out_cap)

CLI contract when run under lli:
  argv[1] = in_hex
  argv[2] = out_cap (base-10 integer)
  argv[3] = entry symbol (must be "f")

Stdout contract (for lli_abi_runner.py parsing):
  RET=<signed_int64>\n
  OUT=<lowercase_hex>\n

No nondeterministic behavior.
*/

#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern int64_t f(uint8_t *in_ptr, int32_t in_len, uint8_t *out_ptr, int32_t out_cap);

static int hex_nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  return -1;
}

static int decode_hex(const char *hex, uint8_t **out_buf, size_t *out_len) {
  size_t n = strlen(hex);
  if ((n % 2) != 0) return -1;
  *out_len = n / 2;
  if (*out_len == 0) {
    *out_buf = NULL;
    return 0;
  }

  uint8_t *buf = (uint8_t *)malloc(*out_len);
  if (!buf) return -2;

  for (size_t i = 0; i < *out_len; i++) {
    int hi = hex_nibble(hex[2 * i]);
    int lo = hex_nibble(hex[2 * i + 1]);
    if (hi < 0 || lo < 0) {
      free(buf);
      return -1;
    }
    buf[i] = (uint8_t)((hi << 4) | lo);
  }

  *out_buf = buf;
  return 0;
}

int main(int argc, char **argv) {
  if (argc < 4) {
    printf("RET=-3\nOUT=\n");
    return 2;
  }

  const char *in_hex = argv[1];
  const char *out_cap_s = argv[2];
  const char *entry = argv[3];

  if (strcmp(entry, "f") != 0) {
    printf("RET=-3\nOUT=\n");
    return 3;
  }

  char *end = NULL;
  unsigned long out_cap_ul = strtoul(out_cap_s, &end, 10);
  if (end == out_cap_s || *end != '\0' || out_cap_ul > 2147483647UL) {
    printf("RET=-3\nOUT=\n");
    return 4;
  }
  int32_t out_cap = (int32_t)out_cap_ul;

  uint8_t *in_buf = NULL;
  size_t in_len = 0;
  int dec = decode_hex(in_hex, &in_buf, &in_len);
  if (dec != 0 || in_len > 2147483647UL) {
    if (in_buf) free(in_buf);
    printf("RET=-1\nOUT=\n");
    return 0;
  }

  uint8_t *out_buf = NULL;
  if (out_cap > 0) {
    out_buf = (uint8_t *)calloc((size_t)out_cap, 1);
    if (!out_buf) {
      free(in_buf);
      printf("RET=-3\nOUT=\n");
      return 5;
    }
  }

  int64_t ret = f(in_buf, (int32_t)in_len, out_buf, out_cap);
  printf("RET=%lld\n", (long long)ret);
  printf("OUT=");

  size_t out_len = 0;
  if (ret > 0) {
    out_len = (size_t)ret;
    if (out_len > (size_t)out_cap) out_len = (size_t)out_cap;
  }
  for (size_t i = 0; i < out_len; i++) {
    printf("%02x", out_buf[i]);
  }
  printf("\n");

  free(in_buf);
  free(out_buf);
  return 0;
}
