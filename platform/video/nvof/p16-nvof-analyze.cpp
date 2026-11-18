// N1X optical-flow analysis through NVIDIA's published CUDA Optical Flow API.
#include <cuda.h>
#include <nvOpticalFlowCuda.h>

#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

static void cuda_ok(CUresult status, const char *operation) {
    if (status != CUDA_SUCCESS)
        throw std::runtime_error(std::string(operation) + " CUDA status " + std::to_string(status));
}

static void of_ok(NV_OF_STATUS status, const char *operation) {
    if (status != NV_OF_SUCCESS)
        throw std::runtime_error(std::string(operation) + " NVOF status " + std::to_string(status));
}

struct FlowEngine {
    CUcontext context = nullptr;
    NvOFHandle handle = nullptr;
    NvOFGPUBufferHandle input = nullptr;
    NvOFGPUBufferHandle reference = nullptr;
    NvOFGPUBufferHandle output = nullptr;
    NV_OF_CUDA_API_FUNCTION_LIST api{};
    unsigned width, height, grid = 4;
    uint32_t driver_api_version = 0;

    FlowEngine(unsigned w, unsigned h) : width(w), height(h) {
        cuda_ok(cuInit(0), "cuInit");
        CUdevice device;
        cuda_ok(cuDeviceGet(&device, 0), "cuDeviceGet");
        cuda_ok(cuCtxCreate(&context, nullptr, 0, device), "cuCtxCreate");
        of_ok(NvOFGetMaxSupportedApiVersion(&driver_api_version), "NvOFGetMaxSupportedApiVersion");
        of_ok(NvOFAPICreateInstanceCuda(NV_OF_API_VERSION, &api), "NvOFAPICreateInstanceCuda");
        if (!api.nvCreateOpticalFlowCuda || !api.nvOFInit || !api.nvOFExecute ||
            !api.nvOFCreateGPUBufferCuda || !api.nvOFGPUBufferGetStrideInfo ||
            !api.nvOFGPUBufferGetCUdeviceptr || !api.nvOFDestroyGPUBufferCuda || !api.nvOFDestroy)
            throw std::runtime_error("NVOF function table is incomplete");
        of_ok(api.nvCreateOpticalFlowCuda(context, &handle), "nvCreateOpticalFlowCuda");
        NV_OF_INIT_PARAMS init{};
        init.width = width;
        init.height = height;
        init.outGridSize = NV_OF_OUTPUT_VECTOR_GRID_SIZE_4;
        init.mode = NV_OF_MODE_OPTICALFLOW;
        init.perfLevel = NV_OF_PERF_LEVEL_MEDIUM;
        of_ok(api.nvOFInit(handle, &init), "nvOFInit");
        NV_OF_BUFFER_DESCRIPTOR in{};
        in.width = width;
        in.height = height;
        in.bufferUsage = NV_OF_BUFFER_USAGE_INPUT;
        in.bufferFormat = NV_OF_BUFFER_FORMAT_GRAYSCALE8;
        of_ok(api.nvOFCreateGPUBufferCuda(handle, &in, NV_OF_CUDA_BUFFER_TYPE_CUDEVICEPTR,
                                          &input), "create input buffer");
        of_ok(api.nvOFCreateGPUBufferCuda(handle, &in, NV_OF_CUDA_BUFFER_TYPE_CUDEVICEPTR,
                                          &reference), "create reference buffer");
        NV_OF_BUFFER_DESCRIPTOR out{};
        out.width = width / grid;
        out.height = height / grid;
        out.bufferUsage = NV_OF_BUFFER_USAGE_OUTPUT;
        out.bufferFormat = NV_OF_BUFFER_FORMAT_SHORT2;
        of_ok(api.nvOFCreateGPUBufferCuda(handle, &out, NV_OF_CUDA_BUFFER_TYPE_CUDEVICEPTR,
                                          &output), "create output buffer");
    }

    ~FlowEngine() {
        if (output) api.nvOFDestroyGPUBufferCuda(output);
        if (reference) api.nvOFDestroyGPUBufferCuda(reference);
        if (input) api.nvOFDestroyGPUBufferCuda(input);
        if (handle) api.nvOFDestroy(handle);
        if (context) cuCtxDestroy(context);
    }

    void upload(NvOFGPUBufferHandle buffer, const std::vector<uint8_t> &frame) {
        NV_OF_CUDA_BUFFER_STRIDE_INFO stride{};
        of_ok(api.nvOFGPUBufferGetStrideInfo(buffer, &stride), "get input stride");
        if (stride.numPlanes != 1 || stride.strideInfo[0].strideXInBytes < width)
            throw std::runtime_error("unexpected input buffer layout");
        CUDA_MEMCPY2D copy{};
        copy.srcMemoryType = CU_MEMORYTYPE_HOST;
        copy.srcHost = frame.data();
        copy.srcPitch = width;
        copy.dstMemoryType = CU_MEMORYTYPE_DEVICE;
        copy.dstDevice = api.nvOFGPUBufferGetCUdeviceptr(buffer);
        copy.dstPitch = stride.strideInfo[0].strideXInBytes;
        copy.WidthInBytes = width;
        copy.Height = height;
        cuda_ok(cuMemcpy2D(&copy), "upload frame");
    }

    std::vector<NV_OF_FLOW_VECTOR> execute() {
        NV_OF_EXECUTE_INPUT_PARAMS in{};
        in.inputFrame = input;
        in.referenceFrame = reference;
        NV_OF_EXECUTE_OUTPUT_PARAMS out{};
        out.outputBuffer = output;
        of_ok(api.nvOFExecute(handle, &in, &out), "nvOFExecute");
        cuda_ok(cuCtxSynchronize(), "synchronize optical flow");
        NV_OF_CUDA_BUFFER_STRIDE_INFO stride{};
        of_ok(api.nvOFGPUBufferGetStrideInfo(output, &stride), "get output stride");
        const unsigned row_bytes = width / grid * sizeof(NV_OF_FLOW_VECTOR);
        if (stride.numPlanes != 1 || stride.strideInfo[0].strideXInBytes < row_bytes)
            throw std::runtime_error("unexpected output buffer layout");
        std::vector<NV_OF_FLOW_VECTOR> flow(width / grid * height / grid);
        CUDA_MEMCPY2D copy{};
        copy.srcMemoryType = CU_MEMORYTYPE_DEVICE;
        copy.srcDevice = api.nvOFGPUBufferGetCUdeviceptr(output);
        copy.srcPitch = stride.strideInfo[0].strideXInBytes;
        copy.dstMemoryType = CU_MEMORYTYPE_HOST;
        copy.dstHost = flow.data();
        copy.dstPitch = row_bytes;
        copy.WidthInBytes = row_bytes;
        copy.Height = height / grid;
        cuda_ok(cuMemcpy2D(&copy), "download optical flow");
        return flow;
    }
};

static bool read_frame(std::vector<uint8_t> &frame) {
    std::cin.read(reinterpret_cast<char *>(frame.data()), frame.size());
    const auto count = std::cin.gcount();
    if (count == 0 && std::cin.eof()) return false;
    if (count != static_cast<std::streamsize>(frame.size()))
        throw std::runtime_error("incomplete raw grayscale frame");
    return true;
}

int main(int argc, char **argv) {
    try {
        if (argc != 4) {
            std::cerr << "Usage: p16-nvof-analyze WIDTH HEIGHT MAX_PAIRS < gray8.raw\n";
            return 2;
        }
        const unsigned width = std::stoul(argv[1]);
        const unsigned height = std::stoul(argv[2]);
        const unsigned max_pairs = std::stoul(argv[3]);
        if (width < 128 || height < 64 || width > 4096 || height > 4096 ||
            width % 4 || height % 4 || max_pairs < 1 || max_pairs > 300)
            throw std::runtime_error("invalid size or pair limit");
        std::vector<uint8_t> current(width * height), next(width * height);
        if (!read_frame(current)) throw std::runtime_error("no input frames");
        FlowEngine engine(width, height);
        engine.upload(engine.input, current);
        double total_magnitude = 0.0, total_nonzero = 0.0;
        unsigned pairs = 0;
        struct PairSummary {
            double mean_x, mean_y, mean_magnitude, nonzero_fraction;
        };
        std::vector<PairSummary> summaries;
        while (pairs < max_pairs && read_frame(next)) {
            engine.upload(engine.reference, next);
            const auto flow = engine.execute();
            double sum_x = 0, sum_y = 0, sum_magnitude = 0;
            unsigned nonzero = 0;
            for (const auto &v : flow) {
                const double dx = v.flowx / 32.0, dy = v.flowy / 32.0;
                const double magnitude = std::hypot(dx, dy);
                sum_x += dx;
                sum_y += dy;
                sum_magnitude += magnitude;
                if (magnitude >= 0.5) ++nonzero;
            }
            summaries.push_back({sum_x / flow.size(), sum_y / flow.size(),
                                 sum_magnitude / flow.size(), double(nonzero) / flow.size()});
            total_magnitude += sum_magnitude / flow.size();
            total_nonzero += double(nonzero) / flow.size();
            ++pairs;
            std::swap(engine.input, engine.reference);
            std::swap(current, next);
        }
        if (!pairs) throw std::runtime_error("need at least two frames");
        std::cout << std::fixed << std::setprecision(4);
        std::cout << "{\"backend\":\"NVIDIA NVOFA CUDA\",\"header_api_version\":"
                  << NV_OF_API_VERSION << ",\"driver_api_version\":"
                  << engine.driver_api_version << ",\"width\":" << width
                  << ",\"height\":" << height << ",\"grid\":4,\"pairs\":[";
        for (unsigned i = 0; i < summaries.size(); ++i) {
            if (i) std::cout << ',';
            const auto &s = summaries[i];
            std::cout << "{\"mean_dx\":" << s.mean_x
                      << ",\"mean_dy\":" << s.mean_y
                      << ",\"mean_magnitude\":" << s.mean_magnitude
                      << ",\"nonzero_fraction\":" << s.nonzero_fraction << '}';
        }
        std::cout << "],\"pair_count\":" << pairs
                  << ",\"mean_magnitude\":" << (pairs ? total_magnitude / pairs : 0)
                  << ",\"mean_nonzero_fraction\":" << (pairs ? total_nonzero / pairs : 0)
                  << "}\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "p16-nvof-analyze: " << error.what() << '\n';
        return 1;
    }
}
