# 在 Windows 本地启动当前 nanobot 仓库

本文档针对 **当前这个本地仓库源码**，说明如何在 **Windows 10/11 + PowerShell** 环境里把项目跑起来。

适用场景：

- 你已经把仓库 clone 到本地
- 你希望直接从源码启动，而不是只安装 PyPI 版本
- 你主要想先把 CLI 跑通，再决定是否接入聊天渠道 / API Server

本文默认仓库路径类似：

`D:\code\nanobot\nanobot`

但步骤对其他路径同样适用。

---

## 1. 先说最短路径

如果你只想最快把项目跑起来，最短路径是：

1. 安装 Python 3.11+
2. 在仓库目录创建虚拟环境
3. 执行 `pip install -e .`
4. 执行 `nanobot onboard`
5. 配置 `~/.nanobot/config.json`
6. 执行 `nanobot agent`

如果你想看完整、稳妥、适合长期开发的流程，继续往下看。

---

## 2. 环境要求

根据当前仓库的 [pyproject.toml](D:/code/nanobot/nanobot/pyproject.toml)：

- Python 要求：`>=3.11`
- CLI 入口：`nanobot = "nanobot.cli.commands:app"`

所以你至少需要：

- Python 3.11、3.12 均可
- PowerShell

可选但常见的附加组件：

- Git：如果你还会继续拉取更新
- Node.js 18+：只有你要用 WhatsApp channel 时才需要

---

## 3. 推荐安装方式：源码开发模式

既然你现在就在仓库里，推荐直接使用 **editable install**：

```powershell
pip install -e .
```

这样做的好处是：

- 修改源码后不需要重新安装
- 更适合本地调试和二次开发

如果你还想跑测试或做开发检查，也可以装开发依赖：

```powershell
pip install -e ".[dev]"
```

---

## 4. Windows 下从零启动的完整步骤

### 4.1 确认 Python 版本

打开 PowerShell，执行：

```powershell
python --version
```

或者：

```powershell
py --version
```

你需要看到 `3.11` 或更高版本。

如果没有，请先安装 Python，并确保安装时勾选：

- `Add Python to PATH`

---

### 4.2 进入仓库目录

```powershell
cd D:\code\nanobot\nanobot
```

---

### 4.3 创建虚拟环境

推荐在仓库目录创建一个独立虚拟环境：

```powershell
python -m venv .venv
```

如果你机器上 `python` 指向不正确，也可以用：

```powershell
py -3.11 -m venv .venv
```

---

### 4.4 激活虚拟环境

在 PowerShell 中：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果提示执行策略限制，例如：

- `running scripts is disabled on this system`

可以临时只对当前 PowerShell 进程放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

激活成功后，通常命令行前面会出现：

```powershell
(.venv)
```

---

### 4.5 升级安装工具

建议先升级基础安装工具：

```powershell
python -m pip install --upgrade pip setuptools wheel
```

---

### 4.6 从当前仓库安装项目

最小安装：

```powershell
pip install -e .
```

如果你是开发者，建议：

```powershell
pip install -e ".[dev]"
```

如果你还需要 API 服务端：

```powershell
pip install -e ".[api]"
```

如果你需要特定渠道，再按需追加：

```powershell
pip install -e ".[discord]"
pip install -e ".[weixin]"
pip install -e ".[wecom]"
pip install -e ".[msteams]"
```

注意：

- `matrix` 在 Windows 上不推荐，仓库文档里也明确写了它不支持 Windows 预编译依赖

---

### 4.7 验证 CLI 安装成功

执行：

```powershell
nanobot --version
```

如果命令不可用，也可以直接用模块方式验证：

```powershell
python -m nanobot --version
```

如果模块方式可用但 `nanobot` 命令不可用，通常是：

- 虚拟环境没激活
- 或者当前 shell 没拿到虚拟环境的 Scripts 路径

---

## 5. 初始化项目配置

当前仓库的建议入口是：

```powershell
nanobot onboard
```

如果你想用交互式向导：

```powershell
nanobot onboard --wizard
```

这个命令会创建：

- 配置目录：`%USERPROFILE%\.nanobot\`
- 配置文件：`%USERPROFILE%\.nanobot\config.json`
- workspace：`%USERPROFILE%\.nanobot\workspace\`

在你的机器上，大概率会是：

- `C:\Users\你的用户名\.nanobot\config.json`
- `C:\Users\你的用户名\.nanobot\workspace\`

---

## 6. 最小可运行配置

跑起来至少需要两类信息：

1. API Key
2. 模型配置

最简单的方式是编辑：

- `C:\Users\你的用户名\.nanobot\config.json`

填入类似下面的内容。

### 6.1 OpenRouter 示例

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "timezone": "Asia/Shanghai"
    }
  }
}
```

如果你只想先验证能跑，OpenRouter 是最直接的方案之一。

---

### 6.2 使用环境变量而不是明文写 Key

在 PowerShell 当前会话中设置：

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-xxx"
```

然后配置文件中写：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "timezone": "Asia/Shanghai"
    }
  }
}
```

这比把 key 直接写死在文件里更稳妥。

---

## 7. 先启动 CLI 模式

完成配置后，最推荐先验证 CLI。

### 7.1 交互模式

```powershell
nanobot agent
```

进入后你就可以直接输入问题。

退出方式包括：

- `exit`
- `quit`
- `/exit`
- `Ctrl + C`

---

### 7.2 单次消息模式

```powershell
nanobot agent -m "你好，请介绍一下你自己"
```

这个模式适合快速验活。

---

### 7.3 模块方式启动

如果你更想确认当前仓库源码入口没有问题，也可以直接这样跑：

```powershell
python -m nanobot agent
```

原因是当前仓库的模块入口 [nanobot/__main__.py](D:/code/nanobot/nanobot/nanobot/__main__.py) 会直接调用 CLI app。

---

## 8. 启动 Gateway

如果你后续要接 Telegram / Feishu / DingTalk / Discord 等渠道，先配好 `config.json` 对应 channel，再执行：

```powershell
nanobot gateway
```

这会让进程持续运行，监听消息。

如果只是本地开发验证，**建议先把 CLI 跑通，再碰 Gateway**。

---

## 9. 启动 API Server

如果你想把它作为 OpenAI-compatible API 使用：

先确保装了 API 依赖：

```powershell
pip install -e ".[api]"
```

然后启动：

```powershell
nanobot serve
```

默认会监听：

- `127.0.0.1:8900`

你也可以指定端口：

```powershell
nanobot serve --port 9000
```

---

## 10. 推荐的本地开发启动顺序

我建议你按下面顺序来，问题最少。

### 第一步：验证 Python 和虚拟环境

```powershell
python --version
.\.venv\Scripts\Activate.ps1
```

### 第二步：安装当前仓库

```powershell
pip install -e ".[dev]"
```

### 第三步：初始化配置

```powershell
nanobot onboard
```

### 第四步：编辑 `config.json`

至少填：

- provider
- apiKey
- model
- timezone

### 第五步：先跑单次消息模式

```powershell
nanobot agent -m "hello"
```

### 第六步：再跑交互模式

```powershell
nanobot agent
```

### 第七步：最后再考虑 gateway / serve

---

## 11. 适合你的最小 PowerShell 命令清单

如果你想直接复制执行，可以用这一组。

```powershell
cd D:\code\nanobot\nanobot
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
nanobot --version
nanobot onboard
```

然后编辑：

```text
C:\Users\你的用户名\.nanobot\config.json
```

再执行：

```powershell
nanobot agent -m "hello"
nanobot agent
```

---

## 12. Windows 下常见问题

### 12.1 `Activate.ps1` 不能执行

症状：

- PowerShell 报执行策略错误

处理：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

---

### 12.2 `nanobot` 命令找不到

先确认虚拟环境是否激活：

```powershell
Get-Command nanobot
```

如果没有结果，试：

```powershell
python -m nanobot --version
```

如果模块可用但 CLI 不可用，基本就是：

- 虚拟环境未激活
- 或 shell 没刷新 PATH

---

### 12.3 `No API key configured`

说明你的 `config.json` 还没配置 provider 的 key，或者环境变量没生效。

先检查：

```powershell
Get-Content $env:USERPROFILE\.nanobot\config.json
```

如果你用环境变量，检查：

```powershell
echo $env:OPENROUTER_API_KEY
```

---

### 12.4 JSON 里的 Windows 路径写法

推荐写法：

```json
{
  "agents": {
    "defaults": {
      "workspace": "C:/Users/yourname/.nanobot/workspace"
    }
  }
}
```

比反斜杠更省心。

---

### 12.5 Windows 下 `bwrap` sandbox 不可用

仓库文档已经说明：

- `tools.exec.sandbox = "bwrap"` 只支持 Linux
- Windows 下不要启这个值

所以在 Windows 上，保持默认即可。

---

### 12.6 终端乱码 / 编码问题

当前 CLI 在 [nanobot/cli/commands.py](D:/code/nanobot/nanobot/nanobot/cli/commands.py) 里已经专门处理了 Windows UTF-8 输出。

但如果你终端仍然显示异常，建议：

- 用 PowerShell 7+
- 或 Windows Terminal
- 尽量避免老旧 `cmd.exe`

---

## 13. 开发者常用命令

### 跑测试

```powershell
pytest
```

### 只跑某个测试文件

```powershell
pytest tests\agent\test_runner.py
```

### Ruff 检查

```powershell
ruff check nanobot
```

### Ruff 格式化

```powershell
ruff format nanobot
```

---

## 14. 推荐你现在就执行的步骤

如果你的目标只是“先在本机跑起来”，我建议你现在按这个顺序做：

1. 在 [D:\code\nanobot\nanobot](D:/code/nanobot/nanobot) 打开 PowerShell
2. 创建并激活 `.venv`
3. 执行 `pip install -e ".[dev]"`
4. 执行 `nanobot onboard`
5. 编辑 `%USERPROFILE%\.nanobot\config.json`
6. 执行 `nanobot agent -m "hello"`
7. 成功后再执行 `nanobot agent`

---

## 15. 一句话总结

在你的 Windows 本地启动当前仓库，最推荐的方式是：

**PowerShell + venv + `pip install -e .` + `nanobot onboard` + 配置 `config.json` + `nanobot agent`**

先把 CLI 跑通，再考虑 Gateway 和 API Server，这样问题最少。
