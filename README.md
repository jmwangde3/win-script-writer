# win-script-writer

中文 Windows（zh-CN / CP936 / Windows PowerShell 5.1）上给 AI agent 与脚本作者用的编码规范 Skill。

## 解决什么

- PowerShell 5.1 读 UTF-8 文件乱码、写文件变 UTF-16LE + BOM、stdout 被 UTF-8 宿主解码成乱码
- 中文路径 + 嵌套引号导致「字符串缺少终止符」/ 引号被拆散
- `.ps1` / `.bat` / `.cmd` 的 BOM 与代码页坑
- Python 在中文 Windows 默认 cp936，不显式指定 `encoding` 就炸
- agent 工具会话以 `-NoProfile` 启动，profile 里的编码兜底根本不生效

## 适用环境

Windows 10/11 简体中文、活动代码页 936、Windows PowerShell 5.1、未开启系统级 UTF-8；Git Bash / MSYS2 侧为 UTF-8。其他环境按需调整。

## 目录

| 路径 | 用途 |
| --- | --- |
| `SKILL.md` | 规则正文：硬规则、四类语言模板、bat 实测表、检查清单、错误速查 |
| `scripts/New-EncodedScript.ps1` | 按指定编码（UTF-8 无 BOM / 带 BOM / GBK）落盘脚本，中文内容走文件不走 argv |
| `scripts/Test-ScriptEncoding.ps1` | 检查 BOM、非 ASCII 字节、严格 UTF-8，输出 `VERDICT=OK/WARN/FAIL` |
| `scripts/run_ps.py` | 命令传输层免疫：UTF-16LE Base64 `-EncodedCommand` + 编码 prelude，中文路径与引号一次解决 |

## 安装

把整个目录放到 agent 的 skills 目录（`<SKILLS_DIR>/win-script-writer/`），例如 WorkBuddy 或 Claude Code 的 skills 目录。其他 agent 直接把 `SKILL.md` 的内容作为规则文件引用即可。建议把一行环境事实 + 兜底命令放进全局指令文件，详细规则按需加载，避免长文本每条会话常驻。

## 快速验证

```powershell
powershell -NoProfile -File scripts\Test-ScriptEncoding.ps1 -Path SKILL.md
powershell -NoProfile -File scripts\Test-ScriptEncoding.ps1 -Path README.md
```

```bash
python scripts/run_ps.py 'Write-Output "hello"'
python scripts/run_ps.py 'Get-ChildItem -LiteralPath "D:\work\项目" -Name'
```

## 规则摘要

1. 优先 Bash；必须用 PowerShell 时，命令开头写 `$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)`。
2. 读文件 `Get-Content -Raw -Encoding UTF8`；写文件 `[System.IO.File]::WriteAllText($p, $s, $utf8NoBom)`；禁用裸 `>` / `Out-File` / `Set-Content`。
3. `.ps1` 含中文 → UTF-8 **带 BOM**；`.bat/.cmd` 含中文 → GBK **无 BOM**；Python 所有 `open()` 显式 `encoding="utf-8"`。
4. stdout 用 ASCII/英文标签，中文只放文件内容里。
5. 命令含中文路径 + 嵌套引号 → `scripts/run_ps.py`，不要直接拼 `-Command`。

完整说明见 `SKILL.md`。

## License

MIT，见 [LICENSE](LICENSE)。
