#include <stdio.h>
#include <stdint.h>
#include <string.h>

int main(){
    uint32_t M = 0x0193e893;
    uint32_t H0 = 0x9dc501c5;
    uint32_t T = 0xc44d3d4d;
    uint32_t invM = 0xf09d759b;
    uint32_t U = T * (uint64_t)invM; /* mod 2^32 */
    const char* prefix = "A3-06";
    size_t plen = strlen(prefix);
    uint32_t Hp = H0;
    for(size_t i=0;i<plen;i++) Hp = ((uint32_t)(unsigned char)prefix[i] ^ Hp) * M;

    uint64_t cnt=0;
    for(uint32_t a=1;a<256;a++){
        uint32_t H1 = ((uint32_t)a ^ Hp) * M;
        for(uint32_t b=1;b<256;b++){
            uint32_t H2 = (b ^ H1) * M;
            for(uint32_t c=1;c<256;c++){
                uint32_t H3 = (c ^ H2) * M;
                uint32_t b1 = U ^ H3;
                if(b1 >= 1 && b1 <= 255){
                    unsigned char key[64];
                    memcpy(key, prefix, plen);
                    key[plen]=(unsigned char)b1; key[plen+1]=(unsigned char)a;
                    key[plen+2]=(unsigned char)b; key[plen+3]=(unsigned char)c;
                    key[plen+4]=0;
                    /* verify */
                    uint32_t H=H0;
                    for(size_t i=0;i<plen+4;i++) H = ((uint32_t)key[i] ^ H) * M;
                    printf("FOUND len=%zu\n", plen+4);
                    for(size_t i=0;i<plen+4;i++) printf("%02x ", key[i]);
                    printf("\nKEY_STR=%s\n", key);
                    printf("verify: %08x == %08x %s\n", H, T, H==T?"OK":"FAIL");
                    return 0;
                }
                cnt++;
            }
        }
    }
    printf("not found cnt=%llu\n", (unsigned long long)cnt);
    return 1;
}
