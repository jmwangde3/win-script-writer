# PowerShell 5.1 兼容性审查

这三处里，**只有 `$a ?? $b` 会让 Windows PowerShell 5.1 在解析阶段直接失败**。5.1 不支持 null 合并运算符；脚本尚未开始执行，运行时版本判断或 `try/catch` 都救不了这个解析错误。

另外两处也不能直接在 5.1 上这样用，但它们不是解析错误：

- `ForEach-Object -Parallel`：命令语法本身能解析；执行到它时，5.1 的 `ForEach-Object` 没有 `-Parallel` 参数，会报参数不存在。
- `Join-Path $a 'b' 'c'`：语法能解析；在 5.1 中会因多出的第三个位置参数而报“找不到位置参数”。PowerShell 7 支持这种多段子路径形式。

## 5.1 可运行的改写示例

```powershell
# null 合并：显式判断是否为 null
$a = $null
$b = '备用值'
if ($null -ne $a) {
    $value = $a
}
else {
    $value = $b
}

# ForEach-Object：顺序处理，5.1 和 7 都可用
1, 2, 3 | ForEach-Object {
    "项目：$_"
}

# Join-Path：嵌套调用，或使用 Path.Combine
$root = 'C:\Work'
$path = Join-Path (Join-Path $root 'b') 'c'
# 等价写法：$path = [System.IO.Path]::Combine($root, 'b', 'c')
```

若目标必须同时支持 5.1 和 7，就不要把 7 专属语法直接写进共同脚本；版本分支也不能让 5.1 跳过它，因为解析发生在分支执行之前。`-Parallel` 若确有需要，应把 7 专属代码延迟解析（例如放在字符串中再用 `[scriptblock]::Create()` 创建），或放到单独文件并仅由 PowerShell 7 子进程运行。