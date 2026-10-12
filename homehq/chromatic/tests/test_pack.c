#include "homehq_pack.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv)
{
    assert(argc==2);
    FILE *f=fopen(argv[1],"rb");assert(f);
    char source[32768];size_t length=fread(source,1,sizeof(source),f);fclose(f);
    size_t n=0, recovered=0;
    uint8_t *packed=HQ_Pack(source,length,&n);assert(packed);
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
        plain=HQ_Unpack(packed,n,&recovered);assert(plain && recovered==size && !memcmp(source,plain,size));
        free(plain);free(packed);
    }
    puts("Compression boundaries and corrupt/truncated input PASS");return 0;
}
