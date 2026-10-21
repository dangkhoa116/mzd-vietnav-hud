// SPDX-License-Identifier: AGPL-3.0-or-later
#include "hud_codec.h"
#include <openssl/evp.h>
#include <iostream>
#include <string>
#include <vector>
#include <random>
#include <cstdlib>

static bool sum(const uint8_t *p,size_t n,const uint8_t *uid,uint8_t *out) {
    auto *ctx=EVP_MD_CTX_new();if (!ctx) return false;
    uint8_t d[16];unsigned size=0;
    bool ok=EVP_DigestInit_ex(ctx,EVP_md5(),nullptr)==1 && EVP_DigestUpdate(ctx,p,n)==1 &&
        EVP_DigestUpdate(ctx,uid,16)==1 && EVP_DigestFinal_ex(ctx,d,&size)==1 && size==16;
    EVP_MD_CTX_free(ctx);
    if (ok) vmhud::put32(out,vmhud::be32(d)+vmhud::be32(d+4)+vmhud::be32(d+8)+vmhud::be32(d+12));
    return ok;
}
static std::vector<uint8_t> unhex(const std::string &s) {
    if (s.size()%2) std::exit(2);
    std::vector<uint8_t> result;
    for (size_t i=0;i<s.size();i+=2) result.push_back(uint8_t(std::stoul(s.substr(i,2),nullptr,16)));
    return result;
}
static void hex(const uint8_t *p,size_t n) {
    const char *digits="0123456789abcdef";
    for (size_t i=0;i<n;i++) std::cout<<digits[p[i]>>4]<<digits[p[i]&15];
}
static void handle(const vmhud::Frame &frame,void *) {
    std::cout<<"{\"cmd\":"<<unsigned(frame.command)<<",\"legacy\":"<<(frame.legacy?"true":"false")<<",\"payload\":\"";
    hex(frame.payload,frame.size);std::cout<<"\"}\n";
}
static void ignore(const vmhud::Frame &,void *) {}
int main(int argc,char **argv) {
    if (argc<2) return 2;
    const std::string mode=argv[1];
    if (mode=="build" && argc==6) {
        const auto data=unhex(argv[5]);uint8_t out[8192];
        const size_t n=vmhud::build(uint8_t(std::stoul(argv[2])),data.data(),data.size(),uint32_t(std::stoul(argv[4])),
                                   out,sizeof(out),sum,std::string(argv[3])=="legacy");
        if (!n) return 3;
        hex(out,n);std::cout<<'\n';return 0;
    }
    if (mode=="feed" && argc==3) {
        vmhud::Receiver<4096> rx;const std::string chunks=argv[2];size_t offset=0;
        for (;;) {
            const size_t end=chunks.find(',',offset);
            const auto bytes=unhex(chunks.substr(offset,end==std::string::npos?end:end-offset));
            rx.feed(bytes.data(),bytes.size(),sum,handle,nullptr);
            if (end==std::string::npos) break;
            offset=end+1;
        }
        return 0;
    }
    if (mode=="nav" && argc==5) {
        const auto bytes=unhex(argv[4]);vmhud::Frame frame;
        frame.command=uint8_t(std::stoul(argv[2]));frame.legacy=std::string(argv[3])=="legacy";
        frame.payload=bytes.data();frame.size=bytes.size();vmhud::Nav nav;
        if (!vmhud::navigation(frame,nav)) { std::cout<<"null\n";return 0; }
        std::cout<<"{\"layout\":\""<<nav.layout<<"\",\"direction\":"<<unsigned(nav.direction)
                 <<",\"distance\":"<<nav.distance<<",\"hours\":"<<nav.hours<<",\"minutes\":"<<unsigned(nav.minutes)
                 <<",\"third_raw\":"<<unsigned(nav.timeThird)<<",\"remaining\":"<<nav.remainingDistance
                 <<",\"speed_raw\":"<<nav.speed<<",\"next_hex\":\"";
        hex(nav.next,nav.nextSize);std::cout<<"\",\"current_hex\":\"";hex(nav.current,nav.currentSize);std::cout<<"\"}\n";
        return 0;
    }
    if (mode=="fuzz") {
        std::mt19937 random(0x5631);vmhud::Receiver<4096> rx;
        for (unsigned i=0;i<50000;i++) {
            std::vector<uint8_t> data(random()%6000);
            for (auto &byte:data) byte=uint8_t(random());
            rx.feed(data.data(),data.size(),sum,ignore,nullptr);
            vmhud::Frame frame;vmhud::Nav nav;
            frame.payload=data.data();frame.size=data.size();frame.command=(i&1)?0:0x40;frame.legacy=i%3==0;
            vmhud::navigation(frame,nav);
            for (size_t n=0;n<32;n++) {
                uint8_t guarded[40];memset(guarded,0xa5,sizeof(guarded));
                vmhud::build(0,data.data(),data.size(),0,guarded+4,n,sum,i%2);
                for (unsigned k=0;k<4;k++) if (guarded[k]!=0xa5 || guarded[36+k]!=0xa5) return 4;
            }
        }
        std::cout<<"50000 malformed inputs PASS\n";return 0;
    }
    return 2;
}
