# 5.1 解析兼容性审查

严格按“**直接解析失败**”来分，三处里只有 `$a ?? $b` 会让 Windows PowerShell 5.1 在脚本开始执行前就报解析错误。空合并运算符从 PowerShell 7.0 才加入；把它放进版本判断或 `try/catch` 也救不了，因为 5.1 必须先解析整个文件。

另外两处会在 5.1 出问题，但不是解析失败：

- `ForEach-Object -Parallel`：`-Parallel` 是 PowerShell 7.0 才有的参数。5.1 能解析这条命令，但执行到它时会因参数不存在而报错。
- `Join-Path $a 'b' 'c'`：5.1 的 `Join-Path` 不接受这三个位置参数，执行时会报位置参数无法绑定。它不是解析错误。PowerShell 7 支持 `-AdditionalChildPath`，但要显式写参数名；上面这种三位置参数写法在参考资料列出的实测中，7 也可运行。

双版本脚本可改用两边都支持的写法，例如：

```powershell
# 空合并的 5.1 兼容写法
$a = $null
$b = 'fallback'
if ($null -ne $a) {
    $value = $a
}
else {
    $value = $b
}

# Join-Path 的 5.1 兼容写法
$a = Join-Path $env:TEMP 'parent'
$path = Join-Path (Join-Path $a 'b') 'c'

# ForEach-Object -Parallel 的兼容替代：顺序处理
1, 2, 3 | ForEach-Object {
    $_ * 2
}
```

结论：若问题只问“哪些写法让 5.1 **直接解析失败**”，答案是 `$a ?? $b`。另两处属于运行期不兼容，审查时也应修，但应准确区分错误阶段。
