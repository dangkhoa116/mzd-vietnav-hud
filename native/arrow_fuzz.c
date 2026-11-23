/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_arrow.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned char model[VN_ARROW_MODEL_MAX],seed_jpeg[8192],bytes[8192];
static unsigned rng=563;
static unsigned random_byte(void) { rng=rng*1664525u+1013904223u;return rng>>24; }
int main(int argc,char **argv)
{
    FILE *f;unsigned model_size,jpeg_size,i,j,n;struct vn_arrow_result out;
    if (argc!=3) return 2;
    f=fopen(argv[1],"rb");if (!f) return 2;
    model_size=(unsigned)fread(model,1,sizeof model,f);fclose(f);
    assert(vn_arrow_model_valid(model,model_size));
    f=fopen(argv[2],"rb");if (!f) return 2;
    jpeg_size=(unsigned)fread(seed_jpeg,1,sizeof seed_jpeg,f);fclose(f);
    assert(jpeg_size>4);
    for (i=0;i<20000;i++) {
        if (i&1) {
            n=jpeg_size;memcpy(bytes,seed_jpeg,n);
            for (j=0;j<1+i%8;j++) bytes[random_byte()*37u%n]^=(unsigned char)random_byte();
        } else {
            n=(random_byte()*37u)%sizeof bytes;
            for (j=0;j<n;j++) bytes[j]=(unsigned char)random_byte();
            if (n>=4) { bytes[0]=bytes[n-2]=0xff;bytes[1]=0xd8;bytes[n-1]=0xd9; }
        }
        if (vn_arrow_match(model,model_size,bytes,n,&out)) assert(out.icon && out.icon<=72);
    }
    puts("20000 malformed/mutated JPEGs PASS");return 0;
}
