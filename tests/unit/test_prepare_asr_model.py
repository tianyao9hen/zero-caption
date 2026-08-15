"""发布模型准备脚本的单元测试。

这些测试不访问真实网络，只保护“完整文件才算就绪”和“临时文件写完后再替换”两个行为。
这样构建过程中断时，不会把残缺模型误判成可发布资产。
"""

from __future__ import annotations

from io import BytesIO

from scripts import prepare_asr_model


def test_model_is_ready_rejects_empty_required_file(tmp_path) -> None:
    """任一必需文件为空时，都不应把模型目录判断为可用。"""

    model_dir = tmp_path / "small"
    model_dir.mkdir()
    (model_dir / "config.json").write_bytes(b"config")
    (model_dir / "model.bin").write_bytes(b"")
    (model_dir / "tokenizer.json").write_bytes(b"tokenizer")

    assert prepare_asr_model.model_is_ready(model_dir) is False


def test_modelscope_download_replaces_temporary_files(monkeypatch, tmp_path) -> None:
    """镜像下载完成后应留下正式文件，并清理所有 `.part` 临时文件。"""

    payload = b"model-data"

    def fake_urlopen(request, timeout):
        # 假响应使用内存字节流模拟网络文件，测试不会依赖外部服务。
        assert request.full_url.startswith("https://www.modelscope.cn/")
        assert timeout == 120
        return BytesIO(payload)

    monkeypatch.setattr(prepare_asr_model, "urlopen", fake_urlopen)
    target = tmp_path / "small"

    prepare_asr_model._download_from_modelscope("small", target)

    for filename in prepare_asr_model.MODELSCOPE_MODEL_FILES:
        output_path = target / filename
        assert output_path.read_bytes() == payload
        assert not output_path.with_suffix(f"{output_path.suffix}.part").exists()


def test_main_prepares_every_model_from_default_bundle(monkeypatch, tmp_path) -> None:
    """未指定 `--model` 时，构建准备入口应处理 `small` 和 `medium`。"""

    # arrange：替换真正下载函数，只记录主入口准备顺序。
    prepared: list[tuple[str, object]] = []

    def remember_model(model_name, output_root):
        prepared.append((model_name, output_root))
        return output_root / model_name

    monkeypatch.setattr(prepare_asr_model, "prepare_model", remember_model)
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_asr_model.py",
            "--output-root",
            str(tmp_path / "models"),
        ],
    )

    # act
    exit_code = prepare_asr_model.main()

    # assert：发布顺序来自默认清单，未来增加模型时这个测试会提醒同步验收。
    assert exit_code == 0
    assert [name for name, _ in prepared] == ["small", "medium"]
