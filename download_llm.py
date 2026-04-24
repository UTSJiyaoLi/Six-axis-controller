# download_model.py
from pathlib import Path
from huggingface_hub import snapshot_download

HF_REPO_ID = "Qwen/Qwen2.5-7B-Instruct"
LOCAL_MODEL_DIR = Path("./Qwen2.5-7B-Instruct")  # 可以改成你想要的路径

def main():
    if LOCAL_MODEL_DIR.exists():
        print(f"本地已存在模型目录：{LOCAL_MODEL_DIR}，不再重复下载。")
        return

    print(f"开始从 Hugging Face 下载模型：{HF_REPO_ID}")
    LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    snapshot_download(
        repo_id=HF_REPO_ID,
        local_dir=str(LOCAL_MODEL_DIR),
        local_dir_use_symlinks=False,  # 实体文件，方便打包
    )

    print(f"✅ 模型已下载到：{LOCAL_MODEL_DIR}")

if __name__ == "__main__":
    main()
