"""Windows CUDA 动态库目录准备测试。

测试使用临时 DLL 占位文件和伪目录句柄，不加载真正的 NVIDIA 运行库，
用于保护开发环境与发布包都依赖的路径注册行为。
"""

from pathlib import Path

from infrastructure.asr import cuda_runtime


class FakeDirectoryHandle:
    """模拟需要长期持有的 Windows DLL 目录句柄。"""


def test_prepare_cuda_runtime_registers_cublas_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """发现 `cublas64_12.dll` 后应同时注册 DLL 目录并更新进程路径。"""

    # arrange：只创建用于路径判断的空文件，避免单元测试依赖真实显卡驱动。
    cublas_directory = tmp_path / "nvidia" / "cublas" / "bin"
    cublas_directory.mkdir(parents=True)
    (cublas_directory / "cublas64_12.dll").write_bytes(b"")
    registered: list[str] = []

    monkeypatch.setattr(cuda_runtime.os, "name", "nt")
    monkeypatch.setattr(
        cuda_runtime,
        "_candidate_directories",
        lambda: (cublas_directory,),
    )
    monkeypatch.setattr(
        cuda_runtime.os,
        "add_dll_directory",
        lambda path: registered.append(path) or FakeDirectoryHandle(),
        raising=False,
    )
    monkeypatch.setattr(cuda_runtime, "_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(cuda_runtime, "_REGISTERED_DIRECTORIES", set())
    monkeypatch.setenv("PATH", str(tmp_path / "existing"))

    # act
    result = cuda_runtime.prepare_cuda_runtime()

    # assert：句柄会被模块保存，且重复调用不会重复注册同一路径。
    assert result == (cublas_directory.resolve(),)
    assert registered == [str(cublas_directory.resolve())]
    assert cuda_runtime._DLL_DIRECTORY_HANDLES
    assert cuda_runtime.os.environ["PATH"].split(cuda_runtime.os.pathsep)[0] == str(
        cublas_directory.resolve()
    )
    cuda_runtime.prepare_cuda_runtime()
    assert registered == [str(cublas_directory.resolve())]
