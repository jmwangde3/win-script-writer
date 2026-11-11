# cmd.exe / .bat / .cmd

cmd.exe 比 PowerShell 更狠：它按**当前活动代码页**逐字节解析批处理文件本
身，而且**不认 BOM**。这意味着同一份含中文的 `.bat`，四种存法会有四种不同
的失败方式。

## 1. 四种存法的实测结果

测试条件：`.bat` 里 `if exist "<含中文的绝对路径>"` 加一句
`echo 中文 > out.txt`，直接用 `cmd.exe /c` 运行，活动代码页保持系统默认
936。判定用**整行精确匹配**——早期版本用子串匹配被 echo 回显骗过，见第 6 节。

| 存法 | 中文路径判定 | `@echo off` 是否生效 | `out.txt` 落盘字节 |
| --- | --- | --- | --- |
| UTF-8 无 BOM | **PATH_FAIL** | 是 | `E4 B8 AD E6 96 87` |
| UTF-8 with BOM | **PATH_FAIL** | **否**，首行变成 `<EF BB BF>@echo off` | `E4 B8 AD E6 96 87` |
| GBK(936) 无 BOM | **PATH_OK** | 是 | `D6 D0 CE C4` |
| UTF-8 无 BOM + 首行 `chcp 65001 >nul` | **PATH_OK** | 是 | `E4 B8 AD E6 96 87` |

三个要点：

1. **三种失败/成功下 `exit=0` 都是 0。** cmd 不会因为路径找不到而返回非零，
   除非你显式 `exit /b`。所以"脚本跑完了没报错"完全没有信息量。
2. **BOM 是唯一连 `@echo off` 都会破坏的情况**：`<EF BB BF>@echo off` 不是
   合法命令，echo 保持打开，屏幕上出现满屏命令回显，之后每一行都被重新
   解释。
3. **`echo` 写出的是文件里的原始字节，不是按控制台代码页重编码后的字节。**
   所以 UTF-8 存法写出的也是 UTF-8 字节——这解释了为什么"cmd 显示乱码但
   文件其实是 UTF-8"。

## 2. 结论：新脚本不要写 .bat

优先顺序：Bash（若可用）→ PowerShell → 最后才是 `.bat`。
`.bat` 只在"必须双击运行 / 计划任务 / 极老系统"时才选。

已有 `.bat` 的改造方向：

```bat
@echo off
chcp 936 >nul
rem 骨架保持纯 ASCII：命令、变量名、标签、注释全部英文
rem 中文内容放进外部 UTF-8 数据文件，交给 PowerShell 或 Python 读
powershell.exe -NoProfile -File "%~dp0work.ps1"
exit /b %ERRORLEVEL%
```

要点：`.bat` 只做启动器，不做数据处理。

## 3. 如果必须内联中文

存成 **ANSI/GBK(936) 无 BOM**。这是唯一同时满足"路径正确"和"`@echo off`
生效"的存法。

必须用 UTF-8 时（例如与仓库其他文件统一），首行加 `chcp 65001 >nul`，且
文件本身**不能有 BOM**。本机实测可用，但要知道代价：

- 老版本 Windows 10 在 65001 下 `for /f`、管道、重定向有历史缺陷，换机器
  必须重测。
- `chcp` 会改变整个控制台的活动代码页，子进程继承。
- 某些第三方程序在 65001 下仍按 ANSI 解释参数。

## 4. 代码页边界清单

以下每一处都会重新按活动代码页解码：

| 位置 | 说明 |
| --- | --- |
| `for /f %%i in (file)` | 按当前 CP 解码文件每一行 |
| `findstr 中文 file` | 模式串与文件都按当前 CP 比对 |
| `type file` / `more file` | 输出按当前 CP 解释 |
| `程序A \| 程序B` | 管道两侧各自解码/编码，中间字节不经转换 |
| `set /p x=<file` | 读第一行，按当前 CP |
| `>> log.txt` 里的中文 | 写入原始字节 |

判据：**只要数据跨过一次进程或文件边界，就要问一次"这里按哪个代码页"。**

## 5. 退出码

```bat
@echo off
some-command.exe
if errorlevel 1 exit /b 1
exit /b 0
```

不写 `exit /b` 时，`.bat` 的退出码是**最后一条命令**的退出码，很容易变成
0。CI 里这等于没有检查。

## 6. 一个真实的踩坑（留作教训）

第一次测四种存法时，判定逻辑写成"stdout 里是否包含 `PATH_OK`"。UTF-8 with
BOM 那一组看起来通过了，因为 `@echo off` 被 BOM 破坏后，cmd 把
`if exist "..." (echo PATH_OK) else (echo PATH_FAIL)` **整行回显**出来，
里面同时含两个标记，子串匹配必然命中。

改成整行精确匹配后立刻暴露为 `PATH_FAIL`。

教训：**测试判定不能用被测对象的输出当唯一证据**，尤其当输出本身可能被
污染时。现在的 `tests/` 里所有断言都基于结构化字段（`VERDICT=`、
`ENCODING=`）或精确行匹配。
