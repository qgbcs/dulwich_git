我先回答原理，再分两步动手： 先修复重试重算问题（现在就改 dulwich_push.py） ， 分 PACK 切分先在独立实验文件里验证，成功后再集成 。

## 原理：git.exe 怎么解决大推送
标准 git smart-HTTP 协议里，一次`git-receive-pack` 就是 一个 POST 请求 （命令行 + 整个 PACK 在同一个请求体里）。git.exe 本身 不能 把一次引用更新的 PACK 拆成多个 HTTP 请求，也 不支持断点续传 ——失败后整个 POST 从头重发。它只有两个缓解手段：本地 pack delta 直接复用（所以它算得快）、以及把历史做成多个小提交逐次推。你已明确不接受拆 commit。

但协议里有一个可利用的机制可以实现 不改历史的请求切分 ：receive-pack 广告 所有 远端引用作为`have` ，服务端对已存在的对象不再要求发送。可以先把目标树的 Blob 分组 ，用若干临时引用（临时分支）指向"累积子集检查点提交"逐个推上去（每个请求 ≤50MB），这些 Blob 永久入库；最后推真实分支时，协商`have` 会排除全部已传 Blob，最终 PACK 只剩很小的收尾。这用标准协议、任何服务端（含 GitHub）都支持，且中途失败留下的临时分支可用于 断点续传 。

先建立任务清单：

修复重试时重复执行 MissingObjectFinder 与重新生成 PACK 的浪费(跨重试缓存)

新建 test_net_pack.py 实验验证临时引用分块上传(本地 smart HTTP 服务)

实验成功后集成 --http-chunk-size(默认50MB)到 dulwich_push.py,LFS 不受影响

