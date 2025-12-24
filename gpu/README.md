# TRON GPU 虚荣地址生成器

## 环境要求
- NVIDIA GPU (Tesla T4, RTX 3080 等)
- CUDA Toolkit 11.0+
- Python 3.8+

## 安装步骤

### 1. 安装 CUDA (CentOS 7)
```bash
sudo yum-config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/cuda-rhel7.repo
sudo yum install -y cuda-toolkit-12-0
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

### 2. 安装 Python 依赖
```bash
pip3 install pycuda numpy base58 ecdsa
```

### 3. 运行
```bash
python3 tron_gpu.py
```

## 预计速度
- Tesla T4: ~2000万/秒
- RTX 3080: ~5000万/秒
- A100: ~2亿/秒

