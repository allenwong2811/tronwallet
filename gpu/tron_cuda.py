#!/usr/bin/env python3
"""
TRON 虚荣地址生成器 - GPU CUDA 加速版本
使用 Numba CUDA 实现 GPU 并行计算
"""

import os
import sys
import time
import hashlib
import numpy as np
from typing import Tuple, Optional

# 检查依赖
try:
    from numba import cuda, uint8, uint32, uint64
    from numba.cuda.random import create_xoroshiro128p_states, xoroshiro128p_uniform_float32
    import base58
    from ecdsa import SECP256k1, SigningKey
    import sha3
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请安装: pip3 install numba base58 ecdsa pysha3 numpy")
    sys.exit(1)

# ======== 配置 ========
PREFIX = "MGf"      # 前缀（不含 T，区分大小写）
SUFFIX = "fqq"      # 后缀（区分大小写）
TARGET_COUNT = 1    # 要找的地址数量
BATCH_SIZE = 100000 # 每批生成的私钥数量
# ======================

# Base58 字符集
BASE58_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def keccak256(data: bytes) -> bytes:
    """Keccak256 哈希"""
    return sha3.keccak_256(data).digest()

def sha256(data: bytes) -> bytes:
    """SHA256 哈希"""
    return hashlib.sha256(data).digest()

def double_sha256(data: bytes) -> bytes:
    """双 SHA256"""
    return sha256(sha256(data))

def private_key_to_address(private_key_bytes: bytes) -> str:
    """从私钥生成 TRON 地址"""
    sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\x04' + vk.to_string()
    
    hash_bytes = keccak256(public_key[1:])
    address_bytes = hash_bytes[-20:]
    address_with_prefix = b'\x41' + address_bytes
    checksum = double_sha256(address_with_prefix)[:4]
    address = base58.b58encode(address_with_prefix + checksum).decode()
    
    return address

def check_address(address: str, prefix: str, suffix: str) -> bool:
    """检查地址是否匹配（区分大小写）"""
    if prefix and address[1:1+len(prefix)] != prefix:
        return False
    if suffix and address[-len(suffix):] != suffix:
        return False
    return True

# CUDA Kernel：在 GPU 上生成随机私钥
@cuda.jit
def generate_random_keys_kernel(rng_states, output_keys):
    """GPU kernel：生成随机私钥"""
    idx = cuda.grid(1)
    if idx < output_keys.shape[0]:
        # 生成 32 字节随机私钥
        for i in range(32):
            # 使用 xoroshiro128+ 生成随机数
            rand_val = xoroshiro128p_uniform_float32(rng_states, idx)
            output_keys[idx, i] = uint8(rand_val * 256)

class TronGPUGenerator:
    """TRON GPU 地址生成器"""
    
    def __init__(self, prefix: str, suffix: str, batch_size: int = 100000):
        self.prefix = prefix
        self.suffix = suffix
        self.batch_size = batch_size
        
        # 检查 GPU
        if not cuda.is_available():
            raise RuntimeError("未检测到 CUDA GPU！")
        
        # 获取 GPU 信息
        device = cuda.get_current_device()
        print(f"GPU: {device.name.decode()}")
        print(f"计算能力: {device.compute_capability}")
        
        # 设置 CUDA 参数
        self.threads_per_block = 256
        self.blocks = (batch_size + self.threads_per_block - 1) // self.threads_per_block
        
        # 初始化随机数生成器状态
        self.rng_states = create_xoroshiro128p_states(
            self.threads_per_block * self.blocks, 
            seed=int(time.time() * 1000000)
        )
        
        # 分配 GPU 内存
        self.d_keys = cuda.device_array((batch_size, 32), dtype=np.uint8)
    
    def generate_batch(self) -> np.ndarray:
        """在 GPU 上批量生成随机私钥"""
        generate_random_keys_kernel[self.blocks, self.threads_per_block](
            self.rng_states, self.d_keys
        )
        cuda.synchronize()
        return self.d_keys.copy_to_host()
    
    def search(self, target_count: int = 1) -> list:
        """搜索匹配的地址"""
        found = []
        total_count = 0
        start_time = time.time()
        last_report_time = start_time
        last_count = 0
        
        print(f"\n开始搜索 T{self.prefix}...{self.suffix}")
        print(f"批次大小: {self.batch_size:,}")
        print()
        
        try:
            while len(found) < target_count:
                # GPU 生成随机私钥
                keys = self.generate_batch()
                
                # CPU 验证地址（椭圆曲线运算仍在 CPU）
                for i in range(len(keys)):
                    try:
                        private_key = bytes(keys[i])
                        address = private_key_to_address(private_key)
                        total_count += 1
                        
                        if check_address(address, self.prefix, self.suffix):
                            result = {
                                'address': address,
                                'private_key': private_key.hex()
                            }
                            found.append(result)
                            
                            print(f"\n{'='*50}")
                            print(f"找到地址 #{len(found)}!")
                            print(f"Address: {address}")
                            print(f"Private Key: {private_key.hex()}")
                            print(f"{'='*50}\n")
                            
                            # 保存到文件
                            self._save_result(result)
                            
                            if len(found) >= target_count:
                                break
                    except Exception:
                        continue
                
                # 报告进度
                current_time = time.time()
                if current_time - last_report_time >= 5:
                    elapsed = current_time - start_time
                    instant_rate = (total_count - last_count) / (current_time - last_report_time)
                    avg_rate = total_count / elapsed
                    
                    hours = int(elapsed // 3600)
                    minutes = int((elapsed % 3600) // 60)
                    seconds = int(elapsed % 60)
                    
                    print(f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d} | "
                          f"已搜索: {total_count:,} | "
                          f"即时: {int(instant_rate):,}/秒 | "
                          f"平均: {int(avg_rate):,}/秒 | "
                          f"已找到: {len(found)}")
                    
                    last_report_time = current_time
                    last_count = total_count
        
        except KeyboardInterrupt:
            print("\n正在停止...")
        
        elapsed = time.time() - start_time
        print(f"\n总运行时间: {elapsed:.1f} 秒")
        print(f"总搜索: {total_count:,}")
        print(f"找到地址: {len(found)}")
        
        return found
    
    def _save_result(self, result: dict):
        """保存结果到文件"""
        with open('found_addresses.txt', 'a') as f:
            f.write(f"Address: {result['address']}\n")
            f.write(f"Private Key: {result['private_key']}\n")
            f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*50 + "\n\n")


def main():
    print("\n" + "="*50)
    print("   TRON GPU 虚荣地址生成器 - CUDA 加速版")
    print("="*50)
    
    # 计算概率
    total_chars = len(PREFIX) + len(SUFFIX)
    probability = 58 ** total_chars
    print(f"\n前缀: T{PREFIX}")
    print(f"后缀: {SUFFIX}")
    print(f"概率: 1/{probability:,}")
    print(f"目标数量: {TARGET_COUNT}")
    
    try:
        generator = TronGPUGenerator(PREFIX, SUFFIX, BATCH_SIZE)
        results = generator.search(TARGET_COUNT)
        
        if results:
            print(f"\n成功找到 {len(results)} 个地址！")
            print(f"结果已保存到 found_addresses.txt")
    
    except RuntimeError as e:
        print(f"\n错误: {e}")
        print("请确保已安装 NVIDIA GPU 驱动和 CUDA")
        sys.exit(1)


if __name__ == '__main__':
    main()

