from __future__ import annotations


def local_device_status() -> dict:
    try:
        import paddle
    except Exception as exc:
        return {
            "available": False,
            "cuda": False,
            "gpu_count": 0,
            "device": "unknown",
            "gpu_name": None,
            "status": f"PaddlePaddle 不可用：{type(exc).__name__}: {exc}",
        }

    try:
        cuda = bool(paddle.is_compiled_with_cuda())
        gpu_count = int(paddle.device.cuda.device_count()) if cuda else 0
        device = str(paddle.get_device())
        gpu_name = None
        if gpu_count:
            try:
                props = paddle.device.cuda.get_device_properties(0)
                gpu_name = getattr(props, "name", None) or str(props)
            except Exception:
                gpu_name = None
        if gpu_count:
            status = f"GPU 可用：{gpu_name or 'CUDA 设备'}"
        elif cuda:
            status = "GPU 不可用：Paddle 为 CUDA 版但未检测到设备"
        else:
            status = "GPU 不可用：当前为 Paddle CPU 版"
        return {
            "available": True,
            "cuda": cuda,
            "gpu_count": gpu_count,
            "device": device,
            "gpu_name": gpu_name,
            "status": status,
        }
    except Exception as exc:
        return {
            "available": True,
            "cuda": False,
            "gpu_count": 0,
            "device": "unknown",
            "gpu_name": None,
            "status": f"GPU 状态检测失败：{type(exc).__name__}: {exc}",
        }
