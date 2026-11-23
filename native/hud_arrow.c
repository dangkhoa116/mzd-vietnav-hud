/* SPDX-License-Identifier: AGPL-3.0-or-later */
#include "hud_arrow.h"
#include "vendor/picojpeg/picojpeg.h"
#define MAX_SIDE 128u
static unsigned char bitmap[MAX_SIDE * MAX_SIDE], query[VN_ARROW_PIXELS];
struct input { const unsigned char *bytes; unsigned size, at; };

static unsigned char read_bytes(unsigned char *out, unsigned char count,
                                 unsigned char *actual, void *user)
{
    struct input *in = (struct input *)user;
    unsigned i, n = in->size - in->at;
    if (n > count) n = count;
    for (i = 0; i < n; i++) out[i] = in->bytes[in->at++];
    *actual = (unsigned char)n;
    return n ? 0 : PJPG_STREAM_READ_ERROR;
}
int vn_arrow_model_valid(const unsigned char *m, unsigned n)
{
    unsigned i, count;
    uint32_t hash = 2166136261u, expected;
    if (!m || n < 12 || n > VN_ARROW_MODEL_MAX || m[0]!='V' || m[1]!='N' ||
        m[2]!='A' || m[3]!='1' || m[4]!=VN_ARROW_SIDE || m[5]!=1) return 0;
    count = ((unsigned)m[6]<<8) | m[7];
    if (!count || count > 256 || n != 12 + count * VN_ARROW_RECORD) return 0;
    expected = ((uint32_t)m[8]<<24) | ((uint32_t)m[9]<<16) | ((uint32_t)m[10]<<8) | m[11];
    for (i=12;i<n;i++) hash = (hash ^ m[i]) * 16777619u;
    if (hash != expected) return 0;
    for (i=0;i<count;i++) {
        const unsigned char *r=m+12+i*VN_ARROW_RECORD;
        if (!r[0] || r[0]>72 || !r[1] || r[1]>16 || r[2] || r[3]) return 0;
    }
    return 1;
}
int vn_arrow_vector_gray(const unsigned char *p, unsigned w, unsigned h,
                         unsigned char out[VN_ARROW_PIXELS])
{
    unsigned x,y,xx,yy,x0,x1,y0,y1,sum,count;
    if (!p || !out || !w || !h || w>MAX_SIDE || h>MAX_SIDE) return 0;
    for (y=0;y<VN_ARROW_SIDE;y++) for (x=0;x<VN_ARROW_SIDE;x++) {
        x0=x*w/VN_ARROW_SIDE;x1=(x+1)*w/VN_ARROW_SIDE;
        y0=y*h/VN_ARROW_SIDE;y1=(y+1)*h/VN_ARROW_SIDE;
        if (x1<=x0) x1=x0+1;
        if (y1<=y0) y1=y0+1;
        sum=count=0;
        for (yy=y0;yy<y1;yy++) for (xx=x0;xx<x1;xx++) { sum+=p[yy*w+xx];count++; }
        out[y*VN_ARROW_SIDE+x]=(unsigned char)((sum+count/2)/count);
    }
    return 1;
}
static int jpeg_vector(const unsigned char *p, unsigned n)
{
    pjpeg_image_info_t info;
    struct input input={p,n,0};
    unsigned mx,my,x,y,px,py,offset,gray;
    if (!p || n<4 || n>8192 || p[0]!=0xff || p[1]!=0xd8 ||
        p[n-2]!=0xff || p[n-1]!=0xd9) return 0;
    if (pjpeg_decode_init(&info,read_bytes,&input,0) || info.m_width<=0 ||
        info.m_height<=0 || info.m_width>(int)MAX_SIDE || info.m_height>(int)MAX_SIDE ||
        (info.m_comps!=1 && info.m_comps!=3) ||
        (info.m_MCUWidth!=8 && info.m_MCUWidth!=16) ||
        (info.m_MCUHeight!=8 && info.m_MCUHeight!=16)) return 0;
    for (my=0;my<(unsigned)info.m_MCUSPerCol;my++)
        for (mx=0;mx<(unsigned)info.m_MCUSPerRow;mx++) {
            if (pjpeg_decode_mcu()) return 0;
            for (y=0;y<(unsigned)info.m_MCUHeight;y++)
                for (x=0;x<(unsigned)info.m_MCUWidth;x++) {
                    px=mx*(unsigned)info.m_MCUWidth+x;
                    py=my*(unsigned)info.m_MCUHeight+y;
                    if (px>=(unsigned)info.m_width || py>=(unsigned)info.m_height) continue;
                    offset=(y/8)*128+(x/8)*64+(y%8)*8+x%8;
                    gray=info.m_pMCUBufR[offset];
                    if (info.m_comps==3)
                        gray=(77*gray+150u*info.m_pMCUBufG[offset]+29u*info.m_pMCUBufB[offset]+128)/256;
                    bitmap[py*(unsigned)info.m_width+px]=(unsigned char)gray;
                }
        }
    return vn_arrow_vector_gray(bitmap,(unsigned)info.m_width,(unsigned)info.m_height,query);
}
/* Squared normalized correlation, using integer moments and double ratios.
 * No sqrt/libm needed. Negative correlation and near-flat images are rejected. */
static double score(const unsigned char *a,const unsigned char *b)
{
    uint64_t sa=0,sb=0,aa=0,bb=0,ab=0,va,vb;
    int64_t covariance;
    unsigned i;
    for (i=0;i<VN_ARROW_PIXELS;i++) {
        sa+=a[i];sb+=b[i];aa+=(unsigned)a[i]*a[i];bb+=(unsigned)b[i]*b[i];
        ab+=(unsigned)a[i]*b[i];
    }
    va=VN_ARROW_PIXELS*aa-sa*sa;vb=VN_ARROW_PIXELS*bb-sb*sb;
    covariance=(int64_t)(VN_ARROW_PIXELS*ab)-(int64_t)(sa*sb);
    if (covariance<=0 || va<4u*VN_ARROW_PIXELS*VN_ARROW_PIXELS ||
        vb<4u*VN_ARROW_PIXELS*VN_ARROW_PIXELS) return 0;
    return (double)covariance*(double)covariance/((double)va*(double)vb);
}
int vn_arrow_match(const unsigned char *m,unsigned size,const unsigned char *jpeg,
                   unsigned jpeg_size,struct vn_arrow_result *out)
{
    double best=0,other=0,current;
    unsigned i,count,best_index=0;
    const unsigned char *r;
    if (!out) return 0;
    out->icon=out->group=out->score_squared_milli=out->margin_squared_milli=0;
    if (!vn_arrow_model_valid(m,size) || !jpeg_vector(jpeg,jpeg_size)) return 0;
    count=((unsigned)m[6]<<8)|m[7];
    for (i=0;i<count;i++) {
        current=score(query,m+12+i*VN_ARROW_RECORD+4);
        if (current>best) { best=current;best_index=i; }
    }
    r=m+12+best_index*VN_ARROW_RECORD;
    for (i=0;i<count;i++) if (m[12+i*VN_ARROW_RECORD+1]!=r[1]) {
        current=score(query,m+12+i*VN_ARROW_RECORD+4);
        if (current>other) other=current;
    }
    out->score_squared_milli=(unsigned)(best*1000);
    out->margin_squared_milli=(unsigned)((best-other>0?best-other:0)*1000);
    if (best<0.81 || best-other<0.02) return 0;
    out->icon=r[0];out->group=r[1];return 1;
}
