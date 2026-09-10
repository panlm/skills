import json, pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

def test_init_container_takes_max_not_sum():
    """K8s 调度取 max(Σ普通容器, 各 init 容器)，不是相加。

    init 容器顺序执行且在普通容器启动前完成，故其 request 与普通容器不叠加，
    但单个 init 容器的 request 可能高于普通容器之和，此时以它为准。
    """
    pod = {"spec": {"containers": [{"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}}}],
                    "initContainers": [{"resources": {"requests": {"cpu": "2", "memory": "4Gi"}}}]}}
    cpu, mem = core.pod_requests(pod)
    assert cpu == 2.0, f"init 容器 2 核应胜出，得到 {cpu}"
    assert abs(mem - 4.0) < 1e-9

def test_pod_overhead_is_added():
    """Pod overhead 是叠加的，不参与 max 比较。"""
    pod = {"spec": {"containers": [{"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}}}],
                    "overhead": {"cpu": "50m", "memory": "128Mi"}}}
    cpu, mem = core.pod_requests(pod)
    assert abs(cpu - 0.15) < 1e-9, f"0.1 + 0.05 overhead，得到 {cpu}"
    assert abs(mem - 0.375) < 1e-9

def test_missing_requests_count_as_zero_not_none():
    """未声明 request 的容器按 0 计——这是 K8s 的真实调度行为，不是缺失数据。"""
    pod = {"spec": {"containers": [{"resources": {}}, {"resources": {"requests": {"cpu": "1"}}}]}}
    cpu, mem = core.pod_requests(pod)
    assert cpu == 1.0
    assert mem == 0.0

def test_booking_rate_over_multiple_clusters():
    """必须逐集群分别算，不能把多个集群的 requests 与 allocatable 混在一起。"""
    fx = json.loads((ROOT / "tests" / "fixtures" / "k8s-pods-sample.json").read_text())
    rates = core.booking_rates(fx["clusters"])
    assert set(rates) == {"cluster-a", "cluster-b"}
    assert rates["cluster-a"]["cpu_pct"] != rates["cluster-b"]["cpu_pct"]

if __name__ == "__main__":
    # 逐个 try/except：顺序裸调用时第一个失败就中断，后面的失败被隐藏，
    # 修一个跑一遍要跑四轮。
    tests = [test_init_container_takes_max_not_sum,
             test_pod_overhead_is_added,
             test_missing_requests_count_as_zero_not_none,
             test_booking_rate_over_multiple_clusters]
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"✓ {test_fn.__name__}")
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
