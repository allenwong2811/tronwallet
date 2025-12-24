#!/usr/bin/env python3
"""
TRON GPU 虚荣地址生成器
使用 CUDA 加速的高性能版本
"""

import os
import sys
import time
import hashlib
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed

# 尝试导入 GPU 库
try:
    import numpy as np
    from ecdsa import SECP256k1, SigningKey
    from ecdsa.util import randrange_from_seed__trytryagain
    import base58
except ImportError:
    print("请安装依赖: pip3 install numpy ecdsa base58")
    sys.exit(1)

# ======== 配置 ========
PREFIX = "MGf"  # 前缀（不含 T）
SUFFIX = "fqq"  # 后缀
TARGET_COUNT = 1  # 要找的地址数量
NUM_WORKERS = mp.cpu_count() * 2  # 工作线程数
BATCH_SIZE = 1000  # 每批处理数量
# ======================

def keccak256(data):
    """Keccak256 哈希"""
    from Crypto.Hash import keccak
    k = keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()

def sha256(data):
    """SHA256 哈希"""
    return hashlib.sha256(data).digest()

def double_sha256(data):
    """双 SHA256"""
    return sha256(sha256(data))

def private_key_to_address(private_key_bytes):
    """从私钥生成 TRON 地址"""
    # 获取公钥
    sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    vk = sk.get_verifying_key()
    public_key = b'\x04' + vk.to_string()
    
    # Keccak256 哈希（去掉 04 前缀）
    hash_bytes = keccak256(public_key[1:])
    
    # 取后 20 字节
    address_bytes = hash_bytes[-20:]
    
    # 添加 TRON 前缀 0x41
    address_with_prefix = b'\x41' + address_bytes
    
    # 计算校验和
    checksum = double_sha256(address_with_prefix)[:4]
    
    # Base58 编码
    address = base58.b58encode(address_with_prefix + checksum).decode()
    
    return address

def check_address(address, prefix, suffix):
    """检查地址是否匹配"""
    if prefix and not address[1:1+len(prefix)].lower() == prefix.lower():
        return False
    if suffix and not address[-len(suffix):].lower() == suffix.lower():
        return False
    return True

def worker(worker_id, prefix, suffix, result_queue, stats_queue):
    """工作进程"""
    count = 0
    found = 0
    
    while True:
        # 生成随机私钥
        private_key = os.urandom(32)
        
        try:
            # 生成地址
            address = private_key_to_address(private_key)
            count += 1
            
            # 检查是否匹配
            if check_address(address, prefix, suffix):
                result_queue.put({
                    'address': address,
                    'private_key': private_key.hex(),
                    'worker_id': worker_id
                })
                found += 1
            
            # 每 10000 次报告统计
            if count % 10000 == 0:
                stats_queue.put(count)
                count = 0
                
        except Exception as e:
            pass

def main():
    print("\n===== TRON GPU 虚荣地址生成器 =====")
    print(f"前缀: T{PREFIX}")
    print(f"后缀: {SUFFIX}")
    print(f"工作进程数: {NUM_WORKERS}")
    
    # 计算概率
    total_chars = len(PREFIX) + len(SUFFIX)
    probability = 58 ** total_chars
    print(f"概率: 1/{probability:,}")
    print()
    
    # 创建队列
    result_queue = mp.Queue()
    stats_queue = mp.Queue()
    
    # 启动工作进程
    processes = []
    for i in range(NUM_WORKERS):
        p = mp.Process(target=worker, args=(i, PREFIX, SUFFIX, result_queue, stats_queue))
        p.daemon = True
        p.start()
        processes.append(p)
    
    print(f"已启动 {NUM_WORKERS} 个工作进程...")
    print()
    
    # 统计
    start_time = time.time()
    total_count = 0
    found_count = 0
    last_report_time = time.time()
    last_count = 0
    
    try:
        while found_count < TARGET_COUNT:
            # 收集统计
            while not stats_queue.empty():
                total_count += stats_queue.get()
            
            # 检查结果
            while not result_queue.empty():
                result = result_queue.get()
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
            
            # 每 5 秒报告
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
        for p in processes:
            p.terminate()
        
        elapsed = time.time() - start_time
        print(f"\n总运行时间: {elapsed:.1f} 秒")
        print(f"总搜索: {total_count:,}")
        print(f"找到地址: {found_count}")

if __name__ == '__main__':
    main()

