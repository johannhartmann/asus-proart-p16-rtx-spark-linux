#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <vector>

#define CHECK(call) do { cudaError_t error=(call); if(error!=cudaSuccess) { \
 std::fprintf(stderr,"%s:%d: %s: %s\n",__FILE__,__LINE__,#call,cudaGetErrorString(error)); return 1; } } while(0)

__global__ void add(const float* a,const float* b,float* out,int size) {
 int i=blockIdx.x*blockDim.x+threadIdx.x;
 if(i<size) out[i]=a[i]+b[i];
}

int main() {
 constexpr int size=4096;
 constexpr size_t bytes=size*sizeof(float);
 int count=0,runtime=0,driver=0;
 CHECK(cudaGetDeviceCount(&count));
 if(count<1) {std::fprintf(stderr,"No CUDA GPU found\n");return 1;}
 CHECK(cudaSetDevice(0));
 cudaDeviceProp prop{};
 CHECK(cudaGetDeviceProperties(&prop,0));
 CHECK(cudaRuntimeGetVersion(&runtime));
 CHECK(cudaDriverGetVersion(&driver));
 std::vector<float>a(size),b(size),out(size);
 for(int i=0;i<size;i++){a[i]=float(i);b[i]=float(2*i);}
 float *da=nullptr,*db=nullptr,*dc=nullptr;
 CHECK(cudaMalloc(&da,bytes));CHECK(cudaMalloc(&db,bytes));CHECK(cudaMalloc(&dc,bytes));
 CHECK(cudaMemcpy(da,a.data(),bytes,cudaMemcpyHostToDevice));
 CHECK(cudaMemcpy(db,b.data(),bytes,cudaMemcpyHostToDevice));
 add<<<(size+255)/256,256>>>(da,db,dc,size);
 CHECK(cudaGetLastError());CHECK(cudaDeviceSynchronize());
 CHECK(cudaMemcpy(out.data(),dc,bytes,cudaMemcpyDeviceToHost));
 for(int i=0;i<size;i++) {
  if(out[i]!=float(3*i)) {std::fprintf(stderr,"Mismatch at %d: %f\n",i,out[i]);return 1;}
 }
 CHECK(cudaFree(da));CHECK(cudaFree(db));CHECK(cudaFree(dc));
 std::printf("{\"result\":\"passed\",\"gpu\":\"%s\",\"compute_capability\":\"%d.%d\",\"cuda_runtime\":%d,\"cuda_driver\":%d,\"elements_verified\":%d}\n",prop.name,prop.major,prop.minor,runtime,driver,size);
 return 0;
}
