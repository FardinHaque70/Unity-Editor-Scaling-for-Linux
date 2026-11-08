/* Actual generated float payloads in anonymous memory, no Unity launch. */
#include "../source/input/input.c"
#include <assert.h>
#include <stdio.h>
#include <sys/mman.h>
static double test_factor=1.5;
int v6_conversion_snapshot(ep_snapshot*out){*out=(ep_snapshot){1,1,1,EP_CUSTOM,150,test_factor};return 0;}
struct Result {
    unsigned char frame[0x210];
    uint64_t rbx,rbp,r12,r13,r14,r15,rsp;
    unsigned char xmm0[16];
};
extern void exercise(void *code,void *event,struct Result*,int release);
extern void block_done(void);
__asm__(
".text\n"
".global exercise\n"
"exercise:\n"
"push %rbp\n push %rbx\n push %r12\n push %r13\n push %r14\n push %r15\n"
"sub $0x218,%rsp\n"
"mov %rdi,%r14\n mov %rsi,%rbx\n mov %rsi,%rbp\n mov %rdx,%r13\n"
"mov $0x12121212,%r12\n mov $0x15151515,%r15\n mov %ecx,%r11d\n"
"mov %rsp,%rdi\n mov $0x210,%ecx\n mov $0xa5,%eax\n rep stosb\n"
/* Model the original release site's outstanding two stack arguments. */
"test %r11d,%r11d\n jz 1f\n sub $16,%rsp\n"
"1: jmp *%r14\n"
".global block_done\n"
"block_done:\n"
"mov %rbx,0x210(%r13)\n mov %rbp,0x218(%r13)\n"
"mov %r12,0x220(%r13)\n mov %r13,0x228(%r13)\n"
"mov %r14,0x230(%r13)\n mov %r15,0x238(%r13)\n"
"mov %rsp,0x240(%r13)\n movdqu %xmm0,0x248(%r13)\n"
"mov %r13,%rdi\n mov %rsp,%rsi\n mov $0x210,%ecx\n rep movsb\n"
"add $0x218,%rsp\n"
"pop %r15\n pop %r14\n pop %r13\n pop %r12\n pop %rbx\n pop %rbp\n ret\n"
);

static unsigned drag_value,get_calls,drag_calls;
static int drag_token;
static void *fake_get_drag(void){++get_calls;return &drag_token;}
static unsigned char fake_is_dragging(void *p){assert(p==&drag_token);++drag_calls;return (unsigned char)drag_value;}
static void jump_to(void *destination,void *fn){
    unsigned char bytes[14]={0xff,0x25,0,0,0,0};
    memcpy(bytes+6,&fn,8);memcpy(destination,bytes,14);
}
static void value(unsigned char *p,int off,double n){memcpy(p+off,&n,8);}
static void expect_float(const unsigned char *p,float expected){float got;memcpy(&got,p,4);assert(got==expected);}
static void register_contract(const struct Result *r,void *event,void *code,int release){
    assert(r->rbx==(uintptr_t)event);
    assert(r->rbp==(release?drag_value:(uintptr_t)event));
    assert(r->r12==0x12121212 && r->r13==(uintptr_t)r);
    assert(r->r14==(uintptr_t)code && r->r15==0x15151515);
    assert((r->rsp&15)==0);
}
static void press_case(unsigned char *event,double u){
    test_factor=(double)(float)u;u=test_factor;struct Result r={0};
    void *code=(void*)(image+0x3c0094e);exercise(code,event,&r,0);
    register_contract(&r,event,code,0);
    float x=(float)(coord(event,24)/u),y=(float)(coord(event,32)/u);
    expect_float(r.frame+0x30,x);expect_float(r.frame+0x34,y);
    expect_float(r.frame+0x40,x);expect_float(r.frame+0x44,y);
    expect_float(r.frame+0x48,0);expect_float(r.frame+0x4c,0);
    expect_float(r.frame+0x28,(float)(coord(event,64)/u));
    expect_float(r.frame+0x2c,(float)(coord(event,72)/u));
    for(unsigned i=0;i<sizeof r.frame;i++)
        if(!((i>=0x28&&i<0x38)||(i>=0x40&&i<0x50)))assert(r.frame[i]==0xa5);
}
static void release_case(unsigned char *event,double u,unsigned drag){
    test_factor=(double)(float)u;u=test_factor;drag_value=drag;struct Result r={0};
    void *code=(void*)(image+0x3c00d00);exercise(code,event,&r,1);
    register_contract(&r,event,code,1);
    float x=(float)(coord(event,24)/u),y=(float)(coord(event,32)/u);
    expect_float(r.frame+0x18,x);expect_float(r.frame+0x1c,y);
    expect_float(r.xmm0,x);expect_float(r.xmm0+4,y);
    for(unsigned i=8;i<16;i++)assert(r.xmm0[i]==0);
    for(unsigned i=0;i<sizeof r.frame;i++)if(i<0x18||i>=0x20)assert(r.frame[i]==0xa5);
}
int main(void){
    /* Anonymous test memory only. No Unity process or disk ELF is written. */
    const size_t size=0x4000000;
    void *allocation=mmap(NULL,size,PROT_READ|PROT_WRITE|PROT_EXEC,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(allocation!=MAP_FAILED);uintptr_t base=(uintptr_t)allocation;
    unsigned char restore[]={0x48,0x83,0xc4,0x10};
    memcpy((void*)(base+0x3c00d00),restore,sizeof restore);
    for(unsigned i=0;i<sizeof(guards)/sizeof(*guards);i++)memcpy((void*)(base+guards[i].va),guards[i].before,guards[i].len);
    for(unsigned i=0;i<sizeof(contexts)/sizeof(*contexts);i++)memcpy((void*)(base+contexts[i].va),contexts[i].before,contexts[i].n);
    vg_patch patches[2];assert(!ns_input_prepare(base,patches));
    for(unsigned i=0;i<2;i++)memcpy((void*)(base+patches[i].va),patches[i].after,patches[i].len);
    assert(!memcmp((void*)(base+0x3c00d00),restore,sizeof restore));
    jump_to((void*)(base+0x3bc4dd0),fake_get_drag);
    jump_to((void*)(base+0x3bc5020),fake_is_dragging);
    jump_to((void*)(base+0x3c0097e),block_done);
    jump_to((void*)(base+0x3c00d2a),block_done);
    unsigned char event[80]={0},before[80];
    unsigned cases=0;
    double coords[][4]={{154.25,31.875,714.5,201.125},{-0.75,-33.25,-2048.125,0.5},{0,1,0,1},{8191.875,4095.125,10000.25,9000.5}};
    for(unsigned k=0;k<sizeof coords/sizeof coords[0];k++){
        value(event,24,coords[k][0]);value(event,32,coords[k][1]);
        value(event,64,coords[k][2]);value(event,72,coords[k][3]);
        memcpy(before,event,sizeof event);
        for(unsigned s=0;s<101;s++){
            double u=(100+s)/100.0;press_case(event,u);++cases;
            release_case(event,u,0);++cases;release_case(event,u,1);++cases;
            assert(!memcmp(before,event,sizeof event));
        }
    }
    assert(get_calls==808 && drag_calls==808);
    assert(!munmap(allocation,size));
    printf("{\"generated_block_cases\":%u,\"raw_event_unchanged\":true,\"release_stack_restored\":true,\"callee_saved_and_frame_canaries\":true,\"unity_launched\":false}\n",cases);
    return 0;
}
