/*
 * native_runner.c - Minimal ELF loader and test harness for freestanding
 * aarch64 candidate executables produced by Phase 2 Step G.
 *
 * Usage:
 *   native_runner <candidate_exe> <in_hex> <out_cap> <symbol>
 *   native_runner --selftest
 *
 * Protocol:
 *   Prints RET=<signed decimal i64> and OUT=<lowercase hex bytes> to stdout.
 *   Exit code is always 0 for semantic results; non-zero only for usage errors.
 *
 * Dependencies: libc only (no dlopen, no libelf, no LLVM).
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <elf.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#define MAX_INPUT_BYTES  65536
#define MAX_OUTPUT_BYTES 65536
#define ERR_INTERNAL     ((int64_t)-3)

typedef int64_t (*candidate_fn)(uint8_t *, int32_t, uint8_t *, int32_t);

/* ------------------------------------------------------------------ */
/* Hex utilities                                                      */
/* ------------------------------------------------------------------ */

static int hex_val(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* Decode hex string into out[]. Returns byte count or -1 on error. */
static int hex_decode(const char *hex, uint8_t *out, int max_out)
{
    int len = (int)strlen(hex);
    if (len % 2 != 0) return -1;
    int nbytes = len / 2;
    if (nbytes > max_out) return -1;
    for (int i = 0; i < nbytes; i++) {
        int hi = hex_val(hex[2 * i]);
        int lo = hex_val(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return nbytes;
}

/* Encode bytes to lowercase hex string. out must hold 2*len+1 bytes. */
static void hex_encode(const uint8_t *data, int len, char *out)
{
    static const char digits[] = "0123456789abcdef";
    for (int i = 0; i < len; i++) {
        out[2 * i]     = digits[(data[i] >> 4) & 0xf];
        out[2 * i + 1] = digits[data[i] & 0xf];
    }
    out[2 * len] = '\0';
}

static void emit_error(void)
{
    printf("RET=%" PRId64 "\n", ERR_INTERNAL);
    printf("OUT=\n");
}

/* ------------------------------------------------------------------ */
/* Self-test (hex roundtrip)                                          */
/* ------------------------------------------------------------------ */

static int selftest(void)
{
    const char *test_hex = "0123456789abcdef";
    uint8_t buf[8];
    int n = hex_decode(test_hex, buf, 8);
    if (n != 8) return 1;
    char out[17];
    hex_encode(buf, 8, out);
    if (strcmp(out, test_hex) != 0) return 1;

    /* Empty roundtrip. */
    n = hex_decode("", buf, 8);
    if (n != 0) return 1;
    hex_encode(buf, 0, out);
    if (strcmp(out, "") != 0) return 1;

    /* Odd-length rejection. */
    if (hex_decode("abc", buf, 8) != -1) return 1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* Minimal ELF64 loader                                               */
/* ------------------------------------------------------------------ */

struct loaded_elf {
    void  *base;       /* mmap'd region base                          */
    size_t map_size;   /* total mapped size                           */
    void  *func;       /* resolved function pointer                   */
};

static int load_elf(const char *path, const char *symbol,
                    struct loaded_elf *out)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "native_runner: cannot open %s\n", path);
        return -1;
    }

    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size < (off_t)sizeof(Elf64_Ehdr)) {
        fprintf(stderr, "native_runner: file too small or stat failed\n");
        close(fd);
        return -1;
    }

    size_t file_size = (size_t)st.st_size;

    /* Map the file read-only for header parsing. */
    uint8_t *fdata = (uint8_t *)mmap(NULL, file_size, PROT_READ,
                                     MAP_PRIVATE, fd, 0);
    close(fd);
    if (fdata == MAP_FAILED) {
        fprintf(stderr, "native_runner: mmap file failed\n");
        return -1;
    }

    Elf64_Ehdr *ehdr = (Elf64_Ehdr *)fdata;

    /* ---------- basic validation ---------- */
    if (memcmp(ehdr->e_ident, ELFMAG, SELFMAG) != 0 ||
        ehdr->e_ident[EI_CLASS] != ELFCLASS64 ||
        ehdr->e_ident[EI_DATA]  != ELFDATA2LSB ||
        ehdr->e_machine != EM_AARCH64) {
        fprintf(stderr, "native_runner: not a valid aarch64 ELF64 LE file\n");
        goto fail_file;
    }
    if (ehdr->e_type != ET_DYN && ehdr->e_type != ET_EXEC) {
        fprintf(stderr, "native_runner: unsupported ELF type %u\n",
                ehdr->e_type);
        goto fail_file;
    }

    /* ---------- compute PT_LOAD extent ---------- */
    if (ehdr->e_phoff + (uint64_t)ehdr->e_phnum * ehdr->e_phentsize
        > file_size) {
        fprintf(stderr, "native_runner: program headers out of bounds\n");
        goto fail_file;
    }
    Elf64_Phdr *phdrs = (Elf64_Phdr *)(fdata + ehdr->e_phoff);

    uint64_t vmin = UINT64_MAX, vmax = 0;
    int has_load = 0;

    for (int i = 0; i < ehdr->e_phnum; i++) {
        if (phdrs[i].p_type != PT_LOAD) continue;
        has_load = 1;
        uint64_t lo = phdrs[i].p_vaddr;
        uint64_t hi = phdrs[i].p_vaddr + phdrs[i].p_memsz;
        if (lo < vmin) vmin = lo;
        if (hi > vmax) vmax = hi;
    }
    if (!has_load) {
        fprintf(stderr, "native_runner: no PT_LOAD segments\n");
        goto fail_file;
    }

    long pgsz = sysconf(_SC_PAGESIZE);
    uint64_t mask = (uint64_t)pgsz - 1;
    vmin &= ~mask;
    vmax  = (vmax + mask) & ~mask;
    size_t map_size = (size_t)(vmax - vmin);

    /* ---------- reserve region, copy segments ---------- */
    uint8_t *base = (uint8_t *)mmap(NULL, map_size,
                                    PROT_READ | PROT_WRITE,
                                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) {
        fprintf(stderr, "native_runner: mmap reserve failed (%zu)\n",
                map_size);
        goto fail_file;
    }

    for (int i = 0; i < ehdr->e_phnum; i++) {
        if (phdrs[i].p_type != PT_LOAD) continue;
        uint64_t off  = phdrs[i].p_offset;
        uint64_t fsz  = phdrs[i].p_filesz;
        uint64_t va   = phdrs[i].p_vaddr;
        uint64_t msz  = phdrs[i].p_memsz;

        if (off + fsz > file_size) {
            fprintf(stderr, "native_runner: segment %d past EOF\n", i);
            goto fail_both;
        }
        if (fsz > 0)
            memcpy(base + (va - vmin), fdata + off, (size_t)fsz);
        if (msz > fsz)
            memset(base + (va - vmin) + fsz, 0, (size_t)(msz - fsz));
    }

    /* ---------- icache coherence (aarch64 requirement) ---------- */
    __builtin___clear_cache((char *)base, (char *)(base + map_size));

    /* ---------- set final permissions per segment ---------- */
    for (int i = 0; i < ehdr->e_phnum; i++) {
        if (phdrs[i].p_type != PT_LOAD) continue;
        uint64_t va  = phdrs[i].p_vaddr;
        uint64_t msz = phdrs[i].p_memsz;

        uint64_t page_off    = va & mask;
        uint64_t aligned_va  = va - page_off;
        uint64_t aligned_sz  = (msz + page_off + mask) & ~mask;
        void    *seg_base    = base + (aligned_va - vmin);

        int prot = 0;
        if (phdrs[i].p_flags & PF_R) prot |= PROT_READ;
        if (phdrs[i].p_flags & PF_W) prot |= PROT_WRITE;
        if (phdrs[i].p_flags & PF_X) prot |= PROT_EXEC;

        if (mprotect(seg_base, (size_t)aligned_sz, prot) < 0) {
            fprintf(stderr, "native_runner: mprotect failed segment %d\n", i);
            goto fail_both;
        }
    }

    /* ---------- check for relocations (fail closed) ---------- */
    if (ehdr->e_shoff + (uint64_t)ehdr->e_shnum * ehdr->e_shentsize
        <= file_size) {
        Elf64_Shdr *shdrs = (Elf64_Shdr *)(fdata + ehdr->e_shoff);
        for (int i = 0; i < ehdr->e_shnum; i++) {
            if ((shdrs[i].sh_type == SHT_RELA ||
                 shdrs[i].sh_type == SHT_REL) && shdrs[i].sh_size > 0) {
                fprintf(stderr,
                        "native_runner: ELF has relocations (unsupported)\n");
                goto fail_both;
            }
        }
    }

    /* ---------- symbol lookup in .symtab ---------- */
    void *func_ptr = NULL;

    if (ehdr->e_shoff + (uint64_t)ehdr->e_shnum * ehdr->e_shentsize
        <= file_size) {
        Elf64_Shdr *shdrs = (Elf64_Shdr *)(fdata + ehdr->e_shoff);
        for (int i = 0; i < ehdr->e_shnum; i++) {
            if (shdrs[i].sh_type != SHT_SYMTAB) continue;
            if (shdrs[i].sh_offset + shdrs[i].sh_size > file_size) break;
            int link = (int)shdrs[i].sh_link;
            if (link < 0 || link >= ehdr->e_shnum) break;
            if (shdrs[link].sh_offset + shdrs[link].sh_size > file_size)
                break;

            Elf64_Sym  *syms = (Elf64_Sym *)(fdata + shdrs[i].sh_offset);
            const char *strs = (const char *)(fdata + shdrs[link].sh_offset);
            int nsyms = (int)(shdrs[i].sh_size / shdrs[i].sh_entsize);

            for (int j = 0; j < nsyms; j++) {
                if (ELF64_ST_TYPE(syms[j].st_info) != STT_FUNC) continue;
                if (syms[j].st_shndx == SHN_UNDEF) continue;
                if (syms[j].st_name >= shdrs[link].sh_size) continue;
                if (strcmp(strs + syms[j].st_name, symbol) == 0) {
                    func_ptr = base + (syms[j].st_value - vmin);
                    break;
                }
            }
            break; /* only process first .symtab */
        }
    }

    /* Fallback: entry point (only for the expected symbol). */
    if (!func_ptr && strcmp(symbol, "f") == 0 && ehdr->e_entry != 0) {
        func_ptr = base + (ehdr->e_entry - vmin);
    }

    if (!func_ptr) {
        fprintf(stderr, "native_runner: symbol '%s' not found\n", symbol);
        goto fail_both;
    }

    munmap(fdata, file_size);

    out->base     = base;
    out->map_size = map_size;
    out->func     = func_ptr;
    return 0;

fail_both:
    munmap(base, map_size);
fail_file:
    munmap(fdata, file_size);
    return -1;
}

static void unload_elf(struct loaded_elf *elf)
{
    if (elf->base && elf->map_size > 0)
        munmap(elf->base, elf->map_size);
    elf->base     = NULL;
    elf->map_size = 0;
    elf->func     = NULL;
}

/* ------------------------------------------------------------------ */
/* main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[])
{
    if (argc == 2 && strcmp(argv[1], "--selftest") == 0)
        return selftest();

    if (argc != 5) {
        fprintf(stderr,
                "usage: native_runner <candidate_exe> <in_hex>"
                " <out_cap> <symbol>\n"
                "       native_runner --selftest\n");
        return 1;
    }

    const char *exe_path = argv[1];
    const char *in_hex   = argv[2];
    int out_cap          = atoi(argv[3]);
    const char *symbol   = argv[4];

    /* Validate caps. */
    if (out_cap < 0 || out_cap > MAX_OUTPUT_BYTES) {
        fprintf(stderr, "native_runner: out_cap %d out of range\n", out_cap);
        emit_error();
        return 0;
    }
    int in_hex_len = (int)strlen(in_hex);
    if (in_hex_len / 2 > MAX_INPUT_BYTES) {
        fprintf(stderr, "native_runner: input too large\n");
        emit_error();
        return 0;
    }

    /* Decode input. */
    uint8_t *in_buf = NULL;
    int in_len = 0;
    if (in_hex_len > 0) {
        in_buf = (uint8_t *)malloc((size_t)(in_hex_len / 2));
        if (!in_buf) {
            fprintf(stderr, "native_runner: malloc input failed\n");
            emit_error();
            return 0;
        }
        in_len = hex_decode(in_hex, in_buf, in_hex_len / 2);
        if (in_len < 0) {
            fprintf(stderr, "native_runner: bad hex input\n");
            free(in_buf);
            emit_error();
            return 0;
        }
    }

    /* Allocate output buffer (always valid pointer, even if cap=0). */
    uint8_t *out_buf = (uint8_t *)calloc(1, out_cap > 0
                                            ? (size_t)out_cap : 1);
    if (!out_buf) {
        fprintf(stderr, "native_runner: malloc output failed\n");
        free(in_buf);
        emit_error();
        return 0;
    }

    /* Load ELF. */
    struct loaded_elf elf;
    memset(&elf, 0, sizeof(elf));
    if (load_elf(exe_path, symbol, &elf) < 0) {
        free(in_buf);
        free(out_buf);
        emit_error();
        return 0;
    }

    /* Call the candidate function. */
    candidate_fn fn = (candidate_fn)elf.func;
    int64_t ret = fn(in_buf  ? in_buf  : out_buf,   /* valid ptr */
                     (int32_t)in_len,
                     out_buf,
                     (int32_t)out_cap);

    /* Emit results. */
    printf("RET=%" PRId64 "\n", ret);

    if (ret > 0) {
        int nbytes = (int)ret;
        if (nbytes > out_cap) nbytes = out_cap; /* clamp for safety */
        char *hex_out = (char *)malloc((size_t)(2 * nbytes + 1));
        if (hex_out) {
            hex_encode(out_buf, nbytes, hex_out);
            printf("OUT=%s\n", hex_out);
            free(hex_out);
        } else {
            printf("OUT=\n");
        }
    } else {
        printf("OUT=\n");
    }

    unload_elf(&elf);
    free(in_buf);
    free(out_buf);
    return 0;
}
