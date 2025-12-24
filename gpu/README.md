# TRON 虚荣地址生成器 - GPU 加速版

支持 NVIDIA GPU (Tesla T4, RTX 系列等) 加速。

## 版本说明

| 文件 | 说明 | 预计速度 |
|------|------|----------|
| `tron_gpu.py` | 纯 CPU 多进程版本 | ~50,000/秒 (20核) |
| `tron_cuda.py` | GPU 生成随机数版本 | ~80,000/秒 |
| `tron_hybrid.py` | GPU + 多进程混合版本 (推荐) | ~100,000/秒 |

## CentOS 7/8 安装步骤

### 1. 安装 NVIDIA 驱动和 CUDA

```bash
# 检查 GPU
nvidia-smi

# 如果没有安装驱动，执行以下步骤
# CentOS 7
sudo yum install -y epel-release
sudo yum install -y kernel-devel kernel-headers
sudo yum-config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/cuda-rhel7.repo
sudo yum install -y cuda-toolkit-12-0 nvidia-driver-latest-dkms

# CentOS 8
sudo dnf install -y epel-release
sudo dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel8/x86_64/cuda-rhel8.repo
sudo dnf install -y cuda-toolkit-12-0 nvidia-driver-latest-dkms

# 添加环境变量
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# 重启后验证
nvidia-smi
nvcc --version
```

### 2. 安装 Python 依赖

```bash
# 安装 Python3 和 pip
sudo yum install -y python3 python3-pip python3-devel gcc

# 安装依赖（推荐使用 pip3）
pip3 install numba numpy ecdsa base58 pysha3 --user

# 或使用 conda（更推荐，避免依赖冲突）
conda install numba numpy
pip install ecdsa base58 pysha3
```

### 3. 修改配置

编辑对应的 Python 文件，修改以下配置：

```python
PREFIX = "MGf"      # 前缀（不含 T，区分大小写）
SUFFIX = "fqq"      # 后缀（区分大小写）
TARGET_COUNT = 1    # 要找的地址数量
```

### 4. 运行

```bash
# 推荐：混合加速版本
python3 tron_hybrid.py

# 或：纯 GPU 版本
python3 tron_cuda.py

# 或：纯 CPU 版本（无需 GPU）
python3 tron_gpu.py
```

## 快速一键安装运行

```bash
# 进入 gpu 目录
cd gpu

# 安装依赖并运行
pip3 install numba numpy ecdsa base58 pysha3 --user && python3 tron_hybrid.py
```

## 常见问题

### 1. `numba.cuda` 报错
```
确保 CUDA 已正确安装：
nvcc --version
nvidia-smi
```

### 2. 速度没有预期快
椭圆曲线运算 (secp256k1) 目前仍在 CPU 执行，这是瓶颈。
GPU 主要用于加速随机数生成和部分哈希运算。

### 3. 想要更快的速度
可以考虑使用纯 CUDA C 实现的工具，如：
- [VanitySearch](https://github.com/JeanLucPons/VanitySearch) - 支持多种加密货币
- 需要自行编译，速度可达 ~2000万/秒

## 注意事项

- 匹配**区分大小写**
- 结果保存在 `found_addresses.txt`
- 按 `Ctrl+C` 可安全停止
- Tesla T4 显存 16GB，足够处理大批量

## 预计搜索时间

| 字符数 | 概率 | Tesla T4 预计时间 |
|--------|------|-------------------|
| 3 | 1/195,112 | ~2 秒 |
| 4 | 1/11,316,496 | ~2 分钟 |
| 5 | 1/656,356,768 | ~2 小时 |
| 6 | 1/38,068,692,544 | ~4 天 |
