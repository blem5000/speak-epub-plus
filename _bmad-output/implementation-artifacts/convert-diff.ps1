$src = 'C:\Users\admin\Documents\programowanie\speak epub\_bmad-output\implementation-artifacts\b1-review-diff.txt'
$dst = 'C:\Users\admin\Documents\programowanie\speak epub\_bmad-output\implementation-artifacts\b1-review-diff-utf8.txt'
$c = Get-Content -Raw -Encoding Unicode $src
[System.IO.File]::WriteAllText($dst, $c, [System.Text.UTF8Encoding]::new($false))
(Get-Item $dst).Length