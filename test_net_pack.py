#!/usr/bin/env python3
# test_net_pack.py: 验证"单个提交的 PACK 能否按阈值切分成多个 HTTP 请求"的可行性实验
#
# 待验证方案(标准 git smart-HTTP 协议, 不依赖任何服务端扩展):
#   1. 枚举目标提交树中【服务端缺失】的普通 Blob, 按原始大小贪心分组(每组 <= 阈值)
#   2. 每组累积子集构造一个"检查点提交"(树只含前 n 组的真实 Blob, SHA 与最终提交完全一致)
#   3. 依次把检查点提交推到临时分支 refs/heads/push-tmp-<target8>-<n>
#      -> 服务端每收到一个请求就永久入库一批 Blob; 后续公告把这些临时分支 tip 作为 have
#   4. 最后推真实分支: 协商 have 排除全部已传 Blob, 收尾 PACK 只含最后一组 + 提交/树对象
#   5. 成功后删除全部临时分支(对象保留, 本就是最终历史的组成部分)
#
# 关键性质: 不改最终历史(检查点提交不进入真实分支祖先链); 失败遗留的临时分支可断点续传。
import os,sys,stat,tempfile,threading
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import dulwich_push as pp
from dulwich.objects import Commit,Tag
from dulwich.object_store import iter_tree_contents
from dulwich.index import commit_tree
from dulwich.pack import pack_objects_to_data
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo


def peel_commits(store,shas): # 剥掉 annotated tag, 返回(commit 集合, tag 对象集合)
    commits=set();tags=set()
    for sha in shas:
        if sha not in store:continue
        obj=store[sha]
        while isinstance(obj,Tag):tags.add(obj.id);obj=store[obj.object[1]]
        if isinstance(obj,Commit):commits.add(obj.id)
    return commits,tags


def walk_tree(store,tree_sha,out): # 自有递归: 树 + 子树 + Blob/符号链接; 显式跳过 gitlink(0o160000 会被 S_ISDIR 误判)
    out.add(tree_sha);tree=store[tree_sha]
    for _name,mode,sha in tree.iteritems():
        if mode==0o160000:continue
        if stat.S_ISDIR(mode):walk_tree(store,sha,out)
        else:out.add(sha)


def reachable_objects(store,commits): # 提交可达全集 = 提交 + 树 + 普通 Blob; 不依赖 dulwich 有漏算的 get_tree_objects
    if not commits:return set()
    prov=store.get_reachability_provider()
    result=set(prov.get_reachable_commits(commits))
    for c in list(result):walk_tree(store,store[c].tree,result)
    return result


def manual_generate(repo,diag=False): # 不依赖 MissingObjectFinder 的祖先边界规则, 直接按"广告引用可达对象"做集合差
    store=repo.object_store
    def generate(have,want,**kwargs):
        hc,_=peel_commits(store,have);wc,wtags=peel_commits(store,want)
        remote=reachable_objects(store,hc);needed=reachable_objects(store,wc)|wtags
        send_ids=sorted(needed-remote)
        if diag:
            print(f"[diag] 广告have提交={len(hc)} 远端可达对象={len(remote)} 目标可达={len(needed)} 实际入包={len(send_ids)}")
        return pack_objects_to_data([(store[oid],None) for oid in send_ids],ofs_delta=kwargs.get("ofs_delta",True),progress=kwargs.get("progress"))
    return generate

THRESHOLD=2*1024*1024     # 实验阈值 2 MiB(集成时默认 50 MiB)
FILE_COUNT=26
FILE_SIZE=256*1024       # 26*256KiB = 6.5MiB 不可压缩随机数据 -> 约 4 个分块
SLACK=256*1024           # PACK 头/树对象/请求头的容差


class MeasuredTransport(pp.Transport): # 记录每个 git-receive-pack POST 实际上传字节(含请求头, 误差几百字节)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.pack_sizes=[]
    def request(self,method,url,headers=None,data=None,label="HTTP",allow_error=False):
        r=super().request(method,url,headers,data,label,allow_error)
        if method=="POST" and urlsplit(url).path.endswith("git-receive-pack"):self.pack_sizes.append(r.meter.sent)
        return r


def smart_server(tempdir,name):
    from dulwich.server import DictBackend
    from dulwich.web import make_wsgi_chain
    from wsgiref.simple_server import make_server,WSGIRequestHandler
    class Quiet(WSGIRequestHandler):
        def log_message(self,*a):pass
    bare=Repo.init_bare(str(Path(tempdir)/name),mkdir=True)
    server=make_server("127.0.0.1",0,make_wsgi_chain(DictBackend({"/test.git":bare})),handler_class=Quiet)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return bare,server,thread,f"http://127.0.0.1:{server.server_port}/test.git"


def make_client(net,url):
    return pp.StdlibGitClient(url,net)


def send(net,url,repo,updates,diag=False): # updates: {ref: newsha or ZERO_SHA(删除)}
    client=make_client(net,url)
    result=client.send_pack(urlsplit(url).path,lambda refs:dict(updates),manual_generate(repo,diag))
    if diag:print(f"[diag] ref_status={result.ref_status}")
    client.close()
    return result


def advertised_known(repo,refs): # 公告引用在本地可证明的全部可达对象
    hc,_=peel_commits(repo.object_store,[s for s in refs.values() if s and s!=ZERO_SHA])
    return reachable_objects(repo.object_store,hc)


def checkpoint_commit(repo,entries,parent,base): # 确定性元数据(复用真实提交的 author/time) -> 同一目标的检查点 SHA 跨进程稳定, 可断点续传
    c=Commit()
    c.tree=commit_tree(repo.object_store,[(p,s,m) for p,s,m,_ in entries])
    c.parents=[parent] if parent else []
    c.author=c.committer=base.author
    c.author_time=c.commit_time=base.commit_time
    c.author_timezone=c.commit_timezone=base.commit_timezone
    c.message=b"purepush http chunk checkpoint\n"
    c.check();repo.object_store.add_object(c);return c.id


def plan_groups(repo,target,known_shas,threshold): # 仅对服务端缺失的普通 Blob 按原始大小贪心分组
    items=[]
    for e in iter_tree_contents(repo.object_store,repo[target].tree):
        if e.mode not in (0o100644,0o100755):continue
        if e.sha in known_shas:continue
        items.append((e.path,e.sha,e.mode,repo.object_store[e.sha].raw_length()))
    items.sort(key=lambda x:x[0])
    groups=[];cur=[];total=0
    for item in items:
        if cur and total+item[3]>threshold:groups.append(cur);cur=[];total=0
        cur.append(item);total+=item[3]
    if cur:groups.append(cur)
    return groups


def tree_map(repo,sha):
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[sha].tree)}


def main():
    td=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);tempdir=td.name
    # 工作仓库: 一个包含 6.5MiB 随机文件的【单个提交】(不允许拆多个提交)
    work=Path(tempdir)/"work";work.mkdir(parents=True)
    repo=Repo.init(str(work))
    cf=repo.get_config();cf.set((b"user",),b"name",b"exp");cf.set((b"user",),b"email",b"exp@example.com");cf.write_to_path()
    for i in range(FILE_COUNT):
        (work/f"dir{i%4}"/f"f{i}.bin").parent.mkdir(parents=True,exist_ok=True)
        (work/f"dir{i%4}"/f"f{i}.bin").write_bytes(os.urandom(FILE_SIZE))
    import dulwich.porcelain as porcelain
    porcelain.add(repo.path,paths=[b"."])
    target=porcelain.commit(repo.path,author=b"exp <exp@example.com>",committer=b"exp <exp@example.com>",message=b"single big commit",no_verify=True)
    base=repo[target]

    failures=[]
    # ---- 场景 A: 基线, 一次性整包推送 ----
    bare_a,sa,ta,url_a=smart_server(tempdir,"a.git")
    a_args=pp.arguments(["push","--no-ask","--no-proxy","--retry","1","--low-speed-time","999"]);a_args.trace=False
    try:
        net=MeasuredTransport(a_args)
        send(net,url_a,repo,{b"refs/heads/master":target})
        one_shot=net.pack_sizes[:]
        net.close()
    finally:
        sa.shutdown();sa.server_close();ta.join(timeout=2);bare_a.close()

    # ---- 场景 B: 临时引用累积检查点切分推送 ----
    bare_b,sb,tb,url_b=smart_server(tempdir,"b.git")
    b_args=pp.arguments(["push","--no-ask","--no-proxy","--retry","1","--low-speed-time","999"]);b_args.trace=False
    tmp_prefix=b"refs/heads/push-tmp-"+target[:8]+b"-"
    try:
        net=MeasuredTransport(b_args)
        refs=make_client(net,url_b).get_refs(urlsplit(url_b).path).refs
        known=advertised_known(repo,refs)
        groups=plan_groups(repo,target,known,THRESHOLD)
        assert len(groups)>=3,f"实验数据应产生>=3个分块, 实际 {len(groups)}"
        cumulative=[];parent=None;tmprefs=[]
        for n,group in enumerate(groups[:-1],1): # 最后一组留给真实分支收尾
            cumulative.extend(group)
            cp=checkpoint_commit(repo,cumulative,parent,base);parent=cp
            tmpref=tmp_prefix+str(n).encode()
            r=send(net,url_b,repo,{tmpref:cp},diag=True)
            print(f"[diag] 检查点{n}: {tmpref.decode()} -> {cp[:8].decode()} status={r.ref_status}")
            tmprefs.append(tmpref)
        refs_again=make_client(net,url_b).get_refs(urlsplit(url_b).path).refs
        print(f"[diag] 收尾前公告引用: {[(k.decode(),v[:8].decode()) for k,v in refs_again.items()]}")
        final_result=send(net,url_b,repo,{b"refs/heads/master":target},diag=True)
        chunked=net.pack_sizes[:]
        # 成功后删除临时分支
        send(net,url_b,repo,{r:ZERO_SHA for r in tmprefs})
        after=make_client(net,url_b).get_refs(urlsplit(url_b).path).refs
        net.close()
    finally:
        sb.shutdown();sb.server_close();tb.join(timeout=2);bare_b.close()

    # ---- 断言 ----
    print("\n================ 实验结果 ================")
    print(f"缺失 Blob 分组数: {len(groups)} (阈值 {pp.human(THRESHOLD)})")
    print(f"一次性推送 POST 数/字节: {len(one_shot)} | {[pp.human(x) for x in one_shot]}")
    print(f"切分后各 POST 字节: {[pp.human(x) for x in chunked]}")
    print(f"切分请求总数: {len(chunked)} (检查点 {len(groups)-1} + 收尾 1)")

    if len(one_shot)!=1 or one_shot[0]<FILE_COUNT*FILE_SIZE:failures.append(f"基线异常: {one_shot}")
    if len(chunked)!=len(groups):failures.append(f"POST 数 {len(chunked)} != 分组数 {len(groups)}")
    for i,size in enumerate(chunked):
        if size>THRESHOLD+SLACK:failures.append(f"第 {i+1} 个请求 {pp.human(size)} 超过阈值+容差 {pp.human(THRESHOLD+SLACK)}")
    final_size=chunked[-1]
    last_group_raw=sum(x[3] for x in groups[-1])
    print(f"收尾请求: {pp.human(final_size)} (最后一组原始量 {pp.human(last_group_raw)})")
    if final_size>last_group_raw+SLACK:failures.append("收尾 PACK 未排除已传 Blob(have 协商未生效)")
    if any((final_result.ref_status or {}).values()):failures.append("收尾引用更新被拒绝")
    checked=Repo(str(bare_b.path)) # 重开句柄: 推送期间服务端写入的新 pack 对旧 Repo 的 pack 缓存不可见
    actual=set(checked.object_store)
    print(f"[diag] 服务端实际对象数: {len(actual)}")
    diag_cp=None
    cumulative=[]
    for n,group in enumerate(groups[:-1],1):
        cumulative.extend(group);diag_cp=checkpoint_commit(repo,cumulative,diag_cp,base)
        miss=reachable_objects(repo.object_store,{diag_cp})-actual
        print(f"[diag] cp{n}={diag_cp[:8].decode()} 可达对象缺在服务端: {len(miss)} {sorted(x[:8].decode() for x in miss)[:8]}")
    need_final=reachable_objects(repo.object_store,{target})
    miss_final=need_final-actual
    print(f"[diag] 目标可达对象缺在服务端: {len(miss_final)} {sorted(x[:8].decode() for x in miss_final)[:10]}")
    walker={e.sha for e in iter_tree_contents(repo.object_store,repo[target].tree)}
    print(f"[diag] iter_tree_contents 枚举 {len(walker)} | get_tree_objects {len(need_final)-1} | 差异 {sorted(x[:8].decode() for x in walker-(need_final-{target}))[:10]}")
    try:
        if checked.refs[b"refs/heads/master"]!=target:failures.append("服务端 master 未指向目标提交")
        if tree_map(checked,target)!=tree_map(repo,target):failures.append("服务端树与本地不一致")
        for path,sha in tree_map(repo,target).items(): # 逐 Blob 内容校验
            if checked.object_store[sha[0]].data!=repo.object_store[sha[0]].data:failures.append(f"Blob 内容不一致: {path}")
    finally:checked.close()
    leftover=[r for r in after if r.startswith(tmp_prefix)]
    if leftover:failures.append(f"临时分支未删净: {leftover}")
    total_chunked=sum(chunked);total_one=sum(one_shot)
    ratio=total_chunked/total_one
    print(f"总字节: 一次性 {pp.human(total_one)} | 切分 {pp.human(total_chunked)} | 比值 {ratio:.3f}")
    if ratio>1.05:failures.append("切分额外开销超过 5%")

    # ---- 场景 C: 断点续传 —— 模拟前两个检查点已在服务端 ----
    bare_c,sc,tc,url_c=smart_server(tempdir,"c.git")
    try:
        net=MeasuredTransport(b_args)
        cumulative=[];parent=None;pre=2
        for n,group in enumerate(groups[:-1],1):
            cumulative.extend(group);cp=checkpoint_commit(repo,cumulative,parent,base);parent=cp
            if n<=pre:send(net,url_c,repo,{tmp_prefix+str(n).encode():cp})
        refs=make_client(net,url_c).get_refs(urlsplit(url_c).path).refs
        known=advertised_known(repo,refs)
        groups2=plan_groups(repo,target,known,THRESHOLD)
        net.close()
    finally:
        sc.shutdown();sc.server_close();tc.join(timeout=2);bare_c.close()
    print(f"断点续传场景: 已有 {pre} 个检查点后, 缺失 Blob 分组数={len(groups2)} (期望 <= {len(groups)-pre})")
    if len(groups2)>len(groups)-pre:failures.append("断点续传分组数未收敛(已传 Blob 仍被计入)")

    print("==========================================")
    if failures:
        print("结论: 方案验证失败")
        for f in failures:print(" [FAIL]",f)
        td.cleanup();sys.exit(1)
    print("结论: 方案可行 —— 单提交可按阈值切分为多个有界 POST, 不改最终历史, 可断点续传, 开销<5%")
    td.cleanup()


if __name__=="__main__":
    main()
