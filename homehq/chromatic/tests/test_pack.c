#include "homehq_pack.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef HQ_PACK_COUNT_ALLOCS
extern size_t HQ_TestAllocations;
#endif

static void bounded_check(const void *source, size_t length, const uint8_t *packed, size_t n)
{
    /* An 8 KiB destination is reserved before Wi-Fi fragments the native heap.
     * Both a missing flag byte and a partial two-byte token must stop within
     * that reservation, with no successful length for an incomplete cache. */
    uint8_t guarded[32768 + 32768 / 8 + 32];
    const size_t capacities[] = {0, 1, 5, 6, 7, n - 1, n, n + 1, 8192};
    for (unsigned c = 0; c < sizeof(capacities) / sizeof(capacities[0]); ++c) {
        size_t capacity = capacities[c], wrote = 123;
        memset(guarded, 0xa5, sizeof(guarded));
#ifdef HQ_PACK_COUNT_ALLOCS
        size_t allocations = HQ_TestAllocations;
#endif
        bool ok = HQ_PackInto(source, length, guarded + 1, capacity, &wrote);
#ifdef HQ_PACK_COUNT_ALLOCS
        assert(HQ_TestAllocations == allocations);
#endif
        assert(guarded[0] == 0xa5);
        for (size_t i = capacity + 1; i < sizeof(guarded); ++i) assert(guarded[i] == 0xa5);
        assert(ok == (capacity >= n));
        assert(wrote == (ok ? n : 0));
        if (ok) assert(!memcmp(guarded + 1, packed, n));
    }
}

static void golden_check(void)
{
    static const uint8_t empty[] = {'H', 'Q', 1, 0, 0, 0};
    static const uint8_t literal[] = {'H', 'Q', 1, 0, 1, 0, 0, 'A'};
    static const uint8_t overlap[] = {'H', 'Q', 1, 0, 20, 0, 2, 'A', 15, 0, 'A'};
    static const uint8_t repeated[] = {'H', 'Q', 1, 0, 9, 0, 8, 'a', 'b', 'c', 35, 0};
    const char *sources[] = {"", "A", "AAAAAAAAAAAAAAAAAAAA", "abcabcabc"};
    const uint8_t *outputs[] = {empty, literal, overlap, repeated};
    const size_t sizes[] = {sizeof(empty), sizeof(literal), sizeof(overlap), sizeof(repeated)};
    for (unsigned i = 0; i < 4; ++i) {
        uint8_t output[32]; size_t wrote = 0;
        assert(HQ_PackInto(sources[i], strlen(sources[i]), output, sizeof(output), &wrote));
        assert(wrote == sizes[i] && !memcmp(output, outputs[i], wrote));
        bounded_check(sources[i], strlen(sources[i]), outputs[i], wrote);
    }
    uint8_t output[32]; size_t wrote = 123;
    assert(!HQ_PackInto(NULL, 1, output, sizeof(output), &wrote) && wrote == 0);
    assert(!HQ_PackInto("A", 1, NULL, sizeof(output), &wrote) && wrote == 0);
    assert(!HQ_PackInto("A", 32769, output, sizeof(output), &wrote) && wrote == 0);
    assert(!HQ_PackInto("A", 1, output, sizeof(output), NULL));
    /* Cache reads must also reject a token before the dictionary exists, an
     * overlong match and appended data, rather than manufacturing a snapshot. */
    static const uint8_t invalid[][10] = {
        {'X', 'Q', 1, 0, 1, 0, 0, 'A'},
        {'H', 'Q', 2, 0, 1, 0, 0, 'A'},
        {'H', 'Q', 1, 1, 1, 0, 0, 'A'},
        {'H', 'Q', 1, 0, 3, 0, 1, 0, 0},
        {'H', 'Q', 1, 0, 2, 0, 2, 'A', 0, 0},
        {'H', 'Q', 1, 0, 1, 0, 0, 'A', 'X'}
    };
    const size_t invalid_sizes[] = {8, 8, 8, 9, 10, 9};
    for (unsigned i = 0; i < sizeof(invalid_sizes) / sizeof(invalid_sizes[0]); ++i)
        assert(!HQ_Unpack(invalid[i], invalid_sizes[i], &wrote));
}
int main(int argc, char **argv)
{
    assert(argc==2);
    FILE *f=fopen(argv[1],"rb");assert(f);
    char source[32768];size_t length=fread(source,1,sizeof(source),f);fclose(f);
    golden_check();
    size_t n=0, recovered=0;
    uint8_t *packed=HQ_Pack(source,length,&n);assert(packed);
    bounded_check(source, length, packed, n);
    char *plain=HQ_Unpack(packed,n,&recovered);
    assert(plain && recovered==length && !memcmp(source,plain,length));
    printf("Snapshot cache: %zu -> %zu bytes; exact round-trip\n",length,n);
    free(plain);
    /* Every truncated prefix must fail cleanly, including a dangling match
     * and an incomplete literal group after a simulated interrupted write. */
    for(size_t i=0;i<n;i++){plain=HQ_Unpack(packed,i,&recovered);assert(!plain);}
    packed[4]=255;packed[5]=255;assert(!HQ_Unpack(packed,n,&recovered));free(packed);
    unsigned random=123;
    const unsigned lengths[]={0,1,2,3,7,8,9,255,256,4096,32768};
    for(unsigned c=0;c<sizeof(lengths)/sizeof(lengths[0]);c++){
        unsigned size=lengths[c];
        for(unsigned i=0;i<size;i++){random=random*1664525+1013904223;source[i]=random>>24;}
        packed=HQ_Pack(source,size,&n);assert(packed);
        bounded_check(source, size, packed, n);
        plain=HQ_Unpack(packed,n,&recovered);assert(plain && recovered==size && !memcmp(source,plain,size));
        free(plain);free(packed);
    }
    puts("Compression boundaries and corrupt/truncated input PASS");return 0;
}
