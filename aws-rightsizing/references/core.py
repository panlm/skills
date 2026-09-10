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


def _ceil_div(numer, denom):
    return math.ceil(numer / denom)


def _required(cur, sustained, peak, target, ceiling):
    """两项取 max：保证降配后 p95 与峰值都不越界。

    峰值项不可省——只看 p95 会把有尖峰的负载降到峰值打满。
    """
    return max(_ceil_div(cur * sustained, target), _ceil_div(cur * peak, ceiling))


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

    pool = [dict(sp, usd=prices[f"{sp['t']}|{res.get('operation')}"])
            for sp in ctx["specs"] if passes_common(sp)]

    nb = sorted((s for s in pool
                 if not s["burst"] and s["vcpu"] >= rv and s["gib"] >= rg),
                key=lambda s: (s["usd"], s["t"]))
    out["nonburst"] = nb[0] if nb else None

    # 先判「适用性」再判「缺失」。CPUSurplusCreditsCharged 只有 T 系列发布，
    # 对非突发当前机型它是「不适用」而不是「缺失」——
    # 无条件 fail-closed 会让突发降配路线在生产上永久不可达（实测 25/29 台）。
    # 与 eval_rds 的 _rds_is_burstable 守卫同构。
    sc = res.get("surplus_credits")
    if cs["burst"] and sc is None:
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
    if out["nonburst"] or out["burst"]:
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


def _spike_note(label, mx, cause):
    return (f"{label} 持续值未越界，但窗口内曾达 {mx}（单次尖峰，"
            f"常见成因：{cause}）。降配前确认该尖峰非容量不足所致；"
            f"本判据取 p95 为持续值，故窗口内最多 {VETO_TOLERANCE_PCT}% 的时长"
            f"处于该状态仍不否决")


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


def eval_rds(res, t):
    """RDS 判据。第一判据是 Performance Insights 的 db.load.avg，不是 CPUUtilization。

    实测教训：某 db.t4g.medium 的 DBLoad p95 = 0.547 < 0.5×2vCPU ⇒ 前置"满足"，
    但 CPUSurplusCreditsCharged 单小时最大 730.6（采 Maximum）、CPUCreditBalance 最小值 0
    ⇒ 规格已不足，实际是升配候选。故信用超额是**独立否决项**，优先级高于 DBLoad。
    """
    out = {"rid": res["rid"], "service": "rds", "cur": res["type"], "blockers": []}
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
    if burstable and sc is None:
        _verdict(out, "metric-missing",
                 "CPUSurplusCreditsCharged 缺失，无法排除信用已超额")
        return out
    if sc is not None and sc > 0:
        _verdict(out, "upsize-candidate",
                 f"CPUSurplusCreditsCharged={sc} > 0，规格已不足，是升配候选")
        return out
    dbload = res.get("dbload_p95")
    if dbload is None:
        _verdict(out, "metric-missing",
                 "db.load.avg 缺失，RDS 降配的第一判据不可得")
        return out
    if dbload >= vcpu:
        _verdict(out, "blocked",
                 f"DBLoad p95 {dbload} >= vCPU {vcpu}，CPU 已是瓶颈")
        return out
    if dbload >= t["rds_dbload_ratio"] * vcpu:
        _verdict(out, "已合理配置",
                 f"DBLoad p95 {dbload} 未低于 {t['rds_dbload_ratio']}×vCPU({t['rds_dbload_ratio']*vcpu})")
        return out
    # 候选集为空 ⇒ 直接已合理配置，早于剩下的前置指标要求（同 eval_elasticache /
    # eval_msk）。否则会让客户为一条不可能产出的建议去补 FreeableMemory 再等一个窗口。
    #
    # **位置是判据的一部分。** 放在两个欠配否决项**之后**：信用超额
    # （sc > 0 ⇒ upsize-candidate）与 DBLoad 瓶颈（dbload >= vCPU ⇒ blocked）。
    # 那两条说的是"这台机器太小了"，客户必须看到，不能被"没有更便宜的候选"盖掉。
    # 代价（刻意接受）：下面 FreeableMemory 的 OOM 阻断会被本条短路掉——但那条
    # 说的是"缩不了"，与"没有可缩的目标"给出的动作完全一致（都不降配），
    # 而把它放在本条之前就等于为一条不可达的建议要求 FreeableMemory 数据。
    cheaper = res.get("cheaper_candidate_exists")
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        # 第二条 blocker：本条短路掉了下面 FreeableMemory 的 OOM 阻断，
        # 所以必须说明"没查内存压力"，否则读者会把「已合理配置」读成「这台机器很健康」。
        # 前者是关于候选集的结论，后者是关于机器的结论，两回事。
        _verdict(out, "已合理配置",
                 "同形态下没有更便宜的候选实例类；"
                             "补充指标或延长窗口都不会改变结论",
                             "本行未评估内存压力（FreeableMemory 阻断在候选集为空时"
                             "不再计算）——"
                             "「已合理配置」说的是没有可降的目标，不是这台机器健康")
        return out
    freeable_min, mem_gib = res.get("freeable_mem_min_gib"), res.get("mem_gib")
    if freeable_min is None or mem_gib is None:
        _verdict(out, "metric-missing",
                 "FreeableMemory 或实例内存未知，无法判断降配是否 OOM")
        return out
    if freeable_min < (t["rds_freeable_mem_floor_pct"] / 100) * mem_gib:
        _verdict(out, "blocked",
                 f"FreeableMemory 最小值 {freeable_min} GiB < 实例内存 {t['rds_freeable_mem_floor_pct']}%，降配会 OOM")
        return out
    _verdict(out, "downsize-candidate",
                 "需变更窗口 + 回滚预案；存储不可缩容，过度预配只能 next-rebuild",
                         _FIT_UNVERIFIED)
    return out


def eval_elasticache(res, t):
    """ElastiCache 判据。内存必须用 pricing 的 memory，且要扣 reserved-memory-percent。

    实测：cache.t3.medium 真实 3.09 GiB，映射到 EC2 t3.medium 得 4.00 GiB，偏 +29%。
    DatabaseMemoryUsagePercentage 是相对真实节点内存的百分比，基数错则绝对量错。
    """
    out = {"rid": res["rid"], "service": "elasticache", "cur": res["type"], "blockers": []}
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
    lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
    if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:
        _verdict(out, "blocked",
                 f"ReplicationLag 持续值 {lag_persist}s >= "
                 f"{t['redis_repl_lag_max_s']}s"
                 + (f"（窗口内最大 {lag_max}s）" if lag_max is not None else ""))
        return out
    if lag_max is not None and lag_max >= t["redis_repl_lag_max_s"]:
        out["blockers"].append(_spike_note("ReplicationLag", f"{lag_max}s",
                                           "failover / 备份快照"))
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
    cheaper = res.get("cheaper_candidate_exists")
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        _verdict(out, "已合理配置",
                 "同形态下没有更便宜的候选机型；"
                             "补充指标或延长窗口都不会改变结论")
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
    return _verdict(
        out, "downsize-candidate",
        f"候选 node type 扣掉 reserved-memory-percent "
        f"{reserved * 100:.0f}% 后的可用内存须 >= "
        f"{out['required_gib_usable']} GiB"
        f"（该值＝当前节点已用的可用内存，未含增长余量）",
        "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）",
        _FIT_UNVERIFIED)


def eval_msk(res, t):
    """MSK 判据。CPU 用 metric math 的 CpuUser+CpuSystem 逐点相加。

    刻度陷阱（同 namespace 内不统一，实测）：
        KafkaDataLogsDiskUsed        0-100
        RequestHandlerAvgIdlePercent 0-1     ← 判据写 >70% 会永不成立
    """
    out = {"rid": res["rid"], "service": "msk", "cur": res["type"], "blockers": []}
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
    cheaper = res.get("cheaper_candidate_exists")
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        _verdict(out, "已合理配置",
                 "同形态下没有更便宜的候选机型；"
                             "补充指标或延长窗口都不会改变结论")
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
    return _verdict(
        out, "downsize-candidate",
        "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
        "不产出减 broker 数建议（需 partition 重分配，属架构级）",
        _FIT_UNVERIFIED)


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
    out = MANAGED_EVALUATORS[svc](res, t)
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
