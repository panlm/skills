#!/usr/bin/env python3
"""aws-rightsizing 判据核心。

职责边界
--------
本文件只做**判断**，不做采集、不调 AWS API、不读写文件路径。
采集、region 循环、分批、输出布局由 agent 按自身环境组装（见 cli-recipes.md）。

这样分工的依据：判据错了是静默的且后果重（降配/删除），必须固定；
采集是环境相关的，agent 适配比预设的模板强。

用法
----
    python3 core.py < input.json > findings.json

stdin 单个 JSON 对象：
    {"sizing_profile": "aggressive|conservative", "specs": [...], "prices": {...},
     "baseline_pct": {...}, "categories": {...}, "offerings": [...],
     "legacy_families": [...], "resources": [...]}

`sizing_profile` 必填（给了 "thresholds" 则用它，用于测试注入）。
`resources` 的每一条必须带 `"service"`，取值 `ec2` / `rds` / `elasticache` / `msk`，
决定走哪条判据；缺失或不认识一律抛错，不回退 ec2（见 `dispatch`）。

stdout 为 findings 数组，一资源一行。

缺失值语义（全局唯一规则）
--------------------------
缺失一律为 None，**禁止兜底为 0 或任何默认值**。
0 恰好都指向「更该被优化」的方向：
    网络缺失 → 零流量 → 误判闲置 → 建议删除
    EBS 缺失 → 无吞吐需求 → 跳过带宽校验 → 选出带宽不够的机型
    信用缺失 → 没超额 → 放行 burstable → 选出会被限流的机型
三者都推向误报，而误报的代价是故障、漏报只是少省钱。故默认 fail-closed。

实测教训：一处 Python 写成 `net_mb_day or 1e9`，因 `0.0 or 1e9 == 1e9`
漏判一台 $1,369/mo 的实例——0 被当假值。本文件一律用 `is None` 判缺失。
"""
import json
import math
import pathlib
import re
import sys

ACCEL_RE = re.compile(r"^(g|p|inf|trn)")
FLEX_RE = re.compile(r"-flex\.")
GEN_RE = re.compile(r"(\d+)")
LETTERS_RE = re.compile(r"^([a-z]+)")
GP_CATS = {"General purpose", "Compute optimized", "Memory optimized"}
HOURS_PER_MONTH = 730

_THRESHOLDS_PATH = pathlib.Path(__file__).with_name("thresholds.json")
_PI_UNSUPPORTED_PATH = pathlib.Path(__file__).with_name("rds-pi-unsupported.json")


def load_pi_unsupported(path=None):
    """不支持 Performance Insights 的 RDS 实例类。**唯一真值源。**

    不在本文件内写字面量：写死等于第二个真值源，AWS 扩了支持范围后
    报告仍会向客户断言旧列表。同 `load_thresholds` 的理由。
    `tests/test_no_duplicated_constants.py` 锁死 `core.py` 里不得出现这些类名。
    """
    p = pathlib.Path(path) if path else _PI_UNSUPPORTED_PATH
    return frozenset(json.loads(p.read_text(encoding="utf-8"))["classes"])


def load_thresholds(profile="aggressive", path=None, override=None):
    """从 thresholds.json 读一个 profile。

    阈值不在本文件内写字面量——那会让 thresholds.json 失去唯一真值地位，
    且散文文档与代码可能各自漂移（本 skill 已在 Sum 系数上犯过两次）。

    未知 profile 抛 ValueError 而非回退默认值：静默回退会让
    `--profile consrvative`（拼错）跑出 aggressive 的结果而无人察觉。
    """
    data = json.loads((pathlib.Path(path) if path else _THRESHOLDS_PATH).read_text())
    profiles = data["profiles"]
    if profile not in profiles:
        raise ValueError(f"未知 sizing_profile: {profile}；可选 {sorted(profiles)}")
    t = dict(profiles[profile])
    if override:
        unknown = set(override) - set(t)
        if unknown:
            raise ValueError(f"override 含未定义的键: {sorted(unknown)}")
        t.update(override)
    return t


def _fam(itype):
    return itype.split(".")[0]


def _gen(itype):
    m = GEN_RE.search(_fam(itype))
    return int(m.group(1)) if m else 0


def _letters(itype):
    m = LETTERS_RE.match(_fam(itype))
    return m.group(1) if m else ""


def _n(v):
    """整数值不带小数点。采集侧的 vcpu 常是浮点（`4.0`），直接插进 blocker
    会让客户读到「当前仅 4.0」。金额不走这里 —— 那些要保留两位小数。
    """
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _ceil_div(numer, denom):
    return math.ceil(numer / denom)


def _required(cur, sustained, peak, target, ceiling):
    """两项取 max：保证降配后 p95 与峰值都不越界。

    峰值项不可省——只看 p95 会把有尖峰的负载降到峰值打满。
    """
    return max(_ceil_div(cur * sustained, target), _ceil_div(cur * peak, ceiling))


CLASS_CHANGED_NOTE = (
    "当前机型非突发，却存在 CPU 信用序列 —— 说明**窗口内改过规格**。"
    "该余额测自另一个规格，不作为当前规格的否决依据；但本行的利用率百分比"
    "混合了两个规格的采样（需求量按当前核数反推），须人工复核")


def _credit_exhausted(cb_min, cb_max, t):
    """信用余额在窗口内是否触底。两个入参都必须非 None（由调用方守卫）。

    判「占窗口内观测最大余额的百分比」而不是「占信用上限」：上限
    = vcpu x baseline_pct x 1440，而 RDS 的 baseline 百分比**不在本 skill 的
    静态资产里**（baseline-pct.json 只覆盖 EC2 机型）。用观测最大值自归一化，
    EC2 与 RDS 共用一套算法，且不引入第二张静态表。
    实测分离度：触底 0.00%-0.14%，健康 85.07%-99.91%，中间无观测点。

    **不判 `cb_min == 0`。** Minimum 是逐小时最小值，真实耗尽时通常落到 0 但
    不保证——实测两台 RDS 的最小值是 0.79 / 0.70。把判据建在「恰好等于 0」上，
    会让余额在 0.3 附近徘徊的饿死实例逃掉，而那正是本判据要抓的一类。
    """
    if cb_max == 0:
        return True          # 整窗口恒为 0 = 彻底耗尽；同时兜住除零
    return cb_min <= cb_max * t["credit_balance_floor_pct"] / 100.0


def _eff_vcpu(spec, baseline_pct):
    """交付的持续 vCPU。burstable 机型只交付基线部分。

    回收量必须按此计算，否则 m5.xlarge → t3.xlarge（同为 4C/16G）
    会算出 delta=0，看起来毫无意义。
    """
    pct = baseline_pct.get(spec["t"])
    return spec["vcpu"] * (pct if pct is not None else 1.0)


def evaluate(res, ctx):
    """判定单个资源。返回 findings 字典。"""
    t = ctx["thresholds"]
    specs_by_type = ctx["_specs_by_type"]
    prices = ctx["prices"]
    base = ctx["baseline_pct"]
    cats = ctx["categories"]
    offerings = ctx["_offerings"]
    legacy = ctx["_legacy"]

    rid = res["rid"]
    itype = res["type"]
    coverage = res.get("metric_coverage") or []
    out = {"rid": rid, "cur": itype, "az": res.get("az"),
           "metric_coverage": coverage, "nonburst": None, "burst": None,
           "burst_na": None, "required_vcpu": None, "required_gib": None}
    _coverage_note(out, res)

    # ---- 采样量：分档而非拒绝 ----
    # 阈值用下标取而非 .get()：注入的 thresholds 缺这个键时必须抛 KeyError。
    # 用 .get() 会让分档静默消失。
    #
    # 「少」与「无」是两件事，走相反的路：
    #   n is None   —— 不知道有多少点，连降档都无从判断 ⇒ fail-closed
    #   n == 0      —— 零个点算不出 p95 ⇒ fail-closed
    #   0 < n < 门限 —— 数据少但存在 ⇒ 照常判据，confidence 降到 low
    #
    # 旧行为（n < 门限即 return insufficient-data）连**否决项**一起压掉了：
    # 实测两条真实健康事实（MSK URP 27、Redis 复制延迟 23.88s）被一句
    # 「点数不足」盖住。采样量挡不住否决项 —— 否决项读的是 max，不是 p95。
    n = res.get("cpu_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n == 0:
        out["verdict"] = "insufficient-data"
        out["burst_na"] = (f"biz-hours {'点数未知' if n is None else '0 点'}"
                           f"（门限 {floor_pts}），p95 无从计算")
        # 成本是事实、不是判断：单价查表不依赖任何指标。不填会让摘要分母
        # 漏掉这些行、节省比例虚高（实测漏 $286.67/mo，23.2% 虚高成 27.7%）。
        # 只在本分支内 best-effort 查，不把查表整段提到守卫之前 ——
        # 那会让 spec-unknown / price-unknown 抢在 insufficient-data 之前，
        # 改变 verdict 链的优先级。
        cs = specs_by_type.get(itype)
        usd = prices.get(f"{itype}|{res.get('operation')}")
        if cs is not None:
            out.update(cur_vcpu=cs["vcpu"], cur_gib=cs["gib"])
        if usd is not None:
            out.update(cur_usd=usd, cur_cat=cats.get(itype),
                       cur_cost_mo=round(usd * HOURS_PER_MONTH
                                         * res.get("count", 1), 2))
        return out

    low_sample = n < floor_pts

    cs = specs_by_type.get(itype)
    if cs is None:
        out["verdict"] = "spec-unknown"
        out["burst_na"] = "当前机型规格未知"
        return out

    cur_usd = prices.get(f"{itype}|{res.get('operation')}")
    if cur_usd is None:
        out["verdict"] = "price-unknown"
        out["burst_na"] = "无按需价格，不得退回「最小够用」选型"
        return out

    out.update(cur_vcpu=cs["vcpu"], cur_gib=cs["gib"], cur_usd=cur_usd,
               cur_cat=cats.get(itype),
               cur_cost_mo=round(cur_usd * HOURS_PER_MONTH * res.get("count", 1), 2))

    if ACCEL_RE.match(itype):
        out["verdict"] = "excluded"
        out["burst_na"] = "加速机型，需 GPU/加速器利用率数据，本版本不评估"
        return out

    # ---- 关键指标缺失 ⇒ fail-closed。必须早于「已合理配置」判定 ----
    # 否则「没能力判断」会被伪装成「无需优化」，是最坏的静默降级。
    sus_cpu, peak_cpu = res.get("sus_cpu"), res.get("peak_cpu")
    if sus_cpu is None or peak_cpu is None:
        out["verdict"] = "metric-missing"
        out["burst_na"] = "CPU 指标缺失，无法反推需求量"
        return out
    if res.get("ebs_need") is None:
        out["verdict"] = "metric-missing"
        out["burst_na"] = "EBS 吞吐指标缺失，无法校验候选机型带宽（不可当 0）"
        return out

    rv = _required(cs["vcpu"], sus_cpu, peak_cpu,
                   t["target_cpu_p95"], t["ceiling_cpu_max"])
    # 无内存数据 ⇒ 内存保持当前规格。不设绝对下限——那是替实例做假设。
    if res.get("sus_mem") is None or res.get("peak_mem") is None:
        rg = cs["gib"]
        mem_known = False
    else:
        rg = _required(cs["gib"], res["sus_mem"], res["peak_mem"],
                       t["target_mem_p95"], t["ceiling_mem_max"])
        mem_known = True
    out.update(required_vcpu=rv, required_gib=rg)

    # 突发上限是标称 vCPU 的 100%，不能超过 ⇒ burstable 候选的标称核数下限
    rv_peak = _ceil_div(cs["vcpu"] * peak_cpu, t["ceiling_cpu_max"])
    eff_cur = _eff_vcpu(cs, base)
    ebs_need = res["ebs_need"]

    def passes_common(sp):
        if sp["arch"] != res.get("arch"):
            return False
        if _fam(sp["t"]) in legacy:
            return False
        if FLEX_RE.search(sp["t"] + "."):
            return False
        if sp["t"] not in offerings:
            return False
        if sp.get("store") != cs.get("store"):
            return False
        # 代次数字只在同族字母内可比：m5 与 t3 同属 Nitro 期，5>3 无意义
        if _letters(sp["t"]) == _letters(itype) and _gen(sp["t"]) < _gen(itype):
            return False
        cat = cats.get(sp["t"])
        if cat is None or not (cat in GP_CATS or cat == cats.get(itype)):
            return False
        if ebs_need > 0 and (sp.get("ebs") is None or sp["ebs"] < ebs_need):
            return False
        usd = prices.get(f"{sp['t']}|{res.get('operation')}")
        if usd is None or usd >= cur_usd:
            return False
        # 降幅上限：目标利用率管不了「窗口外的周期」与「发布间隔内的尖峰」。
        # 这个理由与指标种类无关，所以内存同样要设地板 —— 而且
        # mem_used_percent 不含可回收 page cache，会把内存 p95 压低，
        # 内存比 vCPU 更需要它。实测缺陷：4 GiB 被建议降到 1 GiB（4x），
        # 而同一 profile 允许的 vCPU 降幅要小得多（倍数见 thresholds.json）。
        if sp["vcpu"] < _ceil_div(cs["vcpu"], t["max_reduction_ratio"]):
            return False
        if sp["gib"] < _ceil_div(cs["gib"], t["max_mem_reduction_ratio"]):
            return False
        return True

    # 信用余额触底 = 当前规格已不足，且**会把 CPUUtilization 压住**（限流到基线），
    # 所以必须在用持续值挑候选之前就把两列候选压掉 —— 否则会对一台饿死的机器
    # 推荐再降一档。适用性同 surplus_credits：仅当前机型为 T 系列才判。
    cb_min, cb_max = res.get("credit_balance_min"), res.get("credit_balance_max")
    if not cs["burst"]:
        # 非突发机型：缺失属「不适用」；**存在**则说明窗口内改过规格（实测两台
        # db.m6g.xlarge 有 178/720 的信用序列，上限对应 2 vCPU 机型）。
        credit_exhausted = False
        if cb_min is not None:
            out.setdefault("blockers", []).append(CLASS_CHANGED_NOTE)
    elif cb_min is None or cb_max is None:
        # 当前机型是 T 系列 ⇒ 该序列必然存在，缺失是真缺失 ⇒ fail-closed。
        # 不能放行：信用耗尽会把 CPUUtilization 压住，放行等于对一台可能饿死的
        # 机器按被压低的持续值定档。
        out["verdict"] = "metric-missing"
        out["burst_na"] = "CPUCreditBalance 缺失，无法排除信用已耗尽"
        return out
    else:
        credit_exhausted = _credit_exhausted(cb_min, cb_max, t)

    pool = [dict(sp, usd=prices[f"{sp['t']}|{res.get('operation')}"])
            for sp in ctx["specs"] if passes_common(sp)]

    nb = sorted((s for s in pool
                 if not s["burst"] and s["vcpu"] >= rv and s["gib"] >= rg),
                key=lambda s: (s["usd"], s["t"]))
    out["nonburst"] = None if credit_exhausted else (nb[0] if nb else None)

    # 先判「适用性」再判「缺失」。CPUSurplusCreditsCharged 只有 T 系列发布，
    # 对非突发当前机型它是「不适用」而不是「缺失」——
    # 无条件 fail-closed 会让突发降配路线在生产上永久不可达（实测 25/29 台）。
    # 与 eval_rds 的 _rds_is_burstable 守卫同构。
    sc = res.get("surplus_credits")
    if credit_exhausted:
        out["burst_na"] = "CPU 信用余额窗口内触底，当前规格已不足"
    elif cs["burst"] and sc is None:
        out["burst_na"] = "CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用"
    elif sc is not None and sc > 0:
        out["burst_na"] = "CPUSurplusCreditsCharged>0，当前规格已不足"
    else:
        sus_abs = cs["vcpu"] * sus_cpu / 100.0
        head = 1 - t["burstable_baseline_headroom"]
        b = sorted((s for s in pool
                    if s["burst"] and base.get(s["t"]) is not None
                    and s["gib"] >= rg and s["vcpu"] >= rv_peak
                    and _eff_vcpu(s, base) * head >= sus_abs),
                   key=lambda s: (s["usd"], s["t"]))
        out["burst"] = b[0] if b else None
        if not b:
            if rv > t["burstable_max_vcpu"] or rg > t["burstable_max_gib"]:
                # 数值必须来自 thresholds，不能写死：写死会让调低阈值后
                # 报告仍然向客户断言旧上限。
                out["burst_na"] = (f"超 T 系列上限 {t['burstable_max_vcpu']}C/"
                                   f"{t['burstable_max_gib']}G")
            elif not any(s["burst"] and base.get(s["t"]) is not None for s in pool):
                out["burst_na"] = "baseline-unknown"
            else:
                out["burst_na"] = f"峰值需 {rv_peak} vCPU 或无更便宜的合规 T 机型"

    cnt = res.get("count", 1)
    for key, pick in (("nb", out["nonburst"]), ("b", out["burst"])):
        if pick:
            out[f"{key}_save_mo"] = round((cur_usd - pick["usd"]) * HOURS_PER_MONTH * cnt, 2)
            out[f"{key}_delta_vcpu"] = round(eff_cur - _eff_vcpu(pick, base), 3)
            out[f"{key}_delta_gib"] = cs["gib"] - pick["gib"]
            out[f"{key}_cat"] = cats.get(pick["t"])
        else:
            out[f"{key}_save_mo"] = None

    # 样本量的问题盖过内存口径的问题：低样本一律 low，不再区分有无内存数据。
    if low_sample:
        out["confidence"] = "low"
        out.setdefault("blockers", []).append(
            f"样本 {n} 点 < {floor_pts}（占门限 {round(n / floor_pts * 100)}%），"
            f"p95 统计意义弱，本行结论的置信度相应下降，窗口填满后须复评。"
            f"若本行给出了变更建议，执行前优先安排回滚演练")
    else:
        out["confidence"] = "medium" if not mem_known else "high"
    # 「找不到候选」有三种成因，只有一种是「已合理配置」：需求量超过当前规格时
    # 降配搜索本来就不可能有结果，把它标成「已合理配置」是对客户的错误肯定断言。
    #
    # 只按**持续项**判规格不足。_required 的峰值项是为**降配方向**设计的安全约束
    # （降配后 max 不得越 ceiling），拿它反推「当前规格不足」会把 p95 1.09% /
    # max 76% 的闲置小机器判成不足。实测按持续项筛，9 行收敛到 4 行。
    rv_sus = _ceil_div(cs["vcpu"] * sus_cpu, t["target_cpu_p95"])
    # 无内存数据 ⇒ 内存轴不参与判定。此时 rg 已被置为 cs["gib"]（内存保持当前
    # 规格），拿它反推「内存不足」是替实例做假设。
    rg_sus = (_ceil_div(cs["gib"] * res["sus_mem"], t["target_mem_p95"])
              if mem_known else 0)
    if credit_exhausted:
        # 与「持续项超」是同一结论（当前规格已不足）的两条独立证据。信用触底须
        # 排在持续项之前：被限流的实例持续值必然偏低，先判持续项会让它落进
        # 「已合理配置」。两者同时成立时 blocker 都写，它们解释的是不同事实。
        out["verdict"] = "upsize-candidate"
        out.setdefault("blockers", []).insert(
            0, f"CPU 信用余额窗口内触底（最小 {cb_min} / 窗口内最大 {cb_max}，"
               f"门限 {t['credit_balance_floor_pct']}%）⇒ 当前规格已不足。"
               f"注意此时 CPUUtilization 被限流压住，持续值不可用于定档。"
               f"本 skill 不产出升配目标机型——选型需容量规划输入")
    elif out["nonburst"] or out["burst"]:
        # 候选池已要求 vcpu >= rv and gib >= rg（rv/rg 是两项取 max 的全量需求），
        # 所以选出了候选就说明它满足全量需求 —— 合法降配，不是规格不足。
        # 实测存在这种形态且现行行为正确：某 c7i.8xlarge 的 required 内存
        # 85 GiB > 现有 64 GiB，却选出 r5.4xlarge（128 GiB）并省 $349.23。
        out["verdict"] = "downsize"
    elif rv_sus > cs["vcpu"] or rg_sus > cs["gib"]:
        out["verdict"] = "upsize-candidate"
        axes = []
        if rv_sus > cs["vcpu"]:
            axes.append(f"CPU 持续 p95 {sus_cpu}% ⇒ 按目标 "
                        f"{t['target_cpu_p95']}% 反推需 {rv_sus} vCPU，"
                        f"当前仅 {cs['vcpu']}")
        if rg_sus > cs["gib"]:
            axes.append(f"内存持续 p95 {res['sus_mem']}% ⇒ 按目标 "
                        f"{t['target_mem_p95']}% 反推需 {rg_sus} GiB，"
                        f"当前仅 {cs['gib']}")
        # insert(0) 而不是 append：规格不足是本行的**结论**，须排在低样本等
        # 附注之前。_verdict() 对托管侧做的是同一件事。
        out.setdefault("blockers", []).insert(
            0, "当前规格已不足（" + "；".join(axes)
            + "）。本 skill 不产出升配目标机型——选型需容量规划输入"
              "（增长率 / SLA / 峰值形态）。basic monitoring 会压低持续值，"
              "故本判据偏保守")
    else:
        out["verdict"] = "已合理配置"
        if rv > cs["vcpu"] or rg > cs["gib"]:
            out.setdefault("blockers", []).append(
                f"需求量 {rv} vCPU / {rg} GiB 大于当前规格 "
                f"{cs['vcpu']} vCPU / {cs['gib']} GiB，但由**峰值项**驱动"
                f"（CPU max {peak_cpu}% 对 ceiling {t['ceiling_cpu_max']}%）；"
                f"持续项未超（CPU p95 {sus_cpu}% 对目标 "
                f"{t['target_cpu_p95']}%），故不判规格不足。峰值项的作用是"
                f"防止降配落在尖峰上，不是升配判据")
    return out


def is_idle(res, t):
    """桶 B 闲置判据。显式判 None——0 是有效值（零流量是最强闲置信号）。"""
    c, netv, n = res.get("sus_cpu"), res.get("net_mb_day"), res.get("cpu_n")
    if n is None or n < t["min_biz_hours_points"]:
        return False
    if c is None or netv is None:
        return False
    return c < t["idle_cpu_p95"] and netv < t["idle_net_mb_day"]


# 桶 C 只看这两档：biz-hours 有负载是正常的，不构成停机的反对意见。
STOP_BANDS = ("off", "weekend")


def is_stop_candidate(res, t):
    """桶 C（定时停机）候选判据。返回 True / False / **None**。

    `None` 是「判不了」，与 `False`（判过了，不是候选）严格区分。桶 C 的产出
    是候选清单 + 三档证据、判断权交给执行方，所以「没评估」显示成「不是候选」
    是最坏的静默降级——报告会看起来像"已经查过、没有可停的"。
    `is_idle` 只能返回布尔，因为它决定 `bucket` 归属、没有第三态可放；
    桶 C 是独立一列，有空间把三态表达出来。

    三个门限全部要过，且 `off-hours` 与 `weekend` 两档都要过：
        p95 CPU   <  idle_cpu_p95
        日均网络   <  idle_net_mb_day
        峰值 CPU  <= stop_candidate_peak_cpu_max
    **不得只用 CPU 一个信号**——那会把被动监听型服务全部误判为可停
    （`thresholds.md` 把"自造判据"单列为禁止项，这是其中最常见的一种）。
    """
    n = res.get("cpu_n")
    if n is None or n < t["min_biz_hours_points"]:
        return None
    for band in STOP_BANDS:
        c = res.get(f"{band}_sus_cpu")
        pk = res.get(f"{band}_peak_cpu")
        netv = res.get(f"{band}_net_mb_day")
        if c is None or pk is None or netv is None:
            return None
        if not (c < t["idle_cpu_p95"] and netv < t["idle_net_mb_day"]
                and pk <= t["stop_candidate_peak_cpu_max"]):
            return False
    return True


# ============================================================
# 托管服务判据：RDS / ElastiCache / MSK
# 与 EC2 共用 _required / 缺失=None / fail-closed 规则，
# 但各有**否决项**，且否决项优先级高于降配前置条件。
# ============================================================

# cheaper_candidate_exists 由采集侧按**价格**判定，不校验候选是否装得下
# 当前需求。实测：一个 cache.t4g.medium 复制组该字段为 true，但内存已用到
# maxmemory 的 59.24%（需节点内存 >= 1.830 GiB），同架构下更便宜的两个候选
# （cache.t4g.small 1.37 GiB、cache.t4g.micro 0.5 GiB）都装不下 ⇒ 实际可省 $0。
# 不把适配校验复制到采集侧（那会造出第二个判据实现点，违反本文件开头的
# 职责边界），改为在结论上标注。
_FIT_UNVERIFIED = ("更便宜候选是否装得下当前需求未经校验"
                   "（cheaper_candidate_exists 只按价格判定）；"
                   "目标规格须人工确认，可能不存在满足需求的更便宜机型")

_MANAGED_PREFIX_RE = re.compile(r"^(?:db|cache|kafka)\.")


def _managed_ec2_name(itype):
    """`db.t4g.medium` -> `t4g.medium`。

    **只用于查 `baseline_pct` 与 `arch`，绝不用于查内存。**
    实测 `cache.t3.medium` 真实 3.09 GiB，映射到 EC2 `t3.medium` 得 4.00 GiB，
    偏 +29%；而 `DatabaseMemoryUsagePercentage` 是相对真实节点内存的百分比，
    基数错则绝对量全错。内存一律取 pricing 的 `memory` 属性。
    后人若想把这个映射"顺手统一"到内存上，先读这段注释。
    """
    return _MANAGED_PREFIX_RE.sub("", itype)


def _managed_baseline(itype, base):
    """托管突发机型的基线百分比。复用 EC2 的 `baseline-pct.json`。

    `_credit_exhausted` 的 docstring 写过「RDS 的 baseline 百分比不在本 skill
    的静态资产里」—— 那句话对**当前**机型的信用上限判定成立（那里改用观测
    最大值自归一化，避免引入第二张静态表）。但候选机型没有观测数据，
    只能查表。可验证性：信用上限 = vcpu x baseline x 1440。已确认吻合两例 ——
    `cache.t3.medium` 576 = 2 x 0.20 x 1440、`cache.t4g.micro` 288 = 2 x 0.10 x 1440。

    查不到 ⇒ 返回 None ⇒ 该候选被排除在突发列之外，与 EC2 侧
    `base.get(s["t"]) is not None` 那道过滤同构（fail-closed：信用余量
    无从校验时不得推荐突发机型）。
    """
    return base.get(_managed_ec2_name(itype)) if base else None


# 候选池为空的五种成因。动作相同（都不降配）但可操作性完全不同：
# 「已在价目地板」补指标也没用，「被降幅地板挡住」是策略选择，
# 「需求量超过候选」要容量规划。改动前五种给同一句话
# （「同形态下没有更便宜的候选机型」），而那句话在后三种下是**错的**。
_EMPTY_NO_CHEAPER = ("同形态下更便宜的候选数为 0（已在价目地板上）；"
                     "补充指标或延长窗口都不会改变结论")
_EMPTY_CROSS_ARCH = ("更便宜的候选存在但全部跨 CPU 架构（{types}）；"
                     "跨架构迁移是本 skill 的硬约束禁止项，不是可调阈值")
_EMPTY_VCPU = ("需求量 {req} vCPU 超过所有更便宜候选（最接近的 {best} 只有 "
               "{best_vcpu} vCPU）")
_EMPTY_MEM = "更便宜的候选都装不下当前需求（最接近的是 {best}）"
_EMPTY_FLOOR = ("被降幅地板挡住而非适配失败：max_reduction_ratio={mrr} 要求候选"
                "至少 {floor} vCPU，更便宜的候选都低于它")
_EMPTY_EXCLUDED = ("唯一装得下的更便宜候选（{best}）已被排除（见本行其他 blocker "
                   "说明的排除理由），故无可用目标")

# 「触底」护栏：目标是同架构阶梯里最便宜的那一档。
#
# 这里刻意**不用档数阈值**。先写的版本是「距当前规格 >= 4 档」，实测在
# ElastiCache 上永不触发 —— 同架构比 cache.m6g.large 便宜的候选总共只有 3 档
# （t4g.micro / t4g.small / t4g.medium），阈值取 4 等于把护栏关掉，而取 3
# 又是为凑这条阶梯挑的数，换个 region 或服务就失效。
#
# 「落在阶梯最底部」是结构性属性而非调出来的数：底部意味着估错了没有退路
# （不能再降），且任何数据量增长都只能升配。乘性余量在极小基数上正是在这里
# 失去意义 —— 实测一个复制组实占 0.013 GiB，x1.5 余量后仍选到最底档，
# 倍数余量 19x 而绝对量只有 0.375 GiB 可用。


def _pick_managed_target(res, t, req_vcpu, mem_fit, base, exclude=frozenset()):
    """从 `res["candidates"]` 各选一个非突发 / 突发目标。

    返回 dict：`nonburst` / `burst`（选中的候选或 None）、`cheaper_exists`
    （派生，取代采集侧同名布尔值）、`empty_reason`（两列都空时的成因）、
    `excluded_best`（因 `exclude` 被剔除的最便宜候选，供调用方量化放弃的金额）。

    `candidates` 缺失 ⇒ 返回 `None`，调用方走改动前的旧路径（读采集侧的
    `cheaper_candidate_exists` 布尔值、不出目标）。**不得 fail-closed** ——
    实测教训（真实机队回放）：旧契约缺必填字段时 86 条托管行全部
    fail-closed，比不升级更差。

    `mem_fit` 是各服务自己的内存条件（RDS 比 `gib`、ElastiCache 比扣掉
    reserved-memory-percent 之后的可用内存、MSK 无内存轴恒 True）。判据留在
    各 evaluator，本函数只做筛选与排序 —— 与 EC2 侧 `passes_common` / `pool`
    同一分工。
    """
    cands = res.get("candidates")
    if cands is None:
        return None
    cur_usd, cur_vcpu = res.get("cur_usd"), res.get("vcpu")
    if cur_usd is None or cur_vcpu is None:
        # candidates 存在却没有当前单价/核数：这是采集侧的契约违反，不是指标
        # 缺口。回退旧路径，避免拿不到基准价却"选出"一个目标。
        return None
    cur_arch = res.get("arch")
    cheaper = [c for c in cands if c["usd"] < cur_usd]
    out = {"nonburst": None, "burst": None, "cheaper_exists": bool(cheaper),
           "empty_reason": None, "excluded_best": None}
    if not cheaper:
        out["empty_reason"] = _EMPTY_NO_CHEAPER
        return out
    same_arch = [c for c in cheaper if c.get("arch") == cur_arch]
    if not same_arch:
        out["empty_reason"] = _EMPTY_CROSS_ARCH.format(
            types="、".join(f"{c['t']}({c.get('arch')})"
                            for c in sorted(cheaper, key=lambda c: c["usd"])))
        return out
    floor_vcpu = _ceil_div(cur_vcpu, t["max_reduction_ratio"])
    by_vcpu = [c for c in same_arch if c["vcpu"] >= max(req_vcpu, floor_vcpu)]
    if not by_vcpu:
        if not same_arch:
            out["empty_reason"] = _EMPTY_NO_CHEAPER
            return out
        best = max(same_arch, key=lambda c: c["vcpu"])
        # 两条成因必须分开：需求量超过候选（补容量规划无解）vs 降幅地板挡住
        # （策略选择，调 profile 即可）。读者的下一步动作不同。
        if req_vcpu > floor_vcpu:
            out["empty_reason"] = _EMPTY_VCPU.format(
                req=req_vcpu, best=best["t"], best_vcpu=best["vcpu"])
        else:
            out["empty_reason"] = _EMPTY_FLOOR.format(
                mrr=t["max_reduction_ratio"], floor=floor_vcpu)
        return out
    fitting = [c for c in by_vcpu if mem_fit(c)]
    if not fitting:
        out["empty_reason"] = _EMPTY_MEM.format(
            best=max(by_vcpu, key=lambda c: c["gib"])["t"])
        return out
    # `exclude` 在**适配筛选之后**才应用，且 `excluded_best` 只取「本来装得下、
    # 只因排除才没选中」的那一个。放在筛选之前会量化一笔本来也拿不到的钱：
    # 实测 req 1.765 GiB 时最便宜的被排除候选只有 1.0 GiB，压根装不下，
    # 报它的差价 $147.46 是误导；正确答案是下一档 2.0 GiB 的 $127.02。
    # （具体机型名不写在这里 —— 那份清单的唯一真值源是
    #   rds-pi-unsupported.json，见 load_pi_unsupported 的 docstring。）
    excl = [c for c in fitting if c["t"] in exclude]
    if excl:
        out["excluded_best"] = min(excl, key=lambda c: c["usd"])
    fitting = [c for c in fitting if c["t"] not in exclude]
    if not fitting:
        out["empty_reason"] = _EMPTY_EXCLUDED.format(
            best=out["excluded_best"]["t"])
        return out

    def _key(c):
        return (c["usd"], c["t"])

    nb = sorted((c for c in fitting if not c.get("burst")), key=_key)
    bu = sorted((c for c in fitting if c.get("burst")
                 and _managed_baseline(c["t"], base) is not None), key=_key)
    out["nonburst"] = nb[0] if nb else None
    out["burst"] = bu[0] if bu else None
    return out


def _cheaper_exists(res):
    """是否存在更便宜的同形态候选。

    `candidates` 存在时以派生值为准，消掉一个重复真值源；缺失才读采集侧的
    `cheaper_candidate_exists` 布尔值（向后兼容）。两者都缺 ⇒ None ⇒ 调用方
    fail-closed（不得假定存在）。
    """
    cands = res.get("candidates")
    if cands is not None and res.get("cur_usd") is not None:
        return any(c["usd"] < res["cur_usd"] for c in cands)
    return res.get("cheaper_candidate_exists")


def _managed_deep_note(out, res, pick, usable_ratio=1.0):
    """目标落在同架构阶梯最底部 ⇒ 强制 confidence=low 并写明绝对量风险。

    理由与「不用档数阈值」的取舍见上方 `_cheaper_exists` 之前那段注释。
    两列各自判：非突发列与突发列的阶梯不同，只有一列触底也要报。
    """
    ladder = sorted({c["usd"] for c in res["candidates"]
                     if c.get("arch") == res.get("arch")})
    if len(ladder) < 2:
        return
    for col, p in (("nonburst", pick["nonburst"]), ("burst", pick["burst"])):
        if p is None or p["usd"] != ladder[0]:
            continue
        out["confidence"] = "low"
        out.setdefault("blockers", []).append(
            f"{col} 目标 {p['t']} 是同架构价目阶梯的**最底档**"
            f"（可用内存 {round(p['gib'] * usable_ratio, 3)} GiB）——"
            f"倍数余量看着充足但绝对量极小，且触底后估错了没有退路"
            f"（不能再降，任何数据量增长只能升配）。须人工按业务增长预期复核")
        return


def _apply_managed_pick(out, res, pick, base):
    """把选中的两列与派生金额写进 `out`。

    `*_delta_vcpu` 用 `_eff_vcpu` 而不是标称核数，与 EC2 侧同口径 ——
    否则 `db.m6g.large` -> `db.t4g.large`（同为 2 vCPU）会算出 delta=0，
    看起来毫无意义。突发候选查不到 baseline 时已在 `_pick_managed_target`
    里被排除，所以这里不会拿到 None baseline 的突发目标。
    """
    cnt = res.get("count", 1)
    cur_usd, cur_gib = res["cur_usd"], res.get("mem_gib")
    cur_base = _managed_baseline(res["type"], base)
    eff_cur = res["vcpu"] * (cur_base if cur_base is not None else 1.0)
    for key, p in (("nb", pick["nonburst"]), ("b", pick["burst"])):
        if not p:
            out[f"{key}_save_mo"] = None
            continue
        out[f"{key}_save_mo"] = round(
            (cur_usd - p["usd"]) * HOURS_PER_MONTH * cnt, 2)
        pb = _managed_baseline(p["t"], base)
        out[f"{key}_delta_vcpu"] = round(
            eff_cur - p["vcpu"] * (pb if pb is not None else 1.0), 3)
        if cur_gib is not None:
            out[f"{key}_delta_gib"] = round(cur_gib - p["gib"], 3)
    out["nonburst"] = pick["nonburst"]
    out["burst"] = pick["burst"]


def _persistent(res, p95_key, max_key):
    """返回 (用于否决的持续值, 尖峰值)。

    否决项要判「持续成立」而不是「曾经出现过一次」。实测
    （某 ap-east-1 机队，8 个 MSK 集群）：UnderReplicatedPartitions
    Average 序列 p95 全为 0，而 max 达 27–244 —— MSK 自动打补丁做滚动重启，
    重启期间副本必然短暂落后。按 max 否决等于在任何被维护过的集群上
    永久关闭降配路径。ElastiCache 的 ReplicationLag 同形状
    （p95 0.001–0.005s，max 10.2s / 23.9s）。

    `*_p95` 缺失时回退到 `*_max`：采集侧未升级时行为与改动前完全相同
    （fail-closed 且向后兼容）。

    **这条否决的容忍度是 `agg.jq` 的 p95 定义带来的，不是一个可调阈值。**
    `agg.jq` 对**所有**指标统一用 `pct(0.95)`，所以「持续值未越界」实际含义是
    「窗口内不超过 `VETO_TOLERANCE_PCT`% 的时长处于该状态」——30 天窗口约 36 小时。
    这个数**不放进 thresholds.json**：那会假装它可以按 profile 调，而分位数写在
    `agg.jq` 里、对每个 p95 都一样，加键只会造出一个孤儿键式的假承诺
    （`tests/test_no_duplicated_constants.py` 正是为此存在）。
    它作为已知且被接受的限度写在常量与文档里；要真正收紧，需要采集侧提供
    「破损持续了多少个点」而不是一个分位数 —— 见 SKILL.md 易错项那一行。
    """
    p95 = res.get(p95_key)
    mx = res.get(max_key)
    return (mx if p95 is None else p95), mx


# 否决项判「持续成立」用的是 agg.jq 的 p95，所以容忍度就是 100 − 95。
# 不放进 thresholds.json 的理由见 _persistent 的 docstring。
VETO_TOLERANCE_PCT = 5

# CloudWatch Period=3600 除以 PI 的标称 1 分钟发布周期。
#
# 只用于 run 级注记：`mean(Maximum) > 60 x mean(Average)` 否证「按 1 分钟发布」
# 这个假设（60 个采样点下 max <= 60 x mean 是硬上界）。实测 12 台命中 9 台，
# 且全部 12 台与 1 秒粒度（3600 点/小时）自洽 —— 所以「PI 按 1 秒发布」与
# 「Average 被 SampleCount 稀释」两种解释与观测同样自洽，本 skill 判不了。
# **逐行 blocker 不用这个判别式**：它测的是全机队一致的发布语义，逐行报是噪声。
# 逐行用的是「峰值单独看是否翻转结论」，见 eval_rds 的 DBLoad 轴。
#
# 不进 thresholds.json：物理上界，不是可按 profile 调的策略量，
# 与 VETO_TOLERANCE_PCT 同类。
DBLOAD_MINUTE_SAMPLES = 60


def _spike_note(label, mx, cause):
    return (f"{label} 持续值未越界，但窗口内曾达 {mx}（单次尖峰，"
            f"常见成因：{cause}）。降配前确认该尖峰非容量不足所致；"
            f"本判据取 p95 为持续值，故窗口内最多 {VETO_TOLERANCE_PCT}% 的时长"
            f"处于该状态仍不否决")


def _coverage_note(out, res):
    """把「窗口内指标覆盖不齐」记成 blocker。**必须在任何早退分支之前调用。**

    整套判据的需求反推是 `required_vcpu = ceil(cur_vcpu x sus_cpu% / target)`
    —— 拿 describe 返回的**当前**规格去乘 CloudWatch 的**整窗口**利用率百分比。
    这个乘法只在「窗口内规格没变过」时成立，而本 skill 一处都没校验它。

    信号不需要新增采集：同一资源内某指标的点数明显低于该资源其他指标的点数，
    就说明它只在窗口的一段时间内存在。实测两台 db.m6g.xlarge 的
    CPUUtilization / DBLoad / FreeableMemory 都是 720/720，而
    CPUCreditBalance 只有 178/720，且信用余额上限 576 对应 2 vCPU 机型
    ⇒ 窗口内被放大过。

    **只标注、不改结论。** 判定偏差方向需要逐小时的规格历史：先小后大 ⇒
    混合 p95 虚高 ⇒ 低估节省（保守）；先大后小则相反，是危险方向。
    describe-* 只返回当前规格，CloudWatch 也没有「规格」这个维度，拿不到就不能算。

    放在最前面而不是各出口：早退路径（spec-unknown / metric-missing / excluded）
    上的行恰恰最需要解释「为什么数据看起来怪」。`_verdict()` 保证分支理由排在
    已追加的说明之前，所以先 append 再 `_verdict` 不会被覆盖。
    """
    gaps = res.get("partial_coverage")
    if not gaps:
        return
    detail = "、".join(f"{m} {n}/{exp}" for m, n, exp in gaps)
    out.setdefault("blockers", []).append(
        f"窗口内指标覆盖不齐（{detail}）：同资源的其他指标满覆盖，说明这些指标"
        f"只在窗口的一段时间里存在——常见成因是**窗口内改过规格**，"
        f"也可能是中途才开启的监控。此时本行的利用率百分比混合了两个规格的采样，"
        f"而需求量是按**当前**规格反推的，须人工确认窗口内规格未变。"
        f"本判据**不改结论**：判定偏差方向需要逐小时的规格历史，"
        f"describe-* 只返回当前规格，拿不到就不能算")


def _verdict(out, verdict, *reasons):
    """设置 verdict，并把分支理由排在**已追加**的说明之前。

    **不要写 `out.update(verdict=X, blockers=[...])`。** 那会覆盖此前
    append 进去的尖峰说明（「持续值未越界但曾达 N」），于是维护事件从报告里
    消失——而它恰恰是判据**刻意不否决**的那一类，读者必须看得到"我们看见了、
    并且判断它不构成阻断"。本文件已经在这个覆盖上踩过三次：
    downsize-candidate 出口、已合理配置出口、以及「没有更便宜候选」出口。
    统一走本函数，覆盖就不会再从任何一个新出口漏出去。
    """
    out["verdict"] = verdict
    out["blockers"] = list(reasons) + (out.get("blockers") or [])
    return out


def _rds_is_burstable(itype):
    """RDS 实例类是否 burstable。只有 db.t* 系列发布信用指标。

    非 burstable（db.m*/db.r*/db.x* 等）结构性不发布 CPUCreditBalance 与
    CPUSurplusCreditsCharged —— 实测 db.m5.large 三条序列全空，同批
    db.t4g.medium 都有数据。对它们要求信用指标会让降配路径永久不可达，
    这是「不适用」而不是「缺失」，所以不走 fail-closed。
    EC2 侧的 evaluate() 用 cs["burst"] 做同一个区分。注意：2026-09-04 记录
    J2 时曾断言「EC2 侧已做了这个区分」，那句话当时并不成立 —— EC2 侧同样
    无条件 fail-closed，直到 2026-09-10 才补上。别再凭这类断言跳过复查。
    """
    return itype.split(".")[1].startswith("t") if "." in itype else False


def eval_rds(res, t, base=None):
    """RDS 判据。DBLoad 与 CPUUtilization 是**并行两轴**，不是主备。

    实测教训（保留）：某 db.t4g.medium 的 DBLoad p95 = 0.547 < 0.5x2vCPU
    ⇒ 前置"满足"，但 CPUSurplusCreditsCharged 单小时最大 730.6、
    CPUCreditBalance 最小值 0 ⇒ 规格已不足。故信用超额是**独立否决项**。

    本轮新增的两个 upsize 出口（CPU 持续项超当前规格、FreeableMemory 越地板）
    与那条同类：它们说的是「这台机器已经不够用」，必须排在候选池判定之前 ——
    候选集为空不该压掉这条警告。分支顺序见
    docs/specs/2026-09-13-managed-target-selection-design.md 的 C5。

    峰值项取 `peak_cpu_p95`（`Maximum` 序列的 p95），**不是 max**。
    RDS 的 CPU 尖峰可证明来自托管平面的维护动作（备份窗口、自动小版本升级）：
    实测一台常态 4.00% 的库单峰 88.33%，按 max 反推需 3 vCPU 而它只有 2。
    与 MSK 的 UnderReplicatedPartitions、Redis 的 ReplicationLag 同类，
    故走 `_persistent()` 的口径。**EC2 侧 `peak_cpu` 保持取 max 不动** ——
    那里的尖峰是真实业务负载，`_required` 的注释已论证「峰值项不可省」。
    """
    out = {"rid": res["rid"], "service": "rds", "cur": res["type"],
           "blockers": [], "nonburst": None, "burst": None,
           "required_vcpu": None, "required_gib": None}
    _coverage_note(out, res)
    if res["type"] == "db.serverless":
        _verdict(out, "excluded",
                 "Aurora Serverless v2 按 ACU 伸缩，无固定规格")
        return out
    vcpu = res.get("vcpu")
    if vcpu is None:
        _verdict(out, "spec-unknown",
                 "实例类 vCPU 未知（映射失败且兜底表无此项）")
        return out
    # 否决项优先，且缺失一律 fail-closed —— 但只对 burstable 实例类成立
    burstable = _rds_is_burstable(res["type"])
    sc = res.get("surplus_credits")
    if sc is not None and sc > 0:
        _verdict(out, "upsize-candidate",
                 f"CPUSurplusCreditsCharged={sc} > 0，规格已不足，是升配候选")
        return out
    cb_min, cb_max = res.get("credit_balance_min"), res.get("credit_balance_max")
    if not burstable:
        if cb_min is not None:
            out["blockers"].append(CLASS_CHANGED_NOTE)
    elif (cb_min is not None and cb_max is not None
          and _credit_exhausted(cb_min, cb_max, t)):
        _verdict(out, "upsize-candidate",
                 f"CPU 信用余额窗口内触底（最小 {cb_min} / 窗口内最大 {cb_max}，"
                 f"门限 {t['credit_balance_floor_pct']}%），规格已不足，是升配候选")
        return out

    # ---- CPU 轴。与 DBLoad 并行，任一可用即可评估 ----
    sus_cpu, peak_cpu = res.get("sus_cpu"), res.get("peak_cpu_p95")
    dbload = res.get("dbload_p95")
    if sus_cpu is None and dbload is None:
        _verdict(out, "metric-missing",
                 "DBLoad 与 CPUUtilization 两轴都缺，无从反推需求量")
        return out
    rv_cpu = rv_cpu_sus = None
    if sus_cpu is not None:
        rv_cpu_sus = _ceil_div(vcpu * sus_cpu, t["target_cpu_p95"])
        # peak 缺失 ⇒ 只用持续项并写明。不当 0（那是替实例做假设），
        # 也不 fail-closed（另一轴可能可用，且持续项本身已有意义）。
        rv_cpu = (max(rv_cpu_sus,
                      _ceil_div(vcpu * peak_cpu, t["ceiling_cpu_max"]))
                  if peak_cpu is not None else rv_cpu_sus)
        if peak_cpu is None:
            out["blockers"].append(
                "CPUUtilization Maximum 序列缺失，CPU 轴只用持续项 —— "
                "降配后峰值是否越 ceiling 未校验")
    # 只按**持续项**判规格不足。峰值项是为降配方向设计的安全约束，
    # 拿它反推「当前规格不足」会把闲置小机器判成不足
    # （2026-09-10-ec2-underprovisioned-verdict-design.md 的裁定）。
    if rv_cpu_sus is not None and rv_cpu_sus > vcpu:
        _verdict(out, "upsize-candidate",
                 f"CPU 持续 p95 {sus_cpu}% ⇒ 按目标 {t['target_cpu_p95']}% "
                 f"反推需 {rv_cpu_sus} vCPU，当前仅 {_n(vcpu)}。"
                 f"本 skill 不产出升配目标机型——选型需容量规划输入"
                 f"（增长率 / SLA / 峰值形态）")
        return out

    # ---- DBLoad 轴 ----
    rv_dbload = None
    if dbload is None:
        out["blockers"].append(
            f"该实例类结构性不支持 Performance Insights"
            f"（{res['type']} 在 rds-pi-unsupported.json 列表内），"
            f"DBLoad 不可得 ⇒ 本行只用 CPUUtilization 轴。"
            f"换用支持 PI 的实例类才能拿到第一判据"
            if res["type"] in load_pi_unsupported() else
            "Performance Insights 未开启，DBLoad 不可得 ⇒ 本行只用 "
            "CPUUtilization 轴。开启后重采即可得第一判据")
    else:
        if dbload >= vcpu:
            _verdict(out, "blocked",
                     f"DBLoad p95 {dbload} >= vCPU {_n(vcpu)}，CPU 已是瓶颈")
            return out
        if dbload >= t["rds_dbload_ratio"] * vcpu:
            _verdict(out, "已合理配置",
                     f"DBLoad p95 {dbload} 未低于 {t['rds_dbload_ratio']}x"
                     f"vCPU({t['rds_dbload_ratio'] * vcpu})")
            return out
        rv_dbload = max(1, _ceil_div(dbload, t["rds_dbload_ratio"]))
        # 峰值单独看就会翻转结论 ⇒ 报出来但**不改 verdict**。
        # 哪条序列代表真实负载取决于 PI 的发布语义（见 DBLOAD_MINUTE_SAMPLES
        # 的注释：1 秒粒度 vs SampleCount 稀释，两种解释与观测同样自洽），
        # 本 skill 拿不到，拿不到就不能算。与 _coverage_note() 同一条纪律。
        #
        # 输入取 Maximum 序列的 **p95** 而不是 max —— 按单次尖峰否决正是
        # _persistent() 明令反对的。
        dbl_max = res.get("dbload_max_p95")
        if dbl_max is not None and dbl_max / t["rds_dbload_ratio"] > vcpu:
            out["confidence"] = "low"
            out["blockers"].append(
                f"DBLoad 两条序列跨度极大：Average p95 {dbload} 判为可降，而 "
                f"Maximum 序列 p95 {dbl_max} 单独反推需 "
                f"{max(1, _ceil_div(dbl_max, t['rds_dbload_ratio']))} vCPU"
                f"（当前 {_n(vcpu)}）。降配前须在 Performance Insights 控制台核对 "
                f"Average Active Sessions 实际曲线 —— 本 skill 无法判定 Average "
                f"是细粒度均值还是被 SampleCount 稀释，两者与观测同样自洽")

    # ---- 候选池可行性探针。**必须早于所有剩余的 fail-closed** ----
    # 结构性不可能的两种情形（没有更便宜的候选、更便宜的全部跨架构）与任何
    # 指标无关，先判掉。否则会让客户为一条**不可能产出**的建议去开 PI、
    # 补 FreeableMemory、再等一个完整窗口。
    # 这是本函数原有的裁定（`cheaper` 短路早于所有前置指标要求），本轮只是把
    # 它从一个采集侧布尔值换成带成因的探针 —— 顺序不变。
    probe = _pick_managed_target(res, t, 1, lambda c: True, base or {})
    if probe is None:
        cheaper = res.get("cheaper_candidate_exists")
        if cheaper is None:
            _verdict(out, "metric-missing",
                     "cheaper_candidate_exists 缺失，无法确认是否存在"
                     "更便宜的同形态候选（不得假定存在）")
            return out
        if not cheaper:
            _verdict(out, "已合理配置", _EMPTY_NO_CHEAPER)
            return out
    elif probe["empty_reason"]:
        _verdict(out, "已合理配置", probe["empty_reason"],
                 "本行未评估内存压力（FreeableMemory 阻断在候选集为空时不再计算）"
                 "——「已合理配置」说的是没有可降的目标，不是这台机器健康")
        return out

    # ---- FreeStorageSpace：容量耐久度 ----
    # 采集侧从一开始就采了它（含 Minimum 统计），agg.jq 也聚合了，而
    # core.py / report-template.md / sample-solve.md 一次都没提 ——
    # `grep -rn FreeStorageSpace references/` 在本轮之前返回空。
    #
    # 这条与 rightsizing 的命题确实不同（可用性事故，不是成本项），但采集成本
    # 已经付了，且它的严重度高于本 skill 的全部节省项。
    #
    # 位置：候选池探针**之后**（候选集为空时它同样属于"补了也产不出建议"），
    # 但在信用与 FreeableMemory 两条之**前**。实测回放暴露过反例：
    # 磁盘写满那台（Minimum 最小值 0 GiB）先撞上 FreeableMemory 的 OOM 阻断，
    # 于是报告只写「降配会 OOM」，磁盘被写满这件事从不出现 —— 而按本条自己的
    # 措辞它「优先级高于本行任何降配讨论」。
    st_min = res.get("storage_free_min_gib")
    st_first, st_last = (res.get("storage_free_first_gib"),
                         res.get("storage_free_last_gib"))
    if st_min is None:
        out["blockers"].append(
            "FreeStorageSpace 缺失，未评估容量耐久度（该指标对所有引擎都发布，"
            "缺失是采集缺口而非不适用）")
    elif st_min == 0:
        _verdict(out, "blocked",
                 "FreeStorageSpace 最小值 = 0 GiB ⇒ 窗口内存储被耗尽过。"
                 "**这是可用性事故，不是成本项**，优先级高于本行任何降配讨论。"
                 "先查 binlog / 事务日志保留与大临时表，并开启 storage "
                 "autoscaling；处理完再重采评估降配")
        return out
    elif st_first is not None and st_last is not None:
        # 速率用 Average 序列首尾差，**不用 Minimum** —— Minimum 含 binlog
        # 轮转造成的锯齿，会把速率算成负数或虚高。
        days = res.get("window_days") or 30
        rate = (st_first - st_last) / days
        if rate > 0:
            runway = st_last / rate
            if runway < t["rds_storage_days_floor"]:
                _verdict(out, "blocked",
                         f"按窗口内消耗速率 {round(rate, 3)} GiB/日外推，剩余 "
                         f"{round(runway, 1)} 天触顶（门限 "
                         f"{t['rds_storage_days_floor']} 天）⇒ 先开启 storage "
                         f"autoscaling 再谈降配。存储只能扩不能缩，"
                         f"降实例类不改变这条")
                return out

    if burstable and sc is None:
        _verdict(out, "metric-missing",
                 "CPUSurplusCreditsCharged 缺失，无法排除信用已超额")
        return out
    if burstable and (cb_min is None or cb_max is None):
        _verdict(out, "metric-missing",
                 "CPUCreditBalance 缺失，无法排除信用已耗尽")
        return out

    # ---- FreeableMemory：OOM 阻断 ----
    # **判 `blocked` 而不是 `upsize-candidate`。** 本轮 spec 曾提议升级它，
    # 而既有守卫测试（test_managed_vetoes_actually_fire_and_block）反对，
    # 且它是对的：数据库引擎的缓冲区（MySQL `innodb_buffer_pool_size`、
    # PostgreSQL `shared_buffers` 加 OS page cache）有意占满可分配内存，
    # `FreeableMemory` 报的是 MemAvailable —— 一个 buffer pool 配置正确的库
    # **按设计**就是低 freeable。实测一台可用内存剩 9.7%，但 DBLoad p95
    # 1.211（8 vCPU）、CPU 14.87%，完全不缺算力。这条证据支持"缩不了"，
    # 不支持"需要更大的实例"。欠配的判定交给 CPU 持续项那条出口。
    freeable_min, mem_gib = res.get("freeable_mem_min_gib"), res.get("mem_gib")
    if freeable_min is None or mem_gib is None:
        _verdict(out, "metric-missing",
                 "FreeableMemory 或实例内存未知，无法判断降配是否 OOM")
        return out
    floor_gib = (t["rds_freeable_mem_floor_pct"] / 100) * mem_gib
    if freeable_min < floor_gib:
        _verdict(out, "blocked",
                 f"FreeableMemory 最小值 {freeable_min} GiB < 实例内存 "
                 f"{t['rds_freeable_mem_floor_pct']}%"
                 f"（{round(floor_gib, 3)} GiB），降配会 OOM。"
                 f"注意这条说的是**缩不了**，不是规格不足 —— buffer pool "
                 f"会占满可分配内存，低 freeable 对配置正确的库是常态")
        return out

    req_vcpu = max(x for x in (rv_cpu, rv_dbload, 1) if x is not None)
    # 内存需求按 FreeableMemory 反推，留与 OOM 否决同一道地板的余量 ——
    # 一个候选"装得下"的定义就是"降配后 FreeableMemory 仍高于那道地板"，
    # 故不再叠加额外余量。
    #
    # 已知局限（写进 blocker）：数据库引擎的缓冲区会占满可分配内存，
    # 所以 mem_gib − freeable_min 是真实工作集的**上界**。方向保守
    # （不会推荐过小的机型），代价是系统性少省。要修需要引擎内部的缓冲池
    # 命中率/驻留页计数器，CloudWatch 不发布。
    #
    # **文案必须引擎中立。** 第二支机队实测抓到：一台 PostgreSQL 被告知去调
    # `innodb_buffer_pool_size`，而 InnoDB 是 MySQL 专有。RDS 行不带 engine
    # 字段，所以不猜引擎，两个参数名都列出来。
    req_gib = round((mem_gib - freeable_min)
                    / (1 - t["rds_freeable_mem_floor_pct"] / 100), 3)
    out.update(required_vcpu=req_vcpu, required_gib=req_gib)

    exclude = load_pi_unsupported() if res.get("pi_enabled") else frozenset()
    pick = _pick_managed_target(res, t, req_vcpu, lambda c: c["gib"] >= req_gib,
                                base or {}, exclude=exclude)
    if pick is None:
        # 采集侧未升级（无 candidates）：可行性已由上面的探针按布尔值判过，
        # 到这里说明"存在更便宜的候选"，逐字保持改动前行为。
        _verdict(out, "downsize-candidate",
                 "需变更窗口 + 回滚预案；存储不可缩容，过度预配只能 next-rebuild",
                 _FIT_UNVERIFIED)
        return out
    if pick["excluded_best"]:
        eb = pick["excluded_best"]
        forgone = round((res["cur_usd"] - eb["usd"]) * HOURS_PER_MONTH
                        * res.get("count", 1), 2)
        out["blockers"].append(
            f"更便宜的 {eb['t']} 已排除：该实例类不支持 Performance Insights，"
            f"而 DBLoad 是本判据的第一依据。若业务接受丢失 PI，可额外省 "
            f"${forgone}/mo，但下一轮本行的 DBLoad 轴将不可得")
    if pick["empty_reason"]:
        _verdict(out, "已合理配置", pick["empty_reason"])
        return out
    _apply_managed_pick(out, res, pick, base or {})
    _managed_deep_note(out, res, pick)
    _verdict(out, "downsize-candidate",
             f"目标实例类为本 skill 初选（需 {req_vcpu} vCPU / {req_gib} GiB，"
             f"后者按 FreeableMemory 最小值反推并留 "
             f"{t['rds_freeable_mem_floor_pct']}% 余量），"
             f"须人工确认变更窗口与回滚预案",
             "存储不可缩容，过度预配只能 next-rebuild",
             "内存需求由 FreeableMemory 反推，而数据库引擎的缓冲区会占满"
             "可分配内存 ⇒ 该值是真实工作集的**上界**，方向保守但会系统性少省。"
             "若变更时同步下调缓冲区参数（MySQL `innodb_buffer_pool_size` / "
             "PostgreSQL `shared_buffers`），可选更小的实例类")
    return out


# 判据侧唯一的引擎白名单：这两个引擎是单线程、发布 EngineCPUUtilization 与
# DatabaseMemoryUsagePercentage。Memcached 多线程、两个都不发布，本版本不评估
# （它的 CPU 用 CPUUtilization、内存用 BytesUsedForCache 对上限，都**未实测**，
# 发明一套未验证的判据比诚实排除更糟）。改这个集合前先实测新引擎的指标与刻度。
EC_ENGINES_WITH_ENGINE_CPU = frozenset({"redis", "valkey"})


def eval_elasticache(res, t, base=None):
    """ElastiCache 判据。内存必须用 pricing 的 memory，且要扣 reserved-memory-percent。

    实测：cache.t3.medium 真实 3.09 GiB，映射到 EC2 t3.medium 得 4.00 GiB，偏 +29%。
    DatabaseMemoryUsagePercentage 是相对真实节点内存的百分比，基数错则绝对量错。
    """
    out = {"rid": res["rid"], "service": "elasticache", "cur": res["type"],
           "blockers": [], "nonburst": None, "burst": None,
           "required_vcpu": None, "required_gib": None}
    _coverage_note(out, res)
    if res.get("mem_gib") is None or res.get("vcpu") is None:
        _verdict(out, "spec-unknown",
                 "pricing 的 vcpu/memory 属性为 null（实测 88 个 node type 中 33 个如此），"
                             "不得外推、不得回退 EC2 映射值")
        return out
    ev_persist, ev_max = _persistent(res, "evictions_p95", "evictions_sum")
    if ev_persist is None:
        _verdict(out, "metric-missing",
                 "Evictions 缺失")
        return out
    if ev_persist > 0:
        _verdict(out, "blocked",
                 f"Evictions 持续值 {ev_persist} > 0"
                 + (f"（窗口内最大 {ev_max}）" if ev_max is not None else "")
                 + "，内存已不足，降配更糟")
        return out
    if ev_max is not None and ev_max > 0:
        out["blockers"].append(_spike_note("Evictions", ev_max,
                                           "短时热点 / 批量写入"))
    # Evictions 的 fail-closed（上面）与 ReplicationLag 的分流（下面）**不对称是
    # 有依据的**，不是漏改：Evictions 每个节点都发布，缺失是真缺失；
    # ReplicationLag 只在存在副本时才有意义，缺失可能是「不适用」。
    # 但放行必须有依据——无条件放行会让这条否决项在一个真实复制组上静默消失。
    # 不用 count 做代理：`3 分片 x 1 节点`（count=3、无副本）是合法配置。
    has_replica = res.get("has_replica")
    lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
    if has_replica is None:
        _verdict(out, "metric-missing",
                 "has_replica 缺失，无法区分「无副本故不适用」与「采集失败」")
        return out
    if has_replica and lag_persist is None:
        _verdict(out, "metric-missing",
                 "存在副本却无 ReplicationLag 序列 ⇒ 采集缺口，"
                 "不得按「无副本」放行")
        return out
    if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:
        _verdict(out, "blocked",
                 f"ReplicationLag 持续值 {lag_persist}s >= "
                 f"{t['redis_repl_lag_max_s']}s"
                 + (f"（窗口内最大 {lag_max}s）" if lag_max is not None else ""))
        return out
    if lag_max is not None and lag_max >= t["redis_repl_lag_max_s"]:
        out["blockers"].append(_spike_note("ReplicationLag", f"{lag_max}s",
                                           "failover / 备份快照"))
    # 引擎分流放在两条否决项**之后**：Evictions 与 ReplicationLag 对 Memcached
    # 同样成立（都会淘汰键；无副本则由 has_replica 放行），「这个缓存正在淘汰键」
    # 是有效阻断，与能不能降配无关。放在 cheaper 短路**之前**：excluded 是
    # 「本版本不评估」，比「没有更便宜候选」靠前——后者暗示已经评估过了。
    engine = res.get("engine")
    if engine is None:
        _verdict(out, "metric-missing",
                 "engine 缺失，无法判定 EngineCPUUtilization / "
                 "DatabaseMemoryUsagePercentage 是否适用（不得假定 Redis）")
        return out
    if engine not in EC_ENGINES_WITH_ENGINE_CPU:
        _verdict(out, "excluded",
                 f"引擎 {engine} 不在本版本的评估范围内："
                 f"两个主判据指标（EngineCPUUtilization / "
                 f"DatabaseMemoryUsagePercentage）只有 "
                 f"{'/'.join(sorted(EC_ENGINES_WITH_ENGINE_CPU))} 发布。"
                 f"该引擎需另一套判据（Memcached 多线程，CPU 看 CPUUtilization、"
                 f"内存看 BytesUsedForCache 对节点上限），本 skill **未实测**"
                 f"那套指标的刻度与维度集，故不产出结论而非猜一个")
        return out
    # 候选集为空 ⇒ 直接已合理配置,且早于所有前置指标要求。
    # 否则会让客户为一条不可能产出的建议去补指标、再等一个窗口。
    #
    # 本函数的实测依据是 **ElastiCache 侧的**（此前这里逐字抄了 eval_msk 的
    # kafka.t3.small 证据，拿 MSK 的价目阶梯给 ElastiCache 判据作证）：
    # 实测 us-west-2 Redis 的最便宜 node type 是 cache.t4g.micro $0.016/hr，
    # 而验证 region 里那个单节点集群用的正是它 —— 已经踩在地板上。
    # 与 MSK 不同的是这条阶梯在底部很密（次便宜 cache.t2.micro $0.017/hr，
    # 仅 1.06 倍，且跨 CPU 架构本 skill 不允许），**不要把 MSK 的 4.5 倍
    # 断崖套到这里**：ElastiCache 只有在绝对地板上才会命中本分支。
    cheaper = _cheaper_exists(res)
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        _verdict(out, "已合理配置", _EMPTY_NO_CHEAPER)
        return out
    # ---- 候选池可行性探针。**必须早于所有 metric fail-closed** ----
    # 结构性不可能的两种情形（没有更便宜的候选、更便宜的全部跨架构）与任何
    # 指标无关，先判掉。实测回放：两个 kafka.m7g.large 集群的
    # RequestHandlerAvgIdlePercent 因 EnhancedMonitoring=DEFAULT 而缺失，
    # 若先判缺失，报告会写「缺 RequestHandlerAvgIdlePercent」——
    # 于客户看来是「去开 enhanced monitoring 就能拿到建议」，
    # 而唯一更便宜的机型跨架构、建议根本不可能产出。
    probe = _pick_managed_target(res, t, 1, lambda c: True, base or {})
    if probe is not None and probe["empty_reason"]:
        _verdict(out, "已合理配置", probe["empty_reason"])
        return out

    cpu = res.get("engine_cpu_p95")
    if cpu is None:
        _verdict(out, "metric-missing",
                 "EngineCPUUtilization 缺失。注意不可用 CPUUtilization 替代——"
                             "Redis 单线程，整机 CPU 含后台线程，会系统性误判")
        return out
    memp = res.get("db_mem_used_pct_max")
    if memp is None:
        _verdict(out, "metric-missing",
                 "DatabaseMemoryUsagePercentage 缺失")
        return out
    # reserved-memory-percent 是集群参数（不是指标），有 AWS 文档默认值，
    # 默认值只能来自 thresholds.json——写死在这里就等于第二个真值源。
    reserved = res.get("reserved_memory_pct")
    if reserved is None:
        reserved = t["reserved_memory_pct_default"]
    reserved /= 100.0
    # DatabaseMemoryUsagePercentage 是 maxmemory（即可用内存 = 节点内存 ×
    # (1-reserved)）的百分比，不是节点内存的百分比。故已用可用内存 =
    # 节点内存 × (1-reserved) × memp/100。原式尾部再除 (1-reserved) 会
    # 与前项相消，得到的其实是节点总内存口径，与键名 usable 矛盾。
    out["required_gib_usable"] = round(res["mem_gib"] * (1 - reserved) * memp / 100.0, 3)
    if cpu >= t["target_cpu_p95"] or memp >= t["target_mem_p95"]:
        _verdict(out, "已合理配置",
                 f"EngineCPU p95 {cpu}% / 内存 max {memp}% 未低于目标")
        return out
    # 候选须满足的可用内存下限：把已用量按 target_mem_p95 反推，
    # 即「降配后内存利用率不超过本 profile 声明的目标」。形式与 EC2 侧
    # `_required` 的内存项逐字一致（`ceil(cur_gib * sus_mem / target_mem_p95)`），
    # 不新增阈值。
    #
    # **不用 max_mem_reduction_ratio。** 那道地板在这条阶梯上结构性不可满足：
    # ElastiCache 的节点内存不是 2 的幂（0.50 / 1.37 / 3.09 / 6.38 GiB，
    # 相邻比值 2.74 / 2.26 / 2.07 全部 > 2），conservative 的
    # max_mem_reduction_ratio=2 从 cache.m6g.large 往下要求候选 >= 3.19 GiB，
    # 而下一档只有 3.09 GiB —— 差 3%，永久挡死。实测按比值地板筛，
    # conservative 下 11 个复制组全部选不出目标、合计 $0，且失败原因会被写成
    # 「装不下」而真正的约束是降幅地板，诊断信息指向错误方向。
    #
    # 那道地板的立论（`mem_used_percent` 不含可回收 page cache、会压低内存 p95）
    # 在这里也不成立 —— DatabaseMemoryUsagePercentage 是相对 maxmemory 的
    # 权威利用率，没有那个盲区，所以可以直接用利用率目标表达。
    req = round(out["required_gib_usable"] / (t["target_mem_p95"] / 100.0), 3)
    pick = _pick_managed_target(
        res, t,
        req_vcpu=max(1, _ceil_div(res["vcpu"] * cpu, t["target_cpu_p95"])),
        mem_fit=lambda c: c["gib"] * (1 - reserved) >= req,
        base=base or {})
    if pick is None:
        # 采集侧未升级（无 candidates）：逐字保持改动前行为
        return _verdict(
            out, "downsize-candidate",
            f"候选 node type 扣掉 reserved-memory-percent "
            f"{reserved * 100:.0f}% 后的可用内存须 >= {req} GiB"
            f"（当前已用可用内存 {out['required_gib_usable']} GiB 按目标利用率 "
            f"{t['target_mem_p95']}% 反推）",
            "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）",
            _FIT_UNVERIFIED)
    if pick["empty_reason"]:
        _verdict(out, "已合理配置", pick["empty_reason"])
        return out
    _apply_managed_pick(out, res, pick, base or {})
    _managed_deep_note(out, res, pick, usable_ratio=1 - reserved)
    return _verdict(
        out, "downsize-candidate",
        f"目标 node type 为本 skill 初选：扣掉 reserved-memory-percent "
        f"{reserved * 100:.0f}% 后的可用内存须 >= {req} GiB"
        f"（当前已用可用内存 {out['required_gib_usable']} GiB 按目标利用率 "
        f"{t['target_mem_p95']}% 反推）。须人工确认变更窗口与回滚预案",
        "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）")


def eval_msk(res, t, base=None):
    """MSK 判据。CPU 用 metric math 的 CpuUser+CpuSystem 逐点相加。

    刻度陷阱（同 namespace 内不统一，实测）：
        KafkaDataLogsDiskUsed        0-100
        RequestHandlerAvgIdlePercent 0-1     ← 判据写 >70% 会永不成立
    """
    out = {"rid": res["rid"], "service": "msk", "cur": res["type"],
           "blockers": [], "nonburst": None, "burst": None,
           "required_vcpu": None, "required_gib": None}
    _coverage_note(out, res)
    urp_persist, urp_max = _persistent(res, "under_replicated_p95",
                                       "under_replicated_max")
    if urp_persist is None:
        _verdict(out, "metric-missing",
                 "UnderReplicatedPartitions 缺失。**不要因此去提 EnhancedMonitoring**——实测 DEFAULT 档该指标 per-broker 就有（见 metrics-catalog.md）；缺失另有原因，先查维度值与集群状态")
        return out
    if urp_persist > 0:
        _verdict(out, "blocked",
                 f"UnderReplicatedPartitions 持续值 {urp_persist} > 0"
                 + (f"（窗口内最大 {urp_max}）" if urp_max is not None else ""))
        return out
    if urp_max is not None and urp_max > 0:
        out["blockers"].append(_spike_note("UnderReplicatedPartitions", urp_max,
                                           "broker 滚动重启 / 自动打补丁"))
    # 候选集为空 ⇒ 直接已合理配置，且早于所有前置指标要求。
    # 否则会让客户为一条不可能产出的建议去补指标、再等一个窗口。
    # 实测：kafka.t3.small 是两 region 最便宜的 broker 机型，次便宜的贵约 4.5 倍。
    cheaper = _cheaper_exists(res)
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        _verdict(out, "已合理配置", _EMPTY_NO_CHEAPER)
        return out
    # ---- 候选池可行性探针。**必须早于所有 metric fail-closed** ----
    # 结构性不可能的两种情形（没有更便宜的候选、更便宜的全部跨架构）与任何
    # 指标无关，先判掉。实测回放：两个 kafka.m7g.large 集群的
    # RequestHandlerAvgIdlePercent 因 EnhancedMonitoring=DEFAULT 而缺失，
    # 若先判缺失，报告会写「缺 RequestHandlerAvgIdlePercent」——
    # 于客户看来是「去开 enhanced monitoring 就能拿到建议」，
    # 而唯一更便宜的机型跨架构、建议根本不可能产出。
    probe = _pick_managed_target(res, t, 1, lambda c: True, base or {})
    if probe is not None and probe["empty_reason"]:
        _verdict(out, "已合理配置", probe["empty_reason"])
        return out

    disk, idle, cpu = (res.get("disk_used_max"), res.get("handler_idle_p95"),
                       res.get("cpu_total_p95"))
    if None in (disk, idle, cpu):
        miss = [k for k, v in (("KafkaDataLogsDiskUsed", disk),
                               ("RequestHandlerAvgIdlePercent", idle),
                               ("CpuUser+CpuSystem", cpu)) if v is None]
        _verdict(out, "metric-missing",
                 f"缺失: {', '.join(miss)}")
        return out
    if disk >= t["msk_disk_used_max"]:                      # 0-100 刻度
        _verdict(out, "已合理配置",
                 f"KafkaDataLogsDiskUsed max {disk} >= {t['msk_disk_used_max']}")
        return out
    if idle <= t["msk_handler_idle_min"]:                    # 0-1 刻度，不是 70
        _verdict(out, "已合理配置",
                 f"RequestHandlerAvgIdlePercent p95 {idle} <= {t['msk_handler_idle_min']}（0-1 刻度）")
        return out
    if cpu >= t["msk_target_cpu_p95"]:
        _verdict(out, "已合理配置",
                 f"CpuUser+CpuSystem p95 {cpu}% >= {t['msk_target_cpu_p95']}%")
        return out
    # MSK 无内存轴：AWS/Kafka 不发布 broker 内存利用率。存储也不参与候选筛选
    # —— 卷大小与 broker 机型无关，msk_disk_used_max 是上面那条独立的
    # 「已合理配置」出口，不是候选约束。
    req_vcpu = max(1, _ceil_div(res["vcpu"] * cpu, t["msk_target_cpu_p95"])) \
        if res.get("vcpu") else 1
    pick = _pick_managed_target(res, t, req_vcpu, lambda c: True, base or {})
    if pick is None:
        # 采集侧未升级（无 candidates）：逐字保持改动前行为
        return _verdict(
            out, "downsize-candidate",
            "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
            "不产出减 broker 数建议（需 partition 重分配，属架构级）",
            _FIT_UNVERIFIED)
    if pick["empty_reason"]:
        _verdict(out, "已合理配置", pick["empty_reason"])
        return out
    out["required_vcpu"] = req_vcpu
    _apply_managed_pick(out, res, pick, base or {})
    _managed_deep_note(out, res, pick)
    return _verdict(
        out, "downsize-candidate",
        f"目标 broker 机型为本 skill 初选（CpuUser+CpuSystem p95 {cpu}% ⇒ "
        f"按目标 {t['msk_target_cpu_p95']}% 反推需 {req_vcpu} vCPU），"
        f"须人工确认变更窗口与回滚预案",
        "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
        "不产出减 broker 数建议（需 partition 重分配，属架构级）")


# ============================================================
# EKS：requests 计算与预订率
# ============================================================

def _cpu_cores(v):
    """K8s CPU 量转核数。None 按 0 计——未声明 request 是真实调度行为，不是缺失数据。"""
    if v is None:
        return 0.0
    v = str(v)
    return float(v[:-1]) / 1000 if v.endswith("m") else float(v)


def _mem_gib(v):
    if v is None:
        return 0.0
    v = str(v)
    for suf, div in (("Ki", 1048576), ("Mi", 1024), ("Gi", 1), ("Ti", 1 / 1024)):
        if v.endswith(suf):
            return float(v[:-2]) / div
    return float(v) / (1024 ** 3)


def pod_requests(pod):
    """返回 (cpu_cores, mem_gib)，遵循 K8s 实际调度算法。

    调度用量 = max(Σ 普通容器, 各 init 容器的最大值) + pod overhead

    init 容器顺序执行且先于普通容器完成，故不与普通容器叠加；但单个 init
    容器可能比普通容器之和更大，那时以它为准。overhead 是 RuntimeClass 的
    固定开销，恒叠加。

    漏算这两项会**低估 requests**，而预订率是 EKS 分析的核心结论
    （且它不依赖 Container Insights），低估会直接得出错误的机型建议。
    """
    spec = pod.get("spec") or {}
    def req(c, key):
        return ((c.get("resources") or {}).get("requests") or {}).get(key)
    regular_cpu = sum(_cpu_cores(req(c, "cpu")) for c in spec.get("containers") or [])
    regular_mem = sum(_mem_gib(req(c, "memory")) for c in spec.get("containers") or [])
    init_cpu = max((_cpu_cores(req(c, "cpu")) for c in spec.get("initContainers") or []),
                   default=0.0)
    init_mem = max((_mem_gib(req(c, "memory")) for c in spec.get("initContainers") or []),
                   default=0.0)
    oh = spec.get("overhead") or {}
    return (max(regular_cpu, init_cpu) + _cpu_cores(oh.get("cpu")),
            max(regular_mem, init_mem) + _mem_gib(oh.get("memory")))


def booking_rates(clusters):
    """逐集群算预订率。**不得跨集群汇总**——不同集群的节点池互不调度，
    混算会掩盖单个集群的错配。"""
    out = {}
    for c in clusters:
        ac = sum(_cpu_cores((n.get("allocatable") or {}).get("cpu")) for n in c.get("nodes") or [])
        am = sum(_mem_gib((n.get("allocatable") or {}).get("memory")) for n in c.get("nodes") or [])
        rc = rm = 0.0
        for p in c.get("pods") or []:
            pc, pm = pod_requests(p)
            rc += pc
            rm += pm
        out[c["name"]] = {
            "alloc_cpu": round(ac, 3), "alloc_gib": round(am, 3),
            "req_cpu": round(rc, 3), "req_gib": round(rm, 3),
            "cpu_pct": round(rc / ac * 100, 1) if ac else None,
            "mem_pct": round(rm / am * 100, 1) if am else None,
            "pods": len(c.get("pods") or []),
        }
    return out


# ============================================================
# 分派：service → 判据
# ============================================================
# 托管服务判据的签名是 (res, thresholds)，EC2 的是 (res, ctx)，故分开列。
MANAGED_EVALUATORS = {"rds": eval_rds, "elasticache": eval_elasticache,
                      "msk": eval_msk}
SERVICES = ("ec2",) + tuple(MANAGED_EVALUATORS)


def dispatch(res, ctx):
    """按 res["service"] 选判据。service 必填，缺失或不认识一律抛错。

    不得默认走 EC2 路径：实测缺陷正是 main() 把所有资源都喂给 evaluate()，
    而托管服务的指标名不同（dbload_p95 / engine_cpu_p95 / cpu_total_p95 而非
    sus_cpu / peak_cpu），于是指标齐全的资源被判成 metric-missing——
    「判得了」被伪装成「判不了」，整个托管服务报告静默消失。
    这里的默认值本身就是缺陷，所以缺失必须响。
    """
    svc = res.get("service")
    if svc not in SERVICES:
        raise ValueError(
            f"资源 {res.get('rid')!r} 的 service={svc!r}：该字段必填，"
            f"须为 {sorted(SERVICES)} 之一；缺失不得回退 ec2")
    if svc == "ec2":
        return evaluate(res, ctx)
    # ---- 托管侧采样量：分档而非拒绝，与 EC2 同一道门限 ----
    # 放这里而不是三个 evaluator 里：三份副本会各自漂移，dispatch 是唯一入口。
    #
    # 「少」与「无」走相反的路（与 evaluate() 一致）：
    #   sample_n is None / == 0 ⇒ fail-closed
    #   0 < sample_n < 门限      ⇒ 跑完判据，追加样本量 blocker
    #
    # 旧行为在门限之下直接 return，**连否决项一起压掉**：实测
    # 一个 prod 命名 MSK 集群的 UnderReplicatedPartitions=27 与一个 Redis
    # 复制组的 ReplicationLag=23.88s 都因此没出现在
    # 报告里，报告只写了「点数不足」。否决项读的是 max，采样量挡它没有依据。
    #
    # 托管行的 confidence：**只设 `low`，不设上两档**。
    # `high`/`medium` 由 evaluate() 的「有无内存数据」决定，托管侧没有那个轴；
    # 但 `low` 只需要采样轴，托管侧有。不设它的后果是 report-template 的两条
    # 规则（低样本行须标样本量、摘要须给 confidence=low 的 breakout）对
    # RDS/ElastiCache/MSK **永远不触发** —— 一个 sample_n 只有门限 8% 的集群
    # 会带着空白 confidence 进头条，且按构造被排除在 breakout 之外，
    # 唯一的痕迹是一条 blocker 字符串，而那两条规则不读字符串。
    t = ctx["thresholds"]
    n = res.get("sample_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n == 0:
        return {"rid": res.get("rid"), "service": svc, "cur": res.get("type"),
                "verdict": "insufficient-data",
                "blockers": [f"主判据指标 biz-hours "
                             f"{'点数未知' if n is None else '0 点'}"
                             f"（门限 {floor_pts}），p95 无从计算，"
                             f"不产出任何建议"]}
    out = MANAGED_EVALUATORS[svc](res, t, ctx.get("baseline_pct") or {})
    if n < floor_pts:
        out["confidence"] = "low"
        out.setdefault("blockers", []).append(
            f"样本 {n} 点 < {floor_pts}（占门限 {round(n / floor_pts * 100)}%），"
            f"p95 统计意义弱，本行结论的置信度相应下降，窗口填满后须复评。"
            f"若本行给出了变更建议，执行前优先安排回滚演练")
    return out


def main():
    ctx = json.load(sys.stdin)
    # ctx 未给 thresholds 时按 sizing_profile 从 thresholds.json 加载。
    # 给了则原样使用，便于测试注入。
    # sizing_profile 用下标取：SKILL.md 声明它必填且不可推断。两个 profile
    # 在同一机群上给出的条数与总额都不同（见 thresholds.md 的实测对比），
    # 静默选一个等于替 operator 做了决定，且报告里看不出选过。
    if "thresholds" not in ctx:
        ctx["thresholds"] = load_thresholds(ctx["sizing_profile"])
    ctx["_specs_by_type"] = {s["t"]: s for s in ctx["specs"]}
    ctx["_offerings"] = set(ctx["offerings"])
    ctx["_legacy"] = set(ctx["legacy_families"])
    t = ctx["thresholds"]
    out = []
    for res in ctx["resources"]:
        f = dispatch(res, ctx)
        f["service"] = res["service"]   # 托管判据已自带，EC2 路径在此补齐
        # blockers 一律是**字符串数组**。托管判据本来就产出数组，EC2 侧过去
        # 用字符串 += 拼接——同一个 CSV 列出现两种类型，写出侧无论假定哪一种
        # 都会在另一半资源上出错（且是静默的：join 一个字符串会逐字符拆开）。
        f.setdefault("blockers", [])
        # 桶 C 候选是独立一列，不参与 bucket 归类（停机与降配不互斥）。
        # 托管服务没有桶 C，显式给 None 而不是 False。
        f["stop_candidate"] = (is_stop_candidate(res, t)
                               if res["service"] == "ec2" else None)
        if res["service"] != "ec2":
            # 托管服务只有 downsize / 非 downsize 两种桶，**永不进桶 B(idle)**：
            # is_idle 读的 sus_cpu / net_mb_day 只在 EC2 侧定义，拿它判托管服务
            # 会因指标缺失恒返回 False，把「没做闲置评估」伪装成「不闲置」。
            # upsize-candidate / blocked / 已合理配置 一律 excluded——它们都不是
            # 可节省项，尤其 upsize-candidate 表示规格已不足。
            f["bucket"] = ("downsize" if f["verdict"] == "downsize-candidate"
                           else "excluded")
        # 桶优先级 idle > downsize：命中 idle 时降配方案降级进 blockers，不另起一行
        elif is_idle(res, t):
            f["bucket"] = "idle"
            if f.get("nonburst"):
                f["blockers"].append(
                    f"若须保持运行，可降配至 {f['nonburst']['t']}，"
                    f"月省 ${f['nb_save_mo']}。")
            f["blockers"].append(
                "闲置判据只证明该窗口内未观察到活动，不证明可删除；"
                "冷备、被动监听、低频定时任务均不可见。")
        else:
            f["bucket"] = {"downsize": "downsize"}.get(f["verdict"], "excluded")
            # 采样量分档只放开**降配**路径；`is_idle` 保持硬门限（删除不可回滚）。
            # 但那道门限一挡，本行就完全看不出「闲置根本没评估过」——它拿到的是
            # 一条看起来确定的降配建议，而删除路径值的是全额 `cur_cost_mo`
            # 而不是 `nb_save_mo`（实测差 13.9 倍）。不写这一句，就是把
            # 「没做闲置评估」伪装成「不闲置」，与 dispatch() 对托管服务
            # 明令禁止的那种静默降级同形。
            n_idle = res.get("cpu_n")
            if (res["service"] == "ec2" and n_idle is not None
                    and 0 < n_idle < t["min_biz_hours_points"]):
                f["blockers"].append(
                    f"闲置判据（桶 B）**未评估**：其门限不随采样量分档放宽"
                    f"（删除不可回滚），而本行 biz-hours 仅 {n_idle} 点 < "
                    f"{t['min_biz_hours_points']}。若该资源实际闲置，"
                    f"可省的是全额 cur_cost_mo 而非本行的降配差价，"
                    f"窗口填满后须重判")
        out.append(f)
    # 输入行数必须等于输出行数——任何静默丢行都是缺陷
    assert len(out) == len(ctx["resources"]), "输出行数与输入不符：存在静默丢行"
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
