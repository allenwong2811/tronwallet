#!/usr/bin/env python3
"""
TRON 虚荣地址生成器 - 混合加速版本
GPU 生成随机数 + 多进程 CPU 验证
适用于 Tesla T4 等 NVIDIA GPU
"""

import os
import sys
import time
import hashlib
import multiprocessing as mp
from multiprocessing import Process, Queue, Value
import ctypes

# 检查依赖
try:
    import numpy as np
    from numba import cuda
    from numba.cuda.random import create_xoroshiro128p_states, xoroshiro128p_uniform_float32
    from ecdsa import SECP256k1, SigningKey
    import base58
    import sha3
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("\n请安装依赖:")
    print("pip3 install numba numpy ecdsa base58 pysha3")
    sys.exit(1)

# ======== 配置 ========
PREFIX = "MGf"          # 前缀（不含 T，区分大小写）
SUFFIX = "fqq"          # 后缀（区分大小写）
TARGET_COUNT = 1        # 要找的地址数量
GPU_BATCH_SIZE = 500000 # GPU 每批生成的私钥数量
NUM_CPU_WORKERS = None  # CPU 工作进程数，None 表示自动
# ======================

def keccak256(data):
    return sha3.keccak_256(data).digest()

def sha256(data):
    return hashlib.sha256(data).digest()

def double_sha256(data):
    return sha256(sha256(data))

def private_key_to_address(private_key_bytes):
    """从私钥生成 TRON 地址"""
    sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\x04' + vk.to_string()
    
    hash_bytes = keccak256(public_key[1:])
    address_bytes = hash_bytes[-20:]
    address_with_prefix = b'\x41' + address_bytes
    checksum = double_sha256(address_with_prefix)[:4]
    
    return base58.b58encode(address_with_prefix + checksum).decode()

# GPU Kernel
@cuda.jit
def generate_random_keys_kernel(rng_states, output_keys):
    """GPU 生成随机私钥"""
    idx = cuda.grid(1)
    if idx < output_keys.shape[0]:
        for i in range(32):
            rand_val = xoroshiro128p_uniform_float32(rng_states, idx)
            output_keys[idx, i] = int(rand_val * 256) % 256

def gpu_key_generator(key_queue, stop_flag, batch_size):
    """GPU 进程：持续生成随机私钥"""
    try:
        if not cuda.is_available():
            print("GPU 不可用，退出")
            return
        
        device = cuda.get_current_device()
        print(f"[GPU] 使用: {device.name.decode()}")
        
        threads_per_block = 256
        blocks = (batch_size + threads_per_block - 1) // threads_per_block
        
        rng_states = create_xoroshiro128p_states(
            threads_per_block * blocks,
            seed=int(time.time() * 1000000) + os.getpid()
        )
        
        d_keys = cuda.device_array((batch_size, 32), dtype=np.uint8)
        
        while not stop_flag.value:
            # GPU 生成随机私钥
            generate_random_keys_kernel[blocks, threads_per_block](rng_states, d_keys)
            cuda.synchronize()
            
            # 复制到 CPU
            keys = d_keys.copy_to_host()
            
            # 放入队列
            try:
                key_queue.put(keys, timeout=1)
            except:
                pass
    
    except Exception as e:
        print(f"[GPU] 错误: {e}")

def cpu_worker(worker_id, key_queue, result_queue, stats_queue, prefix, suffix, stop_flag):
    """CPU 工作进程：验证地址"""
    count = 0
    prefix_len = len(prefix) if prefix else 0
    suffix_len = len(suffix) if suffix else 0
    
    while not stop_flag.value:
        try:
            # 从队列获取私钥批次
            keys = key_queue.get(timeout=1)
            
            for key_bytes in keys:
                if stop_flag.value:
                    break
                
                try:
                    private_key = bytes(key_bytes)
                    address = private_key_to_address(private_key)
                    count += 1
                    
                    # 检查匹配（区分大小写）
                    match = True
                    if prefix_len > 0 and address[1:1+prefix_len] != prefix:
                        match = False
                    if match and suffix_len > 0 and address[-suffix_len:] != suffix:
                        match = False
                    
                    if match:
                        result_queue.put({
                            'address': address,
                            'private_key': private_key.hex(),
                            'worker_id': worker_id
                        })
                    
                    # 报告统计
                    if count % 10000 == 0:
                        stats_queue.put(count)
                        count = 0
                
                except Exception:
                    continue
        
        except:
            continue
    
    # 最后的统计
    if count > 0:
        stats_queue.put(count)

def main():
    print("\n" + "="*55)
    print("   TRON 虚荣地址生成器 - GPU + 多进程混合加速版")
    print("="*55)
    
    # 检查 GPU
    if not cuda.is_available():
        print("\n错误: 未检测到 CUDA GPU！")
        print("请确保已安装 NVIDIA 驱动和 CUDA")
        sys.exit(1)
    
    # 计算概率
    total_chars = len(PREFIX) + len(SUFFIX)
    probability = 58 ** total_chars
    
    print(f"\n前缀: T{PREFIX}")
    print(f"后缀: {SUFFIX}")
    print(f"概率: 1/{probability:,}")
    print(f"目标数量: {TARGET_COUNT}")
    
    # 确定 CPU 工作进程数
    num_workers = NUM_CPU_WORKERS or max(1, mp.cpu_count() - 1)
    print(f"CPU 工作进程: {num_workers}")
    print(f"GPU 批次大小: {GPU_BATCH_SIZE:,}")
    print()
    
    # 创建共享变量和队列
    stop_flag = Value(ctypes.c_bool, False)
    key_queue = Queue(maxsize=10)  # 限制队列大小
    result_queue = Queue()
    stats_queue = Queue()
    
    # 启动 GPU 进程
    gpu_process = Process(
        target=gpu_key_generator,
        args=(key_queue, stop_flag, GPU_BATCH_SIZE)
    )
    gpu_process.start()
    
    # 启动 CPU 工作进程
    cpu_processes = []
    for i in range(num_workers):
        p = Process(
            target=cpu_worker,
            args=(i, key_queue, result_queue, stats_queue, PREFIX, SUFFIX, stop_flag)
        )
        p.start()
        cpu_processes.append(p)
    
    print(f"已启动 1 个 GPU 进程 + {num_workers} 个 CPU 进程")
    print("开始搜索...\n")
    
    # 主循环
    start_time = time.time()
    total_count = 0
    found_count = 0
    last_report_time = start_time
    last_count = 0
    
    try:
        while found_count < TARGET_COUNT:
            # 收集统计
            while not stats_queue.empty():
                try:
                    total_count += stats_queue.get_nowait()
                except:
                    break
            
            # 检查结果
            while not result_queue.empty():
                try:
                    result = result_queue.get_nowait()
                    found_count += 1
                    
                    print(f"\n{'='*50}")
                    print(f"找到地址 #{found_count}!")
                    print(f"Address: {result['address']}")
                    print(f"Private Key: {result['private_key']}")
                    print(f"{'='*50}\n")
                    
                    # 保存到文件
                    with open('found_addresses.txt', 'a') as f:
                        f.write(f"Address: {result['address']}\n")
                        f.write(f"Private Key: {result['private_key']}\n")
                        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write("="*50 + "\n\n")
                    
                    if found_count >= TARGET_COUNT:
                        break
                except:
                    break
            
            # 报告进度
            current_time = time.time()
            if current_time - last_report_time >= 5:
                elapsed = current_time - start_time
                instant_rate = (total_count - last_count) / (current_time - last_report_time)
                avg_rate = total_count / elapsed if elapsed > 0 else 0
                
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                seconds = int(elapsed % 60)
                
                print(f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d} | "
                      f"已搜索: {total_count:,} | "
                      f"即时: {int(instant_rate):,}/秒 | "
                      f"平均: {int(avg_rate):,}/秒 | "
                      f"已找到: {found_count}")
                
                last_report_time = current_time
                last_count = total_count
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n正在停止...")
    
    finally:
        # 停止所有进程
        stop_flag.value = True
        
        gpu_process.terminate()
        gpu_process.join(timeout=2)
        
        for p in cpu_processes:
            p.terminate()
            p.join(timeout=2)
        
        elapsed = time.time() - start_time
        avg_rate = total_count / elapsed if elapsed > 0 else 0
        
        print(f"\n{'='*50}")
        print(f"总运行时间: {elapsed:.1f} 秒")
        print(f"总搜索: {total_count:,}")
        print(f"平均速度: {int(avg_rate):,}/秒")
        print(f"找到地址: {found_count}")
        print(f"{'='*50}")


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)
    main()

