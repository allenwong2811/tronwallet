const fs = require('fs');
const path = require('path');
const cluster = require('cluster');
const readline = require('readline');
const os = require('os');
const crypto = require('crypto');
const secp256k1 = require('secp256k1');
const createKeccakHash = require('keccak');

// Keccak256 哈希函数
function keccak256(data) {
  return createKeccakHash('keccak256').update(data).digest();
}

// 全局配置变量
const RESULT_FILENAME = 'number.txt';
const REPORT_INTERVAL = 5000; // 报告间隔（毫秒）

// ======== 靓号配置 ========
// 前缀配置（不含固定的 T，例如想要 TMG 开头就填 "MG"）
const PREFIX = 'MGf';
// 后缀配置
const SUFFIX = 'fqq';
// =========================

// Base58 字符集
const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const ALPHABET_MAP = {};
for (let i = 0; i < ALPHABET.length; i++) {
  ALPHABET_MAP[ALPHABET[i]] = i;
}

// Base58Check 编码
function base58Encode(buffer) {
  if (buffer.length === 0) return '';
  
  const digits = [0];
  for (let i = 0; i < buffer.length; i++) {
    let carry = buffer[i];
    for (let j = 0; j < digits.length; j++) {
      carry += digits[j] << 8;
      digits[j] = carry % 58;
      carry = (carry / 58) | 0;
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = (carry / 58) | 0;
    }
  }
  
  let result = '';
  // 处理前导零
  for (let i = 0; i < buffer.length && buffer[i] === 0; i++) {
    result += ALPHABET[0];
  }
  // 反转并编码
  for (let i = digits.length - 1; i >= 0; i--) {
    result += ALPHABET[digits[i]];
  }
  
  return result;
}

// 计算双 SHA256 校验和
function doubleSha256(buffer) {
  return crypto.createHash('sha256').update(
    crypto.createHash('sha256').update(buffer).digest()
  ).digest();
}

// 从私钥生成 TRON 地址（高性能版本）
function privateKeyToAddress(privateKeyBuffer) {
  // 1. 获取未压缩公钥 (65 bytes: 04 + x + y)
  const publicKey = secp256k1.publicKeyCreate(privateKeyBuffer, false);
  
  // 2. Keccak256 哈希公钥（去掉 04 前缀，使用后 64 字节）
  const hash = keccak256(Buffer.from(publicKey.slice(1)));
  
  // 3. 取后 20 字节作为地址
  const addressBytes = hash.slice(-20);
  
  // 4. 添加 TRON 主网前缀 0x41
  const addressWithPrefix = Buffer.concat([Buffer.from([0x41]), addressBytes]);
  
  // 5. 计算校验和（双 SHA256 的前 4 字节）
  const checksum = doubleSha256(addressWithPrefix).slice(0, 4);
  
  // 6. Base58 编码
  const addressBuffer = Buffer.concat([addressWithPrefix, checksum]);
  return base58Encode(addressBuffer);
}

// 确保结果文件存在
const resultsDir = path.join(__dirname, '..');
const resultsFile = path.join(resultsDir, RESULT_FILENAME);

// 如果结果文件不存在，则创建它
if (!fs.existsSync(resultsFile)) {
  fs.writeFileSync(resultsFile, '');
}

// 格式化时间函数
function formatTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}

// 函数：检查地址是否匹配前缀和后缀（区分大小写）
function checkAddress(address, prefix, suffix) {
  if (!address || typeof address !== 'string') return false;
  
  try {
    // 地址格式：T + 33个字符
    // 前缀检查（不含 T，区分大小写）
    const prefixMatch = !prefix || address.substring(1, 1 + prefix.length) === prefix;
    // 后缀检查（区分大小写）
    const suffixMatch = !suffix || address.slice(-suffix.length) === suffix;
    
    return prefixMatch && suffixMatch;
  } catch (e) {
    console.error('检查地址出错:', e);
    return false;
  }
}

// 函数：高性能生成波场账户
function generateAccount() {
  // 生成随机私钥（Buffer 格式，避免字符串转换开销）
  let privateKeyBuffer;
  do {
    privateKeyBuffer = crypto.randomBytes(32);
  } while (!secp256k1.privateKeyVerify(privateKeyBuffer));
  
  // 使用原生库生成地址
  const address = privateKeyToAddress(privateKeyBuffer);
  const privateKey = privateKeyBuffer.toString('hex');
  
  return { privateKey, address };
}

// 函数：将结果追加到单个文件
function saveToFile(address, privateKey, suffix, stats = null) {
  let content = '';
  
  // 如果提供了统计信息，添加时间戳和运行统计
  if (stats) {
    const { elapsedTime, foundCount, attempts, rate } = stats;
    const timestamp = new Date().toLocaleString();
    const formattedTime = formatTime(elapsedTime);
    
    content += `=== 搜索统计 ===\n`;
    content += `时间戳: ${timestamp}\n`;
    content += `搜索后缀: ${suffix}\n`;
    content += `总运行时间: ${formattedTime}\n`;
    content += `总尝试次数: ${attempts.toLocaleString()}\n`;
    content += `平均速度: ${rate.toLocaleString()} 地址/秒\n`;
    content += `找到地址数量: ${foundCount}\n\n`;
  }
  
  content += `Address: ${address}\n==========\nPrivate Key: ${privateKey}\n\n`;
  
  fs.appendFileSync(resultsFile, content);
  console.log(`\n成功！找到地址: ${address}`);
  console.log(`结果已保存至: ${resultsFile}`);
}

// 工作进程的主函数
function workerProcess(prefix, suffix) {
  console.log(`工作进程 ${process.pid} 开始搜索...`);
  
  let attempts = 0;
  const reportInterval = 10000;
  
  while (true) {
    attempts++;
    
    // 生成新的随机账户
    const { address, privateKey } = generateAccount();
    
    // 检查地址是否符合条件（同时匹配前缀和后缀）
    if (address && checkAddress(address, prefix, suffix)) {
      // 将结果发送回主进程
      process.send({ found: true, address, privateKey, attempts });
      
      // 继续搜索，重置计数
      attempts = 0;
    }
    
    // 报告进度
    if (attempts % reportInterval === 0) {
      process.send({ 
        found: false, 
        attempts,
        pid: process.pid
      });
      
      // 重置计数，避免数值过大或累积不准确
      attempts = 0;
    }
  }
}

// 计算匹配概率
function calculateProbability(prefix, suffix) {
  const base = 58; // Base58 字符集
  const prefixLen = prefix ? prefix.length : 0;
  const suffixLen = suffix ? suffix.length : 0;
  const totalLen = prefixLen + suffixLen;
  return Math.pow(base, totalLen);
}

// 主进程逻辑
if (cluster.isPrimary) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });
  
  const prefix = PREFIX;
  const suffix = SUFFIX;
  const probability = calculateProbability(prefix, suffix);
  
  console.log(`\n===== 波场靓号地址生成器 =====`);
  console.log(`前缀: T${prefix || '(无)'}`);
  console.log(`后缀: ${suffix || '(无)'}`);
  console.log(`预计概率: 1/${probability.toLocaleString()} (约 ${(probability / 1000000).toFixed(1)}M 次)\n`);
  
  rl.question('请输入要查找的地址数量 (输入0表示无限制，默认1): ', (targetCount) => {
    const targetAddressCount = parseInt(targetCount, 10) || 1;
    
    // 记录开始时间
    const startTime = Date.now();
    const startDateTime = new Date().toLocaleString();
    
    const patternDesc = `T${prefix}...${suffix}`;
    console.log(`\n开始时间: ${startDateTime}`);
    console.log(`正在搜索 ${patternDesc} 格式的波场地址...`);
    if (targetAddressCount > 0) {
      console.log(`找到${targetAddressCount}个地址后将自动停止`);
    } else {
      console.log('将持续运行直到手动停止 (按Ctrl+C)');
    }
    
    // 获取CPU核心数
    const numCores = os.cpus().length;
    console.log(`使用${numCores}个CPU核心进行并行处理\n`);
    
    let totalAttempts = 0;
    let foundAddressCount = 0;
    let lastReportTime = Date.now();
    let lastReportAttempts = 0;
    
    // 设置定时器定期显示统计信息
    const statsInterval = setInterval(() => {
      const elapsedTime = (Date.now() - startTime) / 1000;
      const currentTime = Date.now();
      const timeWindow = (currentTime - lastReportTime) / 1000;
      
      const instantRate = Math.floor((totalAttempts - lastReportAttempts) / timeWindow);
      const averageRate = Math.floor(totalAttempts / elapsedTime);
      
      lastReportTime = currentTime;
      lastReportAttempts = totalAttempts;
      
      const formattedTime = formatTime(elapsedTime);
      console.log(`运行时间: ${formattedTime} | 已搜索: ${totalAttempts.toLocaleString()} | 即时: ${instantRate.toLocaleString()}/秒 | 平均: ${averageRate.toLocaleString()}/秒 | 已找到: ${foundAddressCount}`);
    }, REPORT_INTERVAL);
    
    // 监听来自工作进程的消息
    cluster.on('message', (worker, message) => {
      if (message.found) {
        foundAddressCount++;
        if (message.attempts) {
          totalAttempts += message.attempts;
        }
        
        saveToFile(message.address, message.privateKey, patternDesc);
        
        if (targetAddressCount > 0 && foundAddressCount >= targetAddressCount) {
          const endTime = Date.now();
          const totalElapsedTime = (endTime - startTime) / 1000;
          const formattedTotalTime = formatTime(totalElapsedTime);
          
          console.log(`\n已达到${targetAddressCount}个地址的目标。正在停止...`);
          console.log(`总运行时间: ${formattedTotalTime}`);
          clearInterval(statsInterval);
          
          const summaryStats = {
            elapsedTime: totalElapsedTime,
            foundCount: foundAddressCount,
            attempts: totalAttempts,
            rate: Math.floor(totalAttempts / totalElapsedTime)
          };
          
          fs.appendFileSync(resultsFile, `\n=== 搜索完成 ===\n搜索模式: ${patternDesc}\n总运行时间: ${formattedTotalTime}\n总尝试次数: ${totalAttempts.toLocaleString()}\n总找到地址: ${foundAddressCount}\n平均速度: ${summaryStats.rate.toLocaleString()} 地址/秒\n开始时间: ${startDateTime}\n结束时间: ${new Date().toLocaleString()}\n\n`);
          
          Object.values(cluster.workers).forEach(w => w.kill());
          rl.close();
          process.exit(0);
        }
      } else {
        totalAttempts += message.attempts;
      }
    });
    
    // 处理优雅终止
    process.on('SIGINT', () => {
      const endTime = Date.now();
      const totalElapsedTime = (endTime - startTime) / 1000;
      const formattedTotalTime = formatTime(totalElapsedTime);
      const rate = Math.floor(totalAttempts / totalElapsedTime);
      
      console.log('\n正在优雅地关闭...');
      console.log(`总运行时间: ${formattedTotalTime}`);
      clearInterval(statsInterval);
      
      fs.appendFileSync(resultsFile, `\n=== 搜索被中断 ===\n搜索模式: ${patternDesc}\n总运行时间: ${formattedTotalTime}\n总尝试次数: ${totalAttempts.toLocaleString()}\n总找到地址: ${foundAddressCount}\n平均速度: ${rate.toLocaleString()} 地址/秒\n开始时间: ${startDateTime}\n结束时间: ${new Date().toLocaleString()}\n\n`);
      
      Object.values(cluster.workers).forEach(w => w.kill());
      
      console.log(`总共找到地址: ${foundAddressCount}`);
      console.log(`所有结果已保存至: ${resultsFile}`);
      process.exit(0);
    });
    
    // 为每个CPU创建工作进程
    for (let i = 0; i < numCores; i++) {
      const worker = cluster.fork();
      worker.send({ prefix, suffix });
    }
    
    rl.close();
  });
} else {
  // 这是工作进程
  process.on('message', (message) => {
    if (message.prefix !== undefined || message.suffix !== undefined) {
      workerProcess(message.prefix, message.suffix);
    }
  });
} 