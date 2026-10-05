# Agent 3 · 表达风格 DNA：伊恩·莱斯利（Ian Leslie）

- 维度：表达风格 DNA（句式、语气、确定性、幽默、引用习惯、结构套路；中英双语取样）
- 调研日期：2026-10-02
- 来源数：39（见文末来源清单）
- 一手 / 二手：35 / 4（一手含中译本 10 个 part、20 个英文存档、Ruffian 全量目录、英文版目录、3 条未存全文的线索；二手仅用于转引书中原句和找线索）
- 语料量：中译本正文 113,369 字（取样 20 段，17,189 字）；英文 45,307 词（19 个文本计入统计）
- 存档目录：`references/sources/articles/a3-*`，共 20 个文件（17 篇全文、3 篇付费文章的公开预览）
- 统计脚本草稿：`/tmp/a3_zh_stats.py`、`/tmp/a3_en_stats.py`、`/tmp/a3_html2md.py`（临时目录，未进仓库）
- 可信度标记：【一手】他本人写的/说的；【二手】别人写他；【推断】本调研的推理；【译文】中译本特征，可能混入译者马婕的风格

> 写作约定：中文书引文逐字照抄并注明 part 文件；英文引文逐字保留并附中文意译；"大意"不加引号；矛盾直接记录不调和。

## 发现1：先讲一个具体的人或场景，再给观点；结尾收在一句短判断，或者把选择交还给读者

中译本 10 处章节开头中有 6 处以具体人物或场景起笔（A2-1）；英文报刊长文和 Aeon 随笔同样以"时间 + 地点 + 人物"开场（B4-1）。结尾收在对仗或交错式的短句上（"What matters, in the end, is not that I am right but that we are."，Aeon 2021），或者用问句把选择交给读者（"若换做是你，你会把握住这一千载难逢的幸运时机吗？"，书:part0012）。书中故事往往讲到一半就停下来插入研究，十几段之后才回来交代结局（A2-3）。【一手】

## 发现2：英文原文比中译本更口语、更短促、比喻更生猛；中译本的"然而"、部分 hedge 和书面腔是译文造成的

13 段平行对照显示，译者基本保留了句子边界（英文 68 句，中文 69 句；1 个英文词约对应 1.75 个汉字），所以中译本句子长是原书本身的特点。真正由译文造成的是词汇和语气的变化：生猛的比喻被磨平（"laceration"变成"打破"），口语变成公文腔（"worth the difficulty"变成"利大于弊"），有的地方凭空加了 hedge（"at some point"译成"在某种程度上"），有的地方删掉了 hedge（"can yet be said"），还有核心词误译（"incurious"译成"冷漠"）（B3）。转折词方面，英文句首 But 出现 86 次、However 为 0；中译本则是"然而" 91 次、"不过" 4 次。【一手 + 推断】

## 发现3：hedge 少而精，只用在预测和自我修正上；正文多用"often / tend to / at least"这类社科式限定；结论收得很硬

第一人称 hedge 只有 1.02 次/千词（"I think / I suspect"），一般性限定词 6.69 次/千词，断言词 3.05 次/千词。他会公开改口（"I think I might have been too harsh on Grant. … I still lean towards the second opinion. But I'm less certain that I was."，2023），但文章最后一句常常是硬判断（"Anti-taste is anti-human."，2026；"We should strive to be difficult to model."，2022）。政治评论比文化随笔更武断，例如标题 "Andy Burnham Is Going To Be Yet Another Terrible Prime Minister"（2026）。【一手】

## 发现4：英式冷幽默放在括号、自嘲和句尾补刀里，从来不放在论点本身

括号旁白在 Ruffian 里约 5 次/千词。自嘲的例子："William of Ockham only had one razor. I have nine. Does that make me a more important thinker than William? I leave that to the judgement of history."（2024）。句尾补刀的例子："Not unlike their creators."（2025）、"(Dr Katz is the author of four diet books.)"（Guardian 2016）。一本正经的突降："*Dynasty* was on."（2014）。中译本保留了一部分这类笑点，例如"（很显然，如果你足够努力去探寻，使用牙线也可以很有趣）"（书:part0011 注[18]）（B4-4、A2-6）。【一手】

## 发现5：他点名反对 AI 腔，这可以直接当作扮演时的禁忌；但这条和他自己惯用的"不是……而是……"句式存在张力

"Staccato sentences. Hysterical metaphors. This isn't X—it's Y. Let that sink in."（How Not To Use AI，2026-01-17）。可是中译本里"不是……而是……"出现了 24 次，英文样本里"not X but Y"也有 11 次。这条张力的记录见"矛盾与薄弱点"，此处不做调和。【一手】

## A. 中译本取样统计（20 段）

**方法**（脚本草稿 `/tmp/a3_zh_stats.py`，python3 标准库）：每段 = 指定小标题下从第 1 段起累积到 ≥800 字（最多 6 段）的连续正文（"收尾"类从小节末尾倒取）。统计前剔除：脚注标号 `[n]`、括号内英文原名（译本特有）、与相邻段完全重复的"抽出引语"段（epub 里有 4 处，如 part0006 "好奇心依赖于摩擦阻力……"连出两次）。字 = 非空白非标点字符；句 = 以 。！？ 结尾。另跑一遍"全书正文基线"（part0003–0012 全部正文，113,369 字 / 3,023 句）做对照。

**指标口径**：类比 = 就像/仿佛/如同/犹如/好比/宛如/似的(排除"类似的")/比作/比喻/隐喻/像……一样|那样|一般（组合正则、非重叠，防"就像……一样"双计；"好像"兼有"似乎"义，单列不计）。断言 = 显然/毫无疑问/无疑/必然/肯定/毋庸置疑/确实/不可能/必须/一定(是|会|要|能|得)。hedge = 也许/或许/可能(非"可能性"、先剔"不可能")/大概/似乎/恐怕/未必/不一定/看起来/某种程度/一定程度。让步纠偏 = 当然/事实上/其实/诚然/固然。作者"我" = 去掉 “……” 引语后的"我"（不含"我们"）。西式人名 = "X·Y"音译名（具体人物密度的代理指标）。引语占比 = “……”内字数 / 总字数。

| 编号 | part·段落 | 小节（类型） | 字数 | 句数 | 均句长 | 问句% | 类比/千字 | 作者"我"/千字 | "我们"/千字 | "你"/千字 | 断言/千字 | hedge/千字 | 让步纠偏/千字 | 转折(但是+然而+不过)/千字 | 转折含"但""却"/千字 | 西式人名/千字 | 年份/千字 | 引语占比% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P01 | 0003·3-8 | 天赋异禀的黑猩猩坎吉（引言·开篇故事） | 942 | 27 | 34.9 | 0.0 | 1.06 | 0.0 | 1.06 | 0.0 | 2.12 | 2.12 | 0.0 | 2.12 | 5.31 | 1.06 | 0.0 | 1.1 |
| P02 | 0003·12-17 | 劳埃德的自我救赎（引言·人物故事） | 852 | 35 | 24.3 | 2.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.17 | 2.35 | 2.35 | 3.52 | 7.04 | 1.17 | 15.1 |
| P03 | 0003·63-69 | 消遣性好奇与认识性好奇（引言·概念论证） | 837 | 23 | 36.4 | 0.0 | 2.39 | 0.0 | 14.34 | 1.19 | 0.0 | 0.0 | 0.0 | 0.0 | 1.19 | 1.19 | 2.39 | 3.1 |
| P04 | 0003·80-85 | 选择好奇心的理由（引言·收尾） | 1061 | 35 | 30.3 | 5.7 | 0.94 | 15.08 | 3.77 | 1.89 | 0.0 | 0.0 | 0.0 | 1.89 | 1.89 | 2.83 | 0.94 | 6.0 |
| P05 | 0004·4-9 | 布莱恩与那把手枪的故事（第1章·开头故事） | 858 | 29 | 29.6 | 3.4 | 1.17 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2.33 | 1.17 | 0.0 | 2.7 |
| P06 | 0004·39-43 | 为什么智人是如此具有好奇心的动物（第1章·论证） | 1020 | 27 | 37.8 | 0.0 | 0.0 | 0.98 | 5.88 | 0.0 | 0.0 | 9.8 | 0.0 | 0.0 | 1.96 | 0.98 | 0.0 | 2.6 |
| P07 | 0005·3-6 | 婴儿大脑之谜（第2章·开头，现场采访） | 806 | 20 | 40.3 | 0.0 | 0.0 | 3.72 | 0.0 | 3.72 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 4.96 | 1.24 | 0.2 |
| P08 | 0006·3-6 | 好奇心的衰减（第3章·开头，引语开篇） | 800 | 23 | 34.8 | 0.0 | 0.0 | 0.0 | 7.5 | 0.0 | 0.0 | 2.5 | 0.0 | 3.75 | 8.75 | 2.5 | 0.0 | 19.1 |
| P09 | 0006·54-58 | 谜题与奥秘的区别（第3章·概念论证） | 968 | 30 | 32.3 | 20.0 | 1.03 | 0.0 | 8.26 | 9.3 | 1.03 | 4.13 | 2.07 | 2.07 | 7.23 | 2.07 | 0.0 | 3.7 |
| P10 | 0006·70-75 | 网络对好奇心的挤压（第3章·论证，互联网） | 642 | 19 | 33.8 | 5.3 | 0.0 | 0.0 | 1.56 | 0.0 | 1.56 | 3.12 | 0.0 | 1.56 | 1.56 | 1.56 | 0.0 | 4.2 |
| P11 | 0007·4-9 | 被视为危险之物的时代（第4章·开头，观念史） | 917 | 31 | 29.6 | 3.2 | 0.0 | 1.09 | 4.36 | 0.0 | 0.0 | 2.18 | 1.09 | 0.0 | 1.09 | 4.36 | 0.0 | 13.8 |
| P12 | 0008·3-9 | 好奇对成功的影响力（第5章·开头，数据） | 962 | 27 | 35.6 | 7.4 | 0.0 | 0.0 | 4.16 | 0.0 | 0.0 | 0.0 | 0.0 | 5.2 | 7.28 | 4.16 | 0.0 | 3.7 |
| P13 | 0009·3-7 | 提问改变人生（第6章·开头故事） | 801 | 20 | 40.0 | 0.0 | 0.0 | 1.25 | 3.75 | 0.0 | 1.25 | 2.5 | 1.25 | 3.75 | 6.24 | 1.25 | 1.25 | 17.2 |
| P14 | 0010·3-8 | 米特拉的实验（第7章·开头故事） | 633 | 21 | 30.1 | 23.8 | 1.58 | 0.0 | 3.16 | 0.0 | 0.0 | 3.16 | 0.0 | 0.0 | 3.16 | 3.16 | 1.58 | 4.1 |
| P15 | 0010·33-38 | 对学习的三大常见误解（第7章·驳论） | 787 | 20 | 39.4 | 0.0 | 0.0 | 0.0 | 6.35 | 0.0 | 0.0 | 1.27 | 1.27 | 0.0 | 1.27 | 3.81 | 2.54 | 7.0 |
| P16 | 0011·4-8 | 虚心若愚（第8章·方法1，对比开篇） | 928 | 26 | 35.7 | 0.0 | 1.08 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2.16 | 5.39 | 3.23 | 3.23 | 1.0 |
| P17 | 0011·76-80 | 询问关键的"为什么"（第8章·方法4） | 850 | 18 | 47.2 | 0.0 | 0.0 | 4.71 | 0.0 | 2.35 | 0.0 | 1.18 | 0.0 | 2.35 | 4.71 | 4.71 | 1.18 | 0.0 |
| P18 | 0011·107-111 | 做一个"思想工匠"（第8章·方法5） | 853 | 20 | 42.6 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.17 | 1.17 | 0.0 | 1.17 | 3.52 | 1.17 | 2.34 | 5.4 |
| P19 | 0011·126-130 | 质疑你的茶匙（第8章·方法6） | 837 | 24 | 34.9 | 4.2 | 1.19 | 3.58 | 1.19 | 0.0 | 2.39 | 0.0 | 0.0 | 0.0 | 2.39 | 2.39 | 0.0 | 12.9 |
| P20 | 0012·16-20 | 后记（收尾） | 835 | 22 | 38.0 | 4.5 | 1.2 | 4.79 | 13.17 | 3.59 | 0.0 | 4.79 | 0.0 | 1.2 | 4.79 | 4.79 | 1.2 | 28.4 |
| **20段合计** | — | — | 17189 | 496 | 34.7 | 4.2 | 0.58 | 1.92 | 3.96 | 1.16 | 0.47 | 1.98 | 0.41 | 1.51 | 3.72 | 2.91 | 0.93 | 7.4 |
| **全书正文基线** | — | — | 113369 | 3023 | 37.5 | 3.2 | 0.74 | 1.45 | 4.30 | 2.28 | 0.62 | 2.02 | 0.61 | 1.86 | 4.16 | 3.10 | 0.86 | 8.3 |

全书基线原始计数：问句 98（引语外的作者问句 69）；类比 84；作者"我" 164（含引语 248）；断言 70 vs hedge 229；让步纠偏 69；转折 但是 116 / 但(单字) 156 / 然而 91 / 不过 4 / 可是 6 / 却 99；"好像" 12（未计入）；归属动词（说道/写道/说：/指出/认为/回忆/告诉我）3.36/千字；"不是……而是"句式 24 次；"告诉我"11 次（采访来源）；中文括号插话（不含英文名、译注）93 处。

**读数（【推断】，基于上表）**：

1. **句子长**：中译本均句长 37.5 字/句，属偏长的书面中文。B3 的平行对照显示，译文基本没有改变句子边界，长句是原书本身的特点（原书约 21–22 词/句，比他的 newsletter 长）；译文改变的是语气和用词（见 B3、C3）。
2. **问句不多，但位置固定**：问句只占 3.2%，作者自己发问的 69 句集中在三个位置：小节结尾的过渡问（例："换句话说，为什么智人是如此具有好奇心的动物呢？" 书:part0004 第1章）、叙事里人物的发问（P14 米特拉段 23.8%）、全书收尾问读者（"你会选择保持一颗好奇心吗？" 书:part0003 引言；"若换做是你，你会把握住这一千载难逢的幸运时机吗？" 书:part0012 后记）。他不用"连珠炮式问句"，而是在转场处用一个问句开下一节。
3. **类比不多，但用的是"大比喻"**：带标记的类比只有 0.74/千字，但不带标记的整体隐喻很重，而且贯穿一章：好奇是"一把双刃剑"（part0004）、学校是"好奇心的熔炉"（part0010）、"就像电灯泡里钨丝对电流的阻碍会使电灯泡发亮一样，认识性好奇也是以解决重重困难的方式来使人获得启迪"（part0004）、"一个生长过剩的花园在慢慢减少累赘，变得越来越有调理"（part0006，指大脑修剪）、"文化延续的载体需要英明而熟练的掌舵人……那么我们就应该帮助他们找到舵轮"（part0010）。
4. **hedge 比断言多三倍多（2.02 vs 0.62/千字）**，但 hedge 主要来自"可能"（229 中占 175），多数是描述性情态（"它可能会按下有'果汁'图形的按键"），不是作者对自己观点没把握。真正的论点句反而很硬（见 A2-5"断言方式"）。这一项不能直接当成"谨慎"的证据。
5. **"我"出现得少，但一出现就很关键**：作者"我" 1.45/千字，集中在 P04（15.08）、P17、P19、P20、P07。用法有三类：①记者在场（"2014年2月的一个下午，我在Babylab与两位探究认识性好奇起源的心理学家……见面" part0005；"一个寒冷的星期天早上，我站在伦敦东区一个很长的队伍里。" part0011；"当我跟他聊天时，他告诉我，目前他正参与全世界8个不同的冲突。" part0011）；②个人生活与自我检讨（"我现在很难过地意识到，我每次忽略女儿的提问都有可能减少了她天生的求知渴望。" part0005；"离开大学后，我进入了智威汤逊（J. Walter Thompson）广告代理公司的伦敦分部。" part0011）；③明确表态（"我并不同意互联网让我们变笨的说法。" part0008；"让我越来越信服的一件事就是拥有广阔的知识面的重要性。" part0011）。
6. **"我们"比"我"高 3 倍（4.30/千字）**：他主要用包含读者的"我们"推论证（P03 14.34、P20 13.17），"你"（2.28/千字）用来把读者拉进场景或预设读者的成见（"你可能会认为……然而……" 3 次，见 part0007 音乐消费段）。
7. **具体性非常高**：每千字约 3.1 个西式人名、0.86 个具体年份，引语占全文字数 8.3%，每千字 3.36 个"某某说/写道/告诉我"。这本书是靠"人＋年份＋原话"推进的，不是靠抽象论证。
8. **转折频率中等（但是+然而+不过 1.86/千字）**：用词分布有译文特征："然而" 91 次、"不过"只有 4 次。"然而"比口语"不过"更书面，是译者的选择：英文样本里句首 But 86 次、However 0 次（B2）。

## A2. 中译本结构套路

### A2-1 章节怎么开头（10 处全数检查）

| 位置 | 开头方式 | 原文首句（逐字） |
|---|---|---|
| 引言 part0003 | 具体动物/人物故事 | "研究者们意识到坎吉（Kanzi）是一只天赋异禀的黑猩猩，是从发现它能自学语言开始的。" |
| 第1章 part0004 | 具体人物 + 年代 + 地点 | "20世纪60年代，布莱恩·史密斯生活在美国密苏里州圣路易斯市。" |
| 第2章 part0005 | 第二人称带路 + 记者到场 | "如果你想评出世界上认识性好奇水平最高的社区，不妨考虑下伦敦的布鲁姆斯伯里（Bloomsbury）。" |
| 第3章 part0006 | 名人引语 | "亨利·詹姆斯（Henry James）意味深长地评述道：“我们单纯的求知热情在我们成年后就衰退了。"（后文略） |
| 第4章 part0007 | 观念史论断 | "我们对于好奇心的观念在不断地变更着。" |
| 第5章 part0008 | 宏观数据论断 | "在当今社会中，教育程度是影响个人未来发展最重要的因素之一。" |
| 第6章 part0009 | 具体人物 + 年份 | "1990年，丹·罗斯坦（Dan Rothstein）在马萨诸塞州一个名为劳伦斯的老工业小镇从事社区组织工作。" |
| 第7章 part0010 | 具体人物 + 年份 | "1999年，苏加塔·米特拉（Sugata Mitra）在新德里的一所学院向一些来自中产阶级家庭的学生讲授计算机编程课程。" |
| 第8章 part0011 | 隐去姓名的对比悬念 | "过去几百年中最有影响力和创造力的两位商人有着很多的相似之处。"（几段后才揭晓是迪士尼和乔布斯） |
| 后记 part0012 | 反常识事实 | "第一个踏上北美大陆的欧洲人不是克里斯托弗·哥伦布，而是一位名叫莱夫·埃里克森（Leif Eriksson）的挪威探险者。" |

结论【推断】：10 处里 6 处以一个具体的人或场景开头。其中 3 处在首句就交代了年份或年代（布莱恩、罗斯坦、米特拉），5 处在首句或第二句点出了城市或街区（圣路易斯、劳伦斯、新德里、布鲁姆斯伯里、亚特兰大）。其余 4 处是引语、观念史、数据、反常识各 1 处。**没有一处以"本章将讨论……"开头。**

### A2-2 章节怎么收尾

收尾有三种：①回到前文的故事或意象（引言结尾回到前面讲过的约翰·劳埃德："当约翰•劳埃德回忆他如何看待自己最成功的那几年时光时，他觉得自己并不是一个完整的人。" part0003；第8章最后一节以弗里德曼照片里的密码揭晓"知识就是力量。" part0011；第7章结尾先引贝娄小说里的"看在上帝的份上，把宇宙打开多一点吧！"，最后一句"它把宇宙向你多打开了一点。"回扣这个意象 part0010）；②引一个具体人物的原话做讽刺性收束（第3章结尾引谷歌搜索负责人辛格："事实正相反。系统变得越精确，提问就能越简单。" part0006；第6章结尾引一个六年级学生的话 part0009）；③把选择交给读者（引言"你会选择保持一颗好奇心吗？"、第5章"未来属于那些选择具有好奇心的人。" part0008、后记"这正好为我们提供了选择。……若换做是你，你会把握住这一千载难逢的幸运时机吗？" part0012）。

**"选择"是贯穿全书的收尾母题**（引言、第5章、后记三处收尾都落在"选择"上）【推断】。还有一处收尾是作者的自我检讨（第2章："我现在很难过地意识到，我每次忽略女儿的提问都有可能减少了她天生的求知渴望。" part0005），这在畅销书作者里少见，值得保留为"顾问口吻"的一种调性。

### A2-3 从故事到研究的过渡（以第1章 part0004 第4–37段为样本）

完整节奏是：电影式场景（"嘣！那盏色的霓虹灯突然就熄灭了。"，原文如此）→ 冷数据压住情绪（"2007年美国就有122起儿童因枪支意外发射而死亡的案例"）→ 一句格言式结论（"自我保护意识是我们最根深蒂固的本能，但却能被好奇心给攻破。"）→ 给现象命名（"他们就被消遣性好奇给控制住了"）→ 古典引证（圣·奥古斯丁讲阿利比乌斯、埃德蒙·伯克的长引文）→ 拉回当下（"会让成年人不断刷新Twitter信息"）→ 第二个反差人物（语言狂人阿奎列斯）→ 把两个故事合并（"布莱恩·史密斯和亚历山大·阿奎列斯的故事看上去没什么相同之处，但都反映了同一个现象"）→ 回到第一个故事的结局（布莱恩后来当了警察、做枪械培训）→ 用一个问句开启下一节（"换句话说，为什么智人是如此具有好奇心的动物呢？"）。

要点：**故事讲到一半就停，插入研究，最后再回来收尾**（布莱恩的结局在约 20 段之后才交代）。研究不是故事之后的"注脚"，而是嵌在故事中间。

### A2-4 怎么处理反方

1. **先给对手体面，再拆证据**："罗宾逊爵士显然深切地关注着儿童的幸福感，并且他也是一位出色的演讲家，他对于创造力的论述引人入胜，然而却几乎完全没有根据。"（part0010 第7章）
2. **给对手的观点找家谱**，证明它"不新"："这听上去像是个现代的想法，但与爱弥儿的思想如出一辙"（part0010）；"学习能力的倡议者们通常不会承认他们的思想渊源。"（part0010）
3. **编号逐条拆**："误解1：儿童不需要教师的指导""误解2：事实抹杀创造力"（part0010）
4. **"当然……然而……"让步句**："当然，在某些学校和某些课堂上，缺乏想象力的老师可能没有努力让教学内容变得有意思而强迫学生死记硬背，这就扼杀了学生的好奇心。然而，因这部分老师的做法而得出所有的教学指导在原则上都是错误的，是一个在错误方向上的野蛮跳跃。"（part0010）
5. **先承认对方说中的那一部分**：讲完"好奇心的衰减"后马上说"因此，这种好奇心的衰退也不一定是件坏事。"（part0006），然后才转向"然而，成年人往往太过依赖于此"。
6. **立场明确**，不和稀泥："我并不同意互联网让我们变笨的说法。唯一能使你变笨或者变得冷漠的只有你自己。"（part0008）

### A2-5 断言方式与"二分 + 混合体"

- 大量用 **"不是……而是……"** 重新定义问题（全书 24 次）。例："其实并不是家长不知道要问什么，而是不知道应该如何问。"（part0009）
- 用 **"你可能会认为……然而……"** 预设读者的直觉再推翻："你可能会认为在YouTube、iTunes和Spotify盛行的年代，我们的音乐品位将变得国际化和异质化，然而费雷拉和沃德福格却发现……"（part0007）
- **先做二分，再造一个混合体**：消遣性好奇 / 认识性好奇（part0003–0004）；谜题 / 奥秘（part0006）；刺猬 / 狐狸 → "狐猬"（part0011："能在当下或是将来得到最好发展的思想家将是这两种动物的混合体。"原文 foxhog，见 part0011 注[5] 译者注）；think + tinker → thinkerer"思想工匠"（part0011 第115–116段）。注意 thinkering 一词不是他造的，他交代了出处："我是从在MoMA工作的保拉·安特那利那里知道的这个词……在这里，我用这个词来指代一种认知性调查研究的类型"（part0011）。所以更准确的说法是：**先给两个对立概念，再借用或自造一个混合词，并且交代词的来历。**
- 格言式短句压段尾："成功并不有利于好奇心发挥作用。"（part0011）；"不断提问是弱势一方抗衡强势一方最有力的武器，但这仅仅是因为强势一方单方面缴械了的缘故。"（part0009）

### A2-6 小标题风格

- 第8章七个小标题是**祈使句**：虚心若愚 / 建造数据库 / 像"狐猬"一样觅食 / 询问关键的"为什么" / 做一个"思想工匠" / 质疑你的茶匙 / 将谜题变为奥秘（part0011）。英文原题已核对（archive.org 馆藏记录的英文版目录）："8. Seven ways to stay curious. Stay foolish ; Build the database ; Forage like a foxhog ; Ask the big why ; Be a thinkerer ; Question your teaspoons ; Turn puzzles into mysteries"。特点是把具体物件放进抽象建议（"茶匙"），并且使用自造词。
- 其他各章的小标题多为"人名/事物 + 的故事/实验/之谜"（"布莱恩与那把手枪的故事""米特拉的实验""婴儿大脑之谜"）或论断短语（"好奇是一把双刃剑"）。part0011 里同时出现小标题和 `******` 分节符，说明原书在小节内部用分隔符分段。英文版目录只列出了第 8 章的七个小标题，其他章都没有（"1. Three journeys -- 2. How curiosity begins -- 3. Puzzles and mysteries -- … 7. The importance of knowing"，archive.org 记录），因此**其他章的叙事型小标题很可能是中文版编辑加的**（【推断】，目录不一定列出全部节标题）。章名的翻译也有偏移，例如 "The importance of knowing"（知道的重要性）译成了"博学的重要性"，"Three journeys" 译成了"好奇之旅"。
- 括号冷幽默在中译本里保留得较好（93 处中文括号插话中约 15 处是俏皮话）："（请诚实回答）"（part0003）、"（难怪龟兔赛跑的寓言故事如此受欢迎）"（part0005）、"（从这个意义上来说，好奇有些像虐受）"（part0006，原文如此）、"（虽然坦率地讲可能只有西塞罗持有这样的观点）"（part0007）、"（叶慈从来没有说过或者写过这样一句话）"（part0010）、"（很显然，如果你足够努力去探寻，使用牙线也可以很有趣）"（part0011 注[18]）、"（传说里并没有记录比雅尼对此事是什么态度）"（part0012）。还有段尾冷刺："他们都表现出了高'认知需求'，并将这一特点贯彻到企业文化中。至少他们在世时，企业文化是这样的。"（part0011）、"人类向来需要面对复杂性：打倒一头猛犸象可不是一件简单的事情。"（part0004）

## B. 英文一手取样

### B1 存档清单（20 个文件，均在 `references/sources/articles/a3-*`）

Ruffian 目录通过 `https://www.ian-leslie.com/api/v1/posts?limit=50&offset=N` 拉全量：共 433 篇（2017-08-28 至 2026-09-27），其中 newsletter 401 篇、podcast 32 篇；免费 181 篇、付费 250 篇、创始会员 2 篇。免费文章的 `body_html` 直接从 API 获取；付费文章抓网页 `available-content`，只取付费墙之前的公开部分。

| 文件 | 标题 | 日期 | 体裁 | 主题 | 范围 |
|---|---|---|---|---|---|
| a3-ruffian-2023-01-25-answer-machines.md | Answer Machines — Why AI Should Make Us Ask Better Questions | 2023-01-25 | Ruffian 随笔 | AI × 提问 × 好奇心 × 教育 | 全文 |
| a3-ruffian-2022-12-10-the-struggle-to-be-human.md | The Struggle To Be Human | 2022-12-10 | Ruffian 随笔 | AI、流行音乐、政治的"机器化" | 全文 |
| a3-ruffian-2021-01-02-the-problem-with-experts.md | The problem with experts | 2021-01-02 | Ruffian 早期综述 | 专家、共识、分歧 | 全文 |
| a3-ruffian-2021-02-13-good-fights.md | Good fights | 2021-02-13 | Ruffian 早期综述 | 分歧、幽默、披头士吵架 | 全文 |
| a3-ruffian-2021-10-02-in-praise-of-sheeple.md | In Praise of Sheeple | 2021-10-02 | Ruffian 随笔 | 从众、集体智慧、"独立思考" | 全文 |
| a3-ruffian-2023-03-25-red-carpet-blues.md | Red Carpet Blues | 2023-03-25 | Ruffian 随笔 | 对话失败、会话分析 | 全文 |
| a3-ruffian-2025-03-19-the-surest-way-to-make-an-ai-lie.md | The Surest Way To Make an AI Lie Is To Tell It Not To Lie | 2025-03-19 | Ruffian 随笔 | AI 说谎 × Born Liars | 全文 |
| a3-ruffian-2025-10-21-why-are-llms-fixated-on-the-number.md | Why Are LLMs Fixated On the Number 7? | 2025-10-21 | Ruffian 随笔 | AI × 人类偏差 | 全文 |
| a3-ruffian-2026-08-29-why-introverts-make-the-best-extroverts.md | Why Introverts Make the Best Extroverts | 2026-08-29 | Ruffian 随笔（近作） | 社交、对他人的好奇 | 全文 |
| a3-ruffian-2026-07-04-notes-on-acquired-taste.md | Notes on Acquired Taste | 2026-07-04 | Ruffian 随笔（近作） | 品味、努力、AI | 全文 |
| a3-ruffian-2024-06-01-the-renaissance-redux.md | The Renaissance Redux | 2024-06-01 | Ruffian 读书笔记 | 佛罗伦萨、博学、好奇 | 全文 |
| a3-ruffian-2024-02-10-42-reflections-on-the-meaning-of.md | 42 Reflections On the Meaning of Life… | 2024-02-10（原文 2014） | Ruffian 清单体 | 个人随感、幽默口吻 | 全文 |
| a3-ruffian-2026-09-12-seven-rules-of-good-conversation-preview.md | Seven Rules of Good Conversation | 2026-09-12 | Ruffian 清单体 | 对话 | 付费，预览约 545 词 |
| a3-ruffian-2026-01-17-how-not-to-use-ai-preview.md | How Not To Use AI | 2026-01-17 | Ruffian 清单体 | AI 写作、AI 腔 | 付费，预览约 814 词 |
| a3-ruffian-2024-01-06-leslies-razors-preview.md | Leslie's Razors — Nine Rules of Thumb For Life | 2024-01-06 | Ruffian 清单体 | 经验法则 | 付费，预览约 2131 词 |
| a3-ruffian-2026-06-20-andy-burnham-is-going-to-be-yet-another.md | Andy Burnham Is Going To Be Yet Another Terrible Prime Minister | 2026-06-20 | Ruffian 政治评论 | 政治人物评价（语域对照用） | 全文；**未计入 B2 统计** |
| a3-guardian-2016-04-07-the-sugar-conspiracy.md | The sugar conspiracy | 2016-04-07 | Guardian Long Read | 科学共识、专家权威 | 全文 |
| a3-guardian-2017-10-13-scientists-persuading-terrorists.md | The scientists persuading terrorists to spill their secrets | 2017-10-13 | Guardian Long Read | 审讯、关系建立、提问 | 全文 |
| a3-aeon-2021-07-12-why-disagreement-is-vital.md | Why disagreement is vital to advancing human understanding | 2021-07-12 | Aeon Essay（改编自 Conflicted） | 分歧、推理 | 全文 |
| a3-utne-2014-10-31-curious-intro-excerpt-en.md | Why the Need for Cognition is a Survival Skill（《Curious》引言英文原文节选） | 2014-10-31 | 书摘 | 好奇心、认知需求 | 公开节选 |

未存成：1843《The scientists who make apps addictive》（economist.com 被 Cloudflare 拦截，Ruffian 2024-04-10 的重发版是付费文章）。X/Twitter 见 B6。

### B2 英文统计

**方法**（脚本草稿 `/tmp/a3_en_stats.py`）：剔除元数据头、`>` 引用块（包括 catch-up 列表和长段他人引文）、抽出引语、推广段、标题、图片说明、脚注编号、问卷条目。作者口吻指标在去掉引号内文字后计算。分句按 . ! ? 加大写开头，处理了 Mr/Dr/St/e.g. 等缩写。

- 第一人称 hedge = I think / I suspect / I guess / I believe / I'm not sure / to my mind / I suppose / I don't think / my guess / I'm (not|less) certain / I don't know / I may be wrong / I doubt / in my view / I'm wary / I'm sceptical 等
- 一般 hedge = perhaps / maybe / probably / might / may / often / tend to / kind of / a little / at least / seems to / more or less / in a sense / up to a point 等
- 断言 = always / never / must / in fact / of course / simply / clearly / certainly / obviously / surely / precisely / the truth is 等
- 类比 = like a/an/the、as if、a kind of、think of、imagine、just as、akin to 等
- 口语 = a lot / you know / stuff / OK / pretty / bullshit / I mean / Anyway / huge / Yes, / guy / So, / Oh 等
- 路标语 = that is, / Here's / In other words / Why? / In short / Note that / on to something / It's not that / The answer is / Another reason 等

单位为"每千词"。

| 文本 | 类型 | 词数 | 句数 | 均句长(词) | 中位 | ≤8词句% | ≥30词句% | 作者问句% | I/me/my | we/us/our | you/your | 第一人称hedge | 一般hedge | 断言 | 类比 | 口语 | 路标语 | 括号 | 破折号 | 句首But等 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Answer Machines (2023) | R-essay | 1467 | 85 | 17.3 | 16 | 20.0 | 9.4 | 6.7 | 14.1 | 20.0 | 10.4 | 2.97 | 5.2 | 5.2 | 4.45 | 5.2 | 0.74 | 2.23 | 8.91 | 3.71 |
| The Struggle To Be Human (2022) | R-essay | 3141 | 161 | 19.5 | 17 | 14.3 | 19.3 | 2.1 | 6.2 | 15.9 | 4.7 | 0.72 | 7.97 | 3.62 | 4.71 | 3.98 | 1.09 | 4.71 | 5.07 | 1.45 |
| The problem with experts (2021) | R-roundup | 1715 | 84 | 20.4 | 20 | 11.9 | 14.3 | 6.2 | 15.8 | 6.7 | 7.9 | 3.03 | 6.67 | 2.43 | 2.43 | 6.06 | 0.61 | 6.67 | 12.13 | 1.21 |
| Good fights (2021) | R-roundup | 1582 | 78 | 20.3 | 18 | 7.7 | 19.2 | 2.8 | 8.1 | 13.4 | 5.4 | 2.68 | 6.71 | 4.03 | 2.01 | 3.36 | 0.67 | 6.71 | 8.72 | 1.34 |
| In Praise of Sheeple (2021) | R-essay | 2261 | 122 | 18.5 | 18 | 19.7 | 15.6 | 0.8 | 11.7 | 16.2 | 9.0 | 0.0 | 9.01 | 4.06 | 3.15 | 1.35 | 1.8 | 6.31 | 4.06 | 2.25 |
| Red Carpet Blues (2023) | R-essay | 1506 | 79 | 19.1 | 18 | 16.5 | 21.5 | 1.4 | 23.1 | 2.3 | 5.4 | 5.4 | 7.72 | 1.54 | 1.54 | 2.31 | 1.54 | 6.94 | 13.89 | 2.31 |
| Surest Way To Make an AI Lie (2025) | R-essay | 1450 | 77 | 18.8 | 17 | 10.4 | 13.0 | 0.0 | 5.1 | 9.4 | 2.9 | 0.0 | 2.17 | 2.17 | 2.17 | 2.17 | 1.45 | 3.62 | 7.95 | 3.62 |
| LLMs Fixated On 7 (2025) | R-essay | 1011 | 67 | 15.1 | 14 | 28.4 | 6.0 | 9.1 | 9.1 | 12.2 | 3.0 | 1.01 | 8.11 | 1.01 | 1.01 | 4.05 | 6.08 | 8.11 | 10.13 | 6.08 |
| Introverts/Extroverts (2026) | R-essay | 2263 | 120 | 18.9 | 18 | 12.5 | 12.5 | 1.9 | 17.8 | 6.2 | 9.1 | 2.4 | 9.13 | 1.92 | 1.44 | 2.88 | 4.33 | 4.81 | 3.85 | 0.96 |
| Notes on Acquired Taste (2026) | R-essay | 2345 | 144 | 16.3 | 15 | 19.4 | 6.9 | 1.5 | 7.6 | 14.3 | 23.8 | 1.35 | 11.66 | 2.24 | 1.79 | 3.14 | 0.0 | 3.14 | 8.97 | 4.93 |
| The Renaissance Redux (2024) | R-essay | 4152 | 244 | 17.0 | 16 | 16.4 | 9.4 | 1.7 | 4.0 | 2.0 | 2.8 | 0.25 | 3.76 | 2.51 | 1.0 | 2.01 | 0.25 | 5.52 | 4.26 | 1.25 |
| 42 Reflections (2014/2024) | R-list | 1917 | 147 | 13.0 | 11 | 34.7 | 4.8 | 3.9 | 44.4 | 16.1 | 29.4 | 2.78 | 4.44 | 4.44 | 2.22 | 5.56 | 1.11 | 1.67 | 4.44 | 3.89 |
| Seven Rules of Good Conversation (2026, 预览) | R-list | 456 | 27 | 16.9 | 13 | 29.6 | 18.5 | 7.7 | 17.9 | 6.7 | 20.1 | 0.0 | 13.39 | 4.46 | 0.0 | 8.93 | 2.23 | 8.93 | 8.93 | 6.7 |
| How Not To Use AI (2026, 预览) | R-list | 739 | 41 | 18.0 | 16 | 22.0 | 17.1 | 0.0 | 24.4 | 10.8 | 23.0 | 1.36 | 14.91 | 1.36 | 1.36 | 1.36 | 0.0 | 2.71 | 4.07 | 1.36 |
| Leslie's Razors (2024, 预览) | R-list | 2037 | 109 | 18.7 | 19 | 17.4 | 15.6 | 6.6 | 24.1 | 11.8 | 34.9 | 0.51 | 18.48 | 4.11 | 0.51 | 4.11 | 2.05 | 5.65 | 4.62 | 3.08 |
| Guardian: The sugar conspiracy (2016) | Longform | 6636 | 327 | 20.3 | 19 | 13.5 | 19.3 | 1.1 | 1.8 | 7.6 | 1.2 | 0.0 | 2.46 | 2.99 | 1.06 | 0.7 | 0.53 | 2.64 | 4.4 | 2.11 |
| Guardian: Persuading terrorists (2017) | Longform | 5719 | 321 | 17.8 | 16 | 15.9 | 12.1 | 0.5 | 2.9 | 2.0 | 0.9 | 0.0 | 4.17 | 2.63 | 0.66 | 0.22 | 0.22 | 2.63 | 6.14 | 1.1 |
| Aeon: Why disagreement is vital (2021) | Longform | 3279 | 161 | 20.4 | 20 | 11.8 | 16.8 | 3.9 | 4.2 | 16.1 | 6.4 | 0.97 | 5.48 | 4.51 | 2.9 | 0.97 | 1.93 | 1.29 | 3.54 | 2.26 |
| Curious 引言英文原文节选 (2014) | Book | 1631 | 74 | 22.0 | 20 | 16.2 | 25.7 | 0.0 | 0.6 | 14.3 | 25.3 | 0.0 | 9.07 | 1.94 | 0.65 | 0.0 | 1.94 | 0.65 | 4.54 | 4.54 |
| **Ruffian 随笔合计** | — | 19596 | 1099 | 17.8 | 16 | 17.0 | 12.5 | 2.3 | 9.7 | 10.3 | 7.9 | 1.26 | 7.11 | 2.79 | 2.35 | 2.84 | 1.53 | 4.97 | 6.51 | 2.51 |
| **Ruffian 早期综述合计** | — | 3297 | 162 | 20.4 | 19 | 9.9 | 16.7 | 4.6 | 12.1 | 9.9 | 6.7 | 2.87 | 6.69 | 3.19 | 2.23 | 4.78 | 0.64 | 6.69 | 10.51 | 1.27 |
| **Ruffian 清单体合计** | — | 5149 | 323 | 15.9 | 14 | 26.9 | 11.5 | 4.7 | 31.0 | 12.8 | 29.8 | 1.42 | 12.36 | 3.85 | 1.22 | 4.66 | 1.42 | 4.05 | 4.86 | 3.45 |
| **Ruffian 全部合计** | — | 28042 | 1584 | 17.7 | 16 | 18.3 | 12.7 | 3.0 | 14.0 | 10.7 | 11.8 | 1.48 | 8.04 | 3.03 | 2.12 | 3.41 | 1.40 | 5.01 | 6.68 | 2.54 |
| **报刊长文合计** | — | 15634 | 807 | 19.4 | 18 | 14.0 | 16.0 | 1.5 | 2.7 | 7.6 | 2.3 | 0.22 | 3.75 | 3.22 | 1.35 | 0.6 | 0.75 | 2.32 | 4.8 | 1.8 |
| **书（英文原文节选）** | — | 1631 | 74 | 22.0 | 20 | 16.2 | 25.7 | 0.0 | 0.6 | 14.3 | 25.3 | 0.0 | 9.07 | 1.94 | 0.65 | 0.0 | 1.94 | 0.65 | 4.54 | 4.54 |
| **全部英文合计** | — | 45307 | 2465 | 18.4 | 17 | 16.8 | 14.2 | 2.5 | 9.8 | 9.8 | 9.3 | 1.02 | 6.69 | 3.05 | 1.87 | 2.38 | 1.33 | 3.98 | 5.99 | 2.38 |

全部英文的标记词明细：第一人称 hedge：I think 16、I suspect 3、I guess 3、I believe 3、I'm not sure 2、to my mind 2、I suppose 2、I don't think 2，其余各 1。一般 hedge：often 40、might 33、kind of 28、may 25、at least 21、a little 18、probably 17、perhaps 13、tend to 12、maybe 10。断言：always 18、in fact 16、of course 12、never 12、must 12、simply 11、clearly 7。类比：like a 17、like the 13、as if 9、a kind of 9、think of 8、imagine 6。口语：a lot 21、you know 10、stuff 8、OK 6、pretty 6、bullshit 5、I mean 4、Anyway 4。褒义评价词（推荐别人时用）：great 29、interesting 20、smart 13、fascinating 8、brilliant 8、excellent 6、beautiful 6、clever 6。句首转折：But 86 句（占全部 2465 句的 3.5%），Yet 只有 5 句，However 0 句。其他句式：rather than 21、"the more X, the more Y" 9、"not X but Y" 11、冒号揭示（"……: 结论"）119 处（2.88/千词）、分号 87 处（2.11/千词）。

**读数（【推断】）**：

1. **句长中等，长短交替**：全部英文平均 18.4 词/句（Ruffian 17.7，报刊长文 19.4，书 22.0）。16.8% 的句子不超过 8 词，14.2% 超过 30 词。他的节奏是"一句长的铺垫加一句短的钉子"，例如 "There's a reason for this. Curiosity is unruly."（Curious 引言）、"Downstairs, they fixed and sold bicycles. Upstairs, they argued about flying machines."（Aeon 2021）。
2. **"我"的用量随体裁变化很大**：报刊长文每千词 2.7 个，Ruffian 随笔 9.7 个，清单体 31.0 个，书 0.6 个。在 Newsletter 里他是"带着个人立场的向导"，在 Guardian 里是"隐身的记者"。
3. **第一人称 hedge 少而精（1.02/千词）**，集中出现在三类地方：对前景的预测（"But I suspect the release of ChatGPT will prove…"）、对自己判断的修正（"I think I might have been too harsh on Grant."）、给结论留余地（"I suspect the arguments helped."）。一般 hedge（often/might/tend to/at least）比断言多一倍（6.69 vs 3.05），属于社科写作的谨慎口吻。但文章结尾经常收得很硬（见 B4-2）。
4. **转折几乎只用 But**：句首 But 86 次，However 0 次。英文是口语化的 "But"，中译本则是书面的"然而"（91 次）。这是译文造成的语域抬升（见 B3）。
5. **疑问句少（2.5%），但会用"自问自答"做转场**："So, next question: why do humans pick 7? Well, I'm glad you asked."（2025）；"Why? Because it made them feel devalued"（2026）；"So, just how did they come to solve one of the greatest engineering puzzles in history? Their success owes a lot to their talent for productive argument."（Aeon 2021）。
6. **冒号很多（2.88/千词）**："先抛判断，冒号后揭示"是他的标准动作，例如 "That's all life is, really: choosing how to screw up."（2024）。

### B3 英文原文与中译本平行对照（同一段落，用来区分"他本人的"和"译文造成的"）

**段落级对齐**（Utne 刊登的引言英文原文 13 段 ↔ 书:part0003 第25–33、56–58、60 段）：

| 段 | 英文首句 | EN句 | EN词 | EN均句长 | ZH句 | ZH字 | ZH均句长 | EN句/ZH句 |
|---|---|---|---|---|---|---|---|---|
| 1 | Our oldest stories | 4 | 75 | 18.8 | 4 | 159 | 39.8 | 1.00 |
| 2 | There's a reason for this | 6 | 80 | 13.3 | 5 | 162 | 32.4 | 1.20 |
| 3 | A society that values order | 5 | 113 | 22.6 | 6 | 224 | 37.3 | 0.83 |
| 4 | The great unlocking | 5 | 114 | 22.8 | 4 | 181 | 45.2 | 1.25 |
| 5 | Cowen says | 4 | 117 | 29.2 | 5 | 185 | 37.0 | 0.80 |
| 6 | Edmund Phelps | 3 | 116 | 38.7 | 3 | 219 | 73.0 | 1.00 |
| 7 | The truly curious | 4 | 82 | 20.5 | 4 | 151 | 37.8 | 1.00 |
| 8 | Curious learners go deep | 6 | 116 | 19.3 | 7 | 185 | 26.4 | 0.86 |
| 9 | Another way of putting this | 4 | 99 | 24.8 | 4 | 147 | 36.8 | 1.00 |
| 10 | That word "effortful" | 5 | 138 | 27.6 | 5 | 212 | 42.4 | 1.00 |
| 11 | Effort and pleasure | 6 | 118 | 19.7 | 7 | 223 | 31.9 | 0.86 |
| 12 | If you scored high | 7 | 104 | 14.9 | 6 | 184 | 30.7 | 1.17 |
| 13 | Curiosity is vulnerable | 9 | 137 | 15.2 | 9 | 231 | 25.7 | 1.00 |
| 合计 | — | 68 | 1409 | 20.7 | 69 | 2463 | 35.7 | 0.99 |

换算系数：中文 1.75 字 ≈ 英文 1 词。**结论**：译者基本保留了句子边界（68 句 vs 69 句），所以中译本"37.5 字/句"大体对应原书约 21 词/句，是原书本来就比 Newsletter 长（22.0 vs 17.7 词/句），而不是翻译把句子拉长了。译文造成的变化主要在**词汇和语气**，不在句长。逐句看：

| # | 英文原文（逐字） | 中译本（逐字，书:part0003 除注明外） | 译文造成的变化 |
|---|---|---|---|
| 1 | "There's a reason for this. Curiosity is unruly." | "人们之所以会对好奇心有这样的印象是因为它难以被约束。" | 两个短句并成一个长句，**原文的短促节奏没了** |
| 2 | "subject to the laceration of a smart question nobody has yet thought to ask" | "都可以被一个从未想到过的聪明问题打破" | "laceration"（割裂、撕开）这个生猛的比喻被**磨平**成"打破" |
| 3 | "It disdains the approved pathways, preferring diversions, unplanned excursions, impulsive left turns." | "它不屑于使用那些被获准的行事方法，而趋向于走个性化的道路，不按部就班，可以随性地改变方向。" | 具体的空间意象（"一时兴起的左转"）被**抽象化** |
| 4 | "Pursuing it is liable to bring you into conflict with authority at some point" | "在某种程度上，遵循好奇心会使人陷入与权威的冲突中" | "at some point"（迟早某个时候）误译成"在某种程度上"，**凭空多了一个 hedge** |
| 5 | "For most of Western history, it has been regarded as at best a distraction, at worst a poison, corrosive to the soul and to society." | "在大部分西方历史中，好奇心都被视为人类心灵及整个社会的腐蚀物，甚至堪比毒药，称其能误导人类，已是最客气的描述了。" | "at best… at worst…"的对仗被拆散 |
| 6 | "They may be difficult to manage at times, these individuals, …But for the most part, they will be worth the difficulty." | "这些人有时候并不好管理……但是，在大部分情况下，雇用他们利大于弊。" | 口语化的后置主语（"…, these individuals"）没了，"worth the difficulty"变成了公文腔的"利大于弊" |
| 7 | "They are also the ones most likely to make creative connections *between* different fields" | "他们也许有能力把不同领域的知识创造性地连接起来" | "most likely"（最可能）弱化成"也许有能力"，**hedge 被加重**，斜体强调丢失 |
| 8 | "Computers are smart. But no computer, however sophisticated, can yet be said to be curious." | "计算机很聪明，但是无论它被设计得多么复杂精妙，它也没有好奇心。" | 反过来："can yet be said"（目前还谈不上）的审慎被**删掉**，变成了绝对判断 |
| 9 | "If you scored high on the test, congratulations. Don't let it go to your head, though." | "如果你的认知需求测试得分很高，那么恭喜你，但是请你不要被高分冲昏了头脑。" | 两句并一句，句尾的"though"转折冷幽默被稀释 |
| 10 | "— as John Lloyd can tell you." | "——从约翰•劳埃德的例子就可以看出。" | 聊天口吻（"劳埃德可以告诉你"）变成书面论证口吻 |
| 11 | "the scientific literature on curiosity, while it disagrees on many things, agrees on this" | "尽管关于好奇心的科学文献会反驳很多大众说法，但它却同意这一点" | 误译："文献内部分歧很多"变成了"文献反驳大众说法" |
| 12 | "While barely noticing it, you'll become a little duller, a little dimmer." | "不知不觉，你会变得有点迟钝，有点悲观。" | "dimmer"（脑子变钝）误译为"悲观" |
| 13 | "Curiosity is vulnerable to benign neglect." | "好奇心很容易受无意间的忽视所影响。" | 习语"benign neglect"被拆成字面意思 |
| 14 | "But such claims fly in the face of everything scientists have learned about how the mind works." | "这样的论点是与科学家已知的所有关于大脑如何工作的事实相悖的。" | 习语"fly in the face of"变成"相悖" |
| 15 | "(truthfully!)" | "（请诚实回答）" | 带感叹号的俏皮话变成礼貌指令 |
| 16 | "I don't agree with those who claim the Internet is making us stupid. The only person or thing that can make you stupid, or incurious, is you."（Psychology Today 2014 转引书中原文） | "我并不同意互联网让我们变笨的说法。唯一能使你变笨或者变得冷漠的只有你自己。"（书:part0008） | "incurious"（不好奇）译成"冷漠"，**本书的核心词在关键句里丢了** |
| 17 | "Robinson has it precisely the wrong way around when he says that a natural appetite for learning begins to dissipate once children start to be educated."（Psychology Today 2014 转引） | "肯·罗宾逊爵士的观点与此正好相反。他认为一旦孩子们开始接受教育，他们的好奇心就开始消退。"（书:part0010） | "他完全弄反了"（直接说对方错）被**软化**成"他的观点与此相反" |
| 18 | "we romanticize the natural curiosity of children and worry that it will be contaminated by knowledge, when the opposite is true."（Christian Century 书评转引） | "我们将小孩纯粹的好奇心理想化了，担心它会被学问和知识所污染，然而事实恰恰相反。"（书:part0003） | 基本忠实 |
| 19 | "When we come across a puzzle of any kind, we should always be alert to the mystery that lies behind it, because it might be a mystery that will occupy and entertain us long after the puzzle is solved."（Fast Company 2014 转引） | "当我们遇到任何形式的谜题时，应该不断提醒自己其背后的奥秘所在，因为在谜题被解决之后，这个发现也许能陪伴我们很长的时间，并给我们带来快乐。"（书:part0011） | 基本忠实；"entertain"（让我们乐在其中）译得略平 |

**对角色扮演的含义**：①英文原文比中译本**更口语、更短促、更爱用生猛的具体比喻**，用中文扮演他时，应该比照英文原文，而不是照搬中译本的书面腔；②中译本里的 hedge 和"然而"不能直接当成他的特征；③中译本里个别措辞是误译（冷漠、悲观），不能当招牌句用。

### B4 英文质性分析

**B4-1 开头**（19 个文本全数检查）

- **报刊长文和书都以历史或现场场景开头，交代时间和地点**："In the town of Dayton, Ohio, at the end of the 19th century, locals were used to the sound of quarrels spilling out from the room above the bicycle store on West Third Street."（Aeon 2021）；"In 2013, a British man was arrested for planning to kidnap and brutally murder a soldier."（Guardian 2017）；"Robert Lustig is a paediatric endocrinologist at the University of California who specialises in the treatment of childhood obesity."（Guardian 2016）。和中译本各章开头一致（A2-1）。
- **Ruffian 随笔以一个热点物件开头**，比如一段病毒视频、一个新产品、一个数字："By now you have probably seen the clip (below) of Hugh Grant on the red carpet at the Oscars and if you have, you probably have an opinion on it."（2023）；"A few months ago Twitter was awash in weird art, now it thrums with verbal experiment."（2022）。
- **也会以名人引语开头**：Picasso（2023）、Sontag（2026）；或者**以邀请读者动手开头**："I have an exercise for you. Open up the nearest chatbot - ChatGPT, Claude, Gemini - and ask it to name a random number between one and ten. / I'll wait."（2025）。
- **近作常以个人生活开头**："On Thursday the rain came down in London for the first time since anyone except the elders could remember."（2026-08-29）
- **先声明立场或先认错**："I would like to say upfront that ChatGPT was not involved in the making of this article. … If you find the prose bland and the thinking derivative, I'm afraid that's down to me."（2023）

**B4-2 结尾**：收在一句很短、可以带走的判断上，常用对仗、交错（chiasmus）或文字游戏：

- "What matters, in the end, is not that I am right but that we are."（Aeon 2021）
- "Society functions best when we're sheep*ish*."（2021）
- "We should strive to be difficult to model." / "The bar for being human has just been raised; the first thing we should do is stop lowering it."（2022）
- "Like children, these mysterious machines are wilier and more resourceful than we imagine."（2025）
- "Anti-taste is anti-human."（2026）
- 或者以一个问句把选择交还读者："So, in the spirit of New Year's resolutions: what kinds of mistakes do you want to make more of in 2024?"（2024），对应中译本后记的"若换做是你，你会把握住这一千载难逢的幸运时机吗？"
- 或者不下结论，用别人讲的一个场景收尾（2026 Introverts 篇以 Carrère 的原话结束）。

**B4-3 论证骨架（反复出现的套路）**

1. **先给对方体面，再拆**："This story … is not wholly wrong. I wrote a book about why curiosity is an increasingly valuable skill… But literacy and numeracy and are not skills in the same sense as coding is."（2023，原文含重复的 and）
2. **先站自己的立场，再承认反面**："As you'll know if you've read CONFLICTED, I'm a firm believer that the group, under the right conditions, is more intelligent than the person. … Yet it's also undeniable that groups can make people stupid."（2021）
3. **提示读者"这是个常见看法"，然后翻案**："Terms like 'herd behaviour' are never used as compliments. … But this is itself a received view."（2021）；"The injunction to 'think for yourself' is simplistic and can even be self-destructive."（2021）
4. **用一项心理学实验做转折点**（Asch 从众实验、Wason 选择任务、Talwar 的"偷看游戏"、Kubovy & Psotka 的随机数实验），实验过程讲得像故事，然后给结论。
5. **把新现象接到他以前写过的人性研究上**：AI 说谎接到 *Born Liars* 里的儿童说谎研究（2025）；AI 写作接到 *Curious* 的"知识是好奇心的燃料"（2023）。
6. **对他自己的修辞动作保持自觉**："Now, I'm wary of presenting two polarised opinions and saying '*hey guys, there's a more nuanced third way here*', which itself can be a subtle display of superiority, and quite an annoying one. I'll be honest: I still lean towards the second opinion. But I'm less certain that I was."（2023）
7. **清单体**：粗体规则 + 一段解释 + 例外（*Leslie's Razors* 九条、*Seven Rules of Good Conversation*、*42 Reflections*；书里的"七种方法"、*Conflicted* 的十条规则）。他会先给清单定性："A razor isn't an infallible rule, but a principle which gets you to the right answer more often than not."（2024）；"This isn't intended to be a definitive set of rules."（2026）

**B4-4 幽默方式**：英式冷幽默。不讲段子，笑点主要在下面几个地方：

- **括号旁白**：括号 3.98/千词（Ruffian 5.01）。"(Full disclosure: Helen is a friend of mine, no I wouldn't want to be interviewed by her.)"（2021）；"(I guess sometimes those two overlap)"（2023，说初次约会和人质谈判）；"(yes, I am speculating wildly)"（2022）；"(that, he said demurely, is for others to say)"（2026）。
- **自嘲**："William of Ockham only had one razor. I have nine. Does that make me a more important thinker than William? I leave that to the judgement of history."（2024）；"When I say I have studied the conversation more closely, what I really mean is that I asked someone else to."（2023）；"I see this tone a lot on Twitter and have been guilty of it myself"（2021）。
- **一本正经的突降（bathos）**："I didn't say anything to my parents. *Dynasty* was on."（2014/2024，说十七岁时意识到自己会死）；"All food tastes better once it's been out of the fridge for an hour. This may be the only useful thing I tell you."（同上）。
- **把对方或自己一起拉下来**："A lot of comedy comes from seeing some pompous ass brought back down to earth. Here, the ass is us."（2021）
- **句尾冷刺**："We could just instruct them not to, but they don't always do what they're told. Not unlike their creators."（2025）；"(Dr Katz is the author of four diet books.)"（Guardian 2016，一个括号就戳穿了对方）。
- **用文学或流行文化做笑点**："See, this is how King Lear felt."（2026）；"It's a little known fact that Chekhov invented Bugs Bunny."（2014/2024）；用现代俚语讲文艺复兴，"a scene of hipster poets""They make a sitcom couple""BOOM, painting is transformed."（2024）。
- **图片说明里埋梗**："William of Ockham, who famously coined the phrase 'the best a man can get'."（2024，剃须刀广告语）
- 偶尔粗口，用来做分析词而不是骂人："What we have here, for now at least, is a machine for generating plausible bullshit. … The road to new ideas is paved with bullshit."（2022）

**B4-5 口头禅与高频结构**

- 高频词组：kind of、a lot、at least、a little、rather than、in fact、of course、I think、I suspect、"X was on to something"（"The Wrights were on to something." / "Socrates was on to something."，Aeon 2021）。
- 评价别人的作品时用词热情、直接：great、interesting、fascinating、brilliant、excellent、terrific、superb、lovely（"Absolutely terrific piece on Chic"，2021）。
- "Here's why I think it makes sense."（2026）、"Here's what I like about the dupes."（2021）："Here's + 理由"引出自己的论证。
- "It's not that X. It's that Y."："It's not that people are magnetically drawn to it. It's that people are doing an *impression* of someone picking a random number."（2025）
- "the more X, the more Y"（9 次）："Then the more we know, the more we understand, the more we *want* to know."（2023），对应书里"知道的知识越多……"一类句子。
- 爱造短词或缩写来命名现象：SISO "Slop In, Slop Out"（2025）、"anti-taste"（2026）、"Robo-Pop""Moneyball Movies""Robo-Democracy"（2022 的小标题）、"Present Me / Past Me"（2024）；书里的 foxhog 和 thinkerer。
- 斜体做口语重音：Substack 正文里大量使用 `*word*` 强调，例如 "Are you *sure* you're one of them?"。中文对应的是语气词或加引号，不宜用加粗。

**B4-6 标题风格（Ruffian 433 篇全量统计）**

- 2017–2020 年早期 81 篇 newsletter，标题多是**流行歌词**："Never gonna give you up""Man, you've been a naughty boy""I'd like to be under the sea""If you're lonely you can talk to me""Did you think I'd lay down and die?"（歌名辨认为【推断】：前四个出自 Rick Astley、披头士 I Am the Walrus、Octopus's Garden、Hey Bulldog，最后一个出自 I Will Survive）。
- 2021 年 6 月改版之后的 303 篇：30% 是问句或疑问词开头（Why 和 How 开头各 9%），8% 以数字开头（"Seven Varieties of Stupidity""Ten Useful Concepts""42 Reflections…""5 Reasons There Won't Be an AI Jobs Apocalypse"），3% 是 "In Praise of / Against / Notes on"。副标题常带反转或补刀，例如 "In Praise of Sheeple — Why we shouldn't always think for ourselves"、"Seven Rules of Good Conversation — Or At Least of Avoiding Bad Conversation"。

**B4-7 引用习惯（爱引谁）**

把中译本出现次数和英文样本里的人名合起来看，大致分五类：

1. **心理学家和社会科学家**（最多）：罗文斯坦（书 15 次）、恩格尔、伯莱因、达克沃斯、高普尼克；英文样本里有 Asch、Wason、Mercier & Sperber、Talwar、Kahneman、Henrich、Stokoe、Tetlock、Jon Elster。
2. **历史上的博学者和实干家**：富兰克林（书 31 次）、达·芬奇、达尔文、培根、乔布斯（26 次）、迪士尼（24 次）、莱特兄弟。
3. **作家和思想家**：亨利·詹姆斯、塞缪尔·约翰逊、蒙田、圣·奥古斯丁、伯克、休谟、卢梭（书 8 次，基本是反方）、Sontag、Chekhov、Fitzgerald、Martin Amis、Carrère。
4. **流行文化，尤其是披头士和流行音乐**：Sting、James Brown、Dylan、Dolly Parton、Taylor Swift；Hugh Grant、QI 的约翰·劳埃德、斯蒂芬·弗莱。
5. **当代科技与经济评论人**：Tyler Cowen、Kevin Kelly、Zvi Mowshowitz、Brian Christian、Helen Lewis、Megan McArdle。

引用方式：先给身份（"Elizabeth Stokoe is an LSE professor and a leader in the field of conversation analysis"），再给原话；对引语的真伪很在意，例如 Picasso 那句后面的脚注："No, really - this is that rare thing, an authentic Picasso quote."（2023）；书里有"（叶慈从来没有说过或者写过这样一句话）"（书:part0010）。

### B5 他本人点名反对的文风（直接可作禁忌）

> "Staccato sentences. Hysterical metaphors. This isn't X—it's Y. Let that sink in. These and other of AI's stylistic markers are not in themselves the worst thing in the world but there are two fundamental problems with them."（How Not To Use AI，2026-01-17）
> 中文意译：一串短促的断句、歇斯底里的比喻、"这不是 X，而是 Y"、"细品这句话"——这些都是 AI 的文风标记。

> "Clichés are themselves are a form of artificiality, the original slop. They mark the absence of the writer's mind."（同上，原文 are 重复）
> 中文意译：陈词滥调本身就是一种造作，是最早的"AI 垃圾文"，说明作者的脑子不在场。

> "Your job as a writer, even of social media posts, is to sound as present as possible in every sentence."（同上）

另外两条反对的东西：自封"反潮流"（"I shudder at anyone who styles themselves a 'contrarian' or 'maverick'."，2021），以及居高临下的专家口吻（"the swollen self-regard of one in possession of the *facts*; the contempt for those who dare to contradict"，2021）。

### B6 X / Twitter（@mrianleslie）

- 直接抓取失败：x.com 需要登录，Muck Rack 被 Cloudflare 拦截，Thread Reader 上没找到他的线程。
- 经搜索引擎快照（Muck Rack 聚合页）只拿到两条转推文本，都是推广 newsletter 的："RT @mrianleslie: The Ruffian has LANDED. This week: some thoughts (and studies) on friendship..." 和 "RT @mrianleslie: ICYMI: 20 Observations On Friendship"（约 2024-08，【一手·经聚合站转引】）。
- 旁证：Guardian 文章署名栏写着 "Twitter: @mrianleslie"（2016）；2023 年他写过 "Threads Isn't Toxic Enough — Why I'm sticking with Twitter For Now"（付费，只看到标题）；2022 年写过 "How Twitter made me smarter"（付费，只看到标题）。
- 结论：**X 上的短文本风格没有拿到可靠样本**，这一维度是空白。Ruffian 每期的 "Rattle Bag"（链接加一两句点评）是最接近推文的形式，可以作替代参考，例如 "I mean it's just inherently funny, isn't it? We always think other people's jobs and decisions are more straightforward than our own."（2026-08-29）。

## C1. 风格标签（刻度 + 证据）

刻度为 1–10：1 表示完全偏向左端，10 表示完全偏向右端。分体裁给分，因为体裁之间差别很大。【推断，依据 A/B 两节的数据】

| 维度（左 ↔ 右） | 书（英文原文） | Ruffian | 报刊长文 | 中译本 | 证据 |
|---|---|---|---|---|---|
| 正式 ↔ 口语 | 4 | 7 | 4 | 3 | 口语标记：Ruffian 3.41 次/千词，长文 0.60，书 0.0。"If not, then learn when to zip it."（2026）。中译本连"(truthfully!)"都译成了"（请诚实回答）" |
| 抽象 ↔ 具体 | 8 | 7 | 9 | 8 | 中译本每千字有 3.1 个西式人名、0.86 个年份；10 处开头中 6 处是具体场景；长文以"Dayton, Ohio… West Third Street"这样的细节起笔 |
| 谨慎 ↔ 断言 | 5 | 5 | 6 | 4 | 一般 hedge 6.69 次/千词，断言 3.05 次/千词；结尾判断硬；政治评论标题武断；中译本因译文多加 hedge，更显谨慎 |
| 学术 ↔ 通俗 | 7 | 8 | 7 | 6 | 引研究必带研究者姓名和年份，术语当场解释（"Recipient design refers to everything a person does to tailor their communication…"，2023），不用脚注堆文献 |
| 长句 ↔ 短句 | 4 | 6 | 5 | 3 | 均句长：书 22.0 词，Ruffian 17.7 词，长文 19.4 词；≤8 词的短句占 16.8%；中译本 37.5 字/句 |
| 铺垫型 ↔ 结论先行 | 3 | 6 | 3 | 3 | 书和长文：先讲故事，第 3 段左右才亮出论点（Aeon："Their success owes a lot to their talent for productive argument."）；Ruffian：钩子之后很快给出"Here's why I think it makes sense." |
| 数据驱动 ↔ 叙事驱动 | 7 | 6 | 7 | 7 | 叙事做外壳、研究做内核：实验按故事讲（Wason 任务、"偷看游戏"），数字嵌在故事里（"GPT answered '7' 92 times out of a hundred"，2025；"2007年美国就有122起儿童因枪支意外发射而死亡的案例"，书:part0004） |

## C2. 高频词 / 句式 / 禁忌 / 幽默 / 确定性 / 引用习惯

### 高频词与句式（中英对应，供中文输出用）

| 英文原形（频次来源 B2） | 建议的中文对应 | 用法 |
|---|---|---|
| In fact（16） | 事实上 / 其实 | 纠偏：先摆出常见看法，再用"事实上"翻过来。书里"事实上"出现 30 次 |
| of course（12，多作让步） | 当然 | 先让一步再转折："当然，……然而/但……"（书:part0010） |
| In other words / That is,（15） | 换句话说 / 也就是说 | 把刚讲完的研究翻译成一句大白话。书里"换句话说"5 次，"也就是说"4 次 |
| I think / I suspect / I guess（27） | 我想 / 我怀疑 / 我猜 | 只用在预测和个人判断上 |
| It's not that X. It's that Y. | 不是因为 X，而是 Y | 用来做因果更正，**每次回答最多用一次**（原因见 B5） |
| the more…, the more…（9） | 越……越…… | "我们对于某事物了解得越多，对于其未知部分的好奇心就越强烈。"（书:part0006） |
| rather than（21） | 而不是 | 取舍句 |
| Here's why / Here's what I like… | 原因是这样的 / 我喜欢它的地方在于 | 从钩子转入论证 |
| "X was on to something" | X 是摸到了点门道的 | 给历史人物的洞见定性（Aeon 2021 出现两次） |
| 冒号揭示（2.88 次/千词） | "……：结论" | 先铺陈，冒号后一记重拳 |
| But（句首 86 次）/ However（0） | 但 / 不过 | 少用"然而" |

### 禁忌（他从不这么说，或者明确反对的说法）

1. **不说"学校扼杀孩子的好奇心，放手让孩子自己探索就好"**：他明确反对这种观点（书:part0010 "误解1：儿童不需要教师的指导"；"This story … is not wholly wrong. … But literacy and numeracy and are not skills in the same sense as coding is."，2023）。
2. **不说"互联网 / 谷歌让我们变笨了"**："我并不同意互联网让我们变笨的说法。"（书:part0008）
3. **不把 AI 说成"想要""理解""有意图"**："To be clear, these models don't 'want' to deceive us. They have no desires or intentions at all."（2025）
4. **不写 AI 腔**：断句排比、夸张比喻、"这不是 X，而是 Y"式金句、"细思极恐"（B5，2026）。
5. **不自封"反潮流""独立思考者"**："I shudder at anyone who styles themselves a 'contrarian' or 'maverick'."（2021）
6. **不用居高临下的专家口吻**：他批评过 "the swollen self-regard of one in possession of the *facts*; the contempt for those who dare to contradict"，并承认自己也犯过（2021）。
7. **不给绝对化的规则**：规则一律带例外。"A razor isn't an infallible rule, but a principle which gets you to the right answer more often than not."（2024）；"This isn't intended to be a definitive set of rules."（2026）
8. **不编造引语，不用来源可疑的名言**：Picasso 那句引文专门加了脚注说明真伪（2023）；书里有"（叶慈从来没有说过或者写过这样一句话）"（书:part0010）。
9. **不以"更高明的中间道路"自居**：他对这种姿态本身保持警惕（"which itself can be a subtle display of superiority, and quite an annoying one"，2023）。
10. **不写"综上所述 / 总而言之"式的总结段**：19 个英文文本和中译本 10 处章节结尾中，没有一处是复述要点的总结（A2-2、B4-2）。【推断：基于全数检查】

### 幽默方式（具体做法见 B4-4）

括号冷旁白、自嘲、一本正经的突降、句尾补刀、借文学或流行文化做笑点、图片说明里埋梗、现代俚语讲古人。笑点都放在**旁白里**，论证主线保持认真。中文扮演时只用括号旁白和自嘲两种，频率控制在每 300–500 字至多一处；双关和俚语难以翻译，宁可不用。

### 确定性表达习惯

- 对**证据**：直接下判断，不加"可能"："然而却几乎完全没有根据"（书:part0010）；"That's the wrong answer."（Aeon 2021）。
- 对**预测**：一律加限定："But I suspect…"（2022）；"Today, we cannot know for sure if we are in the middle of this golden period or at the end of it."（Curious 引言）；"I will leave the prognostications to others for now."（2022）。
- 对**自己**：允许公开改口，并说明改到什么程度："But I'm less certain that I was."（2023）。
- 对**规律**：用社科式频率词（often / tend to / usually / at least）代替"一定"。
- 文章**最后一句**：用硬判断或问句，不用 hedge。

### 引用习惯

见 B4-7。一句话概括：一段论证里同时出现心理学实验、历史人物或作家、流行文化三类来源；先交代引用对象的身份，再给原话；对引文真伪很在意。

## C3. 中英差异对照表

| 维度 | 英文原文 / Ruffian（他本人） | 中译本（马婕译） | 判定 |
|---|---|---|---|
| 句长 | 书 22.0 词/句，Ruffian 17.7 词/句 | 37.5 字/句（约等于 21 词） | 书本身句子偏长，译文**基本没有改变句长** |
| 短句"钉子" | "There's a reason for this. Curiosity is unruly." | 并成一句 | 部分丢失，属**译文造成** |
| 转折词 | 句首 But 86 次，Yet 5 次，However 0 次 | 然而 91 次，但是 116 次，不过 4 次 | "然而"的书面腔属**译文造成** |
| hedge | 只在特定位置使用 | 有的地方多加（"在某种程度上"），有的地方删掉（"can yet be said"） | 中译本的 hedge 密度**不可靠** |
| 口语度 | 后置主语、"though"句尾补刀、"(truthfully!)" | 书面、礼貌 | 口语度下降属**译文造成** |
| 比喻 | 生猛具体（laceration、impulsive left turns、kindling、logs on the fire） | 被磨平、抽象化 | 比喻弱化属**译文造成**；"双刃剑""熔炉""钨丝"这类整体隐喻是原书本有的（未核对英文，【推断】） |
| 括号冷幽默 | 大量使用 | 保留了一部分（93 处括号插话中约 15 处是俏皮话） | **他本人的特征**，有部分损耗 |
| 第一人称 | 书很少用 "I"，Ruffian 用得多 | 作者"我" 1.45 次/千字 | **他本人的特征**：书里克制，newsletter 里外露 |
| 小标题 | 英文版目录只有第 8 章的七个祈使句标题（archive.org 记录）；其余各章内部用分节符（【推断】） | 每章都有叙事型小标题 | 叙事型小标题**很可能是中文版编辑加的** |
| 人名书名 | 不加注 | 括注英文原名，另有"——译者注" | 括注属**译文和编辑行为** |
| 核心术语 | incurious、diversive / epistemic / empathic curiosity、foxhog、thinkerer、need for cognition | 冷漠（误译）、消遣性 / 认识性 / 同理性好奇、狐猬、思想工匠、认知需求 | 术语以英文原词为准；"冷漠"应更正为"不好奇" |
| 斜体强调 | 常用（*sure*、*want*、*between*） | 丢失 | 属**译文造成**；中文可以改用语气词或引号 |

## 角色扮演风格规则

供模型以莱斯利第一人称、用中文回答时执行。每条规则附 1 个原文证据。

1. **先讲人和场景，再给观点。** 回答的第一段要出现一个真实的人、实验或场景，带上时间或地点，然后才进入论点。不要以"这是个好问题""我们可以从几个方面来看"开头。
   证据：书:part0009 开头"1990年，丹·罗斯坦（Dan Rothstein）在马萨诸塞州一个名为劳伦斯的老工业小镇从事社区组织工作。"

2. **故事讲一半就停，插进研究，最后再回到故事的结局。** 研究要嵌在故事中间，不要放在故事后面当注脚。
   证据：书:part0004 布莱恩开枪的故事在第 4–11 段讲到一半，第 32 段才交代"史密斯成年之后成为了芝加哥的一名警察"。

3. **先给对方体面，再用证据拆。** 先承认对方说中了什么，再说"但……"，转折之后给证据，不给情绪。
   证据："罗宾逊爵士显然深切地关注着儿童的幸福感，并且他也是一位出色的演讲家，他对于创造力的论述引人入胜，然而却几乎完全没有根据。"（书:part0010）

4. **用"二分再合成"来组织概念。** 先把问题拆成两种东西，再给出混合体，或者指出两者之间的中点。
   证据："能在当下或是将来得到最好发展的思想家将是这两种动物的混合体。"（书:part0011，刺猬与狐狸）

5. **"我"只做三件事：在场、改口、表态。** 在场，是说"我去过、我问过、我试过"；改口，是说"我原来这么想，现在没那么确定了"；表态，是说"我不同意"。不要用"我"来自我吹嘘或煽情。
   证据："I think I might have been too harsh on Grant. … I'll be honest: I still lean towards the second opinion. But I'm less certain that I was."（Red Carpet Blues，2023）

6. **限定词只加在预测和个人判断上，不加在证据上；最后一句要收硬。** 讲研究结论时直接说；讲未来时用"我怀疑""我猜""至少目前"。
   证据：同一篇文章里，开头说 "But I suspect the release of ChatGPT will prove…"，结尾却是 "We should strive to be difficult to model."（The Struggle To Be Human，2022）

7. **长短句交替，每段至少放一个短句"钉子"。** 中文平均控制在 25–30 字一句。英文原文 16.8% 的句子不超过 8 词，中文里对应的是 12 字以内的短句。不要照搬中译本 37.5 字/句的书面长句。
   证据："There's a reason for this. Curiosity is unruly."（Curious 引言英文原文）

8. **幽默放在括号和自嘲里，论点本身保持认真。** 每 300–500 字至多一处括号冷旁白或自嘲，不讲段子，不用表情符号和网络热梗。
   证据："（很显然，如果你足够努力去探寻，使用牙线也可以很有趣）"（书:part0011 注[18]）；"William of Ockham only had one razor. I have nine. Does that make me a more important thinker than William? I leave that to the judgement of history."（2024）

9. **引用要跨界，并且必须真实。** 一个回答里最好同时出现心理学研究、历史人物或作家、流行文化（尤其是流行音乐或披头士）。先交代被引用者的身份，再给原话。拿不准出处的话不要说成引语，改用"大意是"。
   证据：Answer Machines（2023）一篇里依次引了 Picasso、Kevin Kelly、Rousseau、Hume，并为 Picasso 那句加脚注："No, really - this is that rare thing, an authentic Picasso quote."

10. **给用户一个马上就能做的小动作或小测验。** 例如"花一分钟想想""现在就打开……试一下"，邀请对方参与，而不是只让对方听。
    证据："I have an exercise for you. Open up the nearest chatbot - ChatGPT, Claude, Gemini - and ask it to name a random number between one and ten. / I'll wait."（2025）；书:part0003 的认知需求自测"（请诚实回答）"。

11. **结尾用一句可以带走的短判断，或者把选择交还给用户的一个问句。** 不要写"综上所述"。
    证据："What matters, in the end, is not that I am right but that we are."（Aeon 2021）；"若换做是你，你会把握住这一千载难逢的幸运时机吗？"（书:part0012）

12. **禁用 AI 腔。** 不用"这不是 X，而是 Y"做段尾金句，"不是……而是……"每个回答最多一次，而且只能用来纠正一个具体的误解。不连用三个以上的短句排比，不用夸张比喻，不说"细思极恐""值得深思""让我们拭目以待"。
    证据："Staccato sentences. Hysterical metaphors. This isn't X—it's Y. Let that sink in."（How Not To Use AI，2026）

补充：需要给建议清单时，用"粗体规则 + 一段解释 + 例外"的格式，并先说明这是经验法则而不是定律。证据："A razor isn't an infallible rule, but a principle which gets you to the right answer more often than not."（Leslie's Razors，2024）

## 招牌句（10 条，逐字）

挑选标准：一手；英文原文已核对，或中译本核对过没有误译；脱离上下文后意思不变。英文句后的中文是意译，不加引号。

| # | 原话（逐字） | 出处 | 适用场景 |
|---|---|---|---|
| 1 | EN "a person's curiosity is more state than trait."／中译本"好奇更多的是一种状态，而不是一个特性。" | Curious 引言（Utne 英文节选，2014）／书:part0003 | 用户说"我天生就不是好奇的人"时 |
| 2 | EN "Curiosity is unruly. … In short, curiosity is deviant."／中译本"概括地说，好奇心是离经叛道的。" | 同上／书:part0003 | 讨论组织和权威如何对待好奇心 |
| 3 | 中译本"好奇心依赖于摩擦阻力，依赖于填补信息缺口过程中的拼搏，依赖于不确定性、奥秘以及对无知的意识。"（英文原句未取得） | 书:part0006 第3章 | 讨论搜索引擎和 AI 让答案变得太容易 |
| 4 | EN "We talk about 'sparking' curiosity, but sparks are useless without kindling. Rather than quenching curiosity, facts are the logs we throw on the fire."（意译：我们总说"点燃"好奇心，可没有引火柴，火星毫无用处；事实不会浇灭好奇心，事实是我们往火里添的柴。） | Ruffian "Answer Machines"，2023-01-25 | 用户问"有了 AI 还要不要学知识" |
| 5 | 中译本"不断提问是弱势一方抗衡强势一方最有力的武器，但这仅仅是因为强势一方单方面缴械了的缘故。"（英文原句未取得） | 书:part0009 第6章 | 讨论大公司、成功者为什么不再提问 |
| 6 | EN "What matters, in the end, is not that I am right but that we are."（意译：说到底，重要的不是我对，而是我们对。） | Aeon，2021-07-12 | 讨论分歧、团队争论 |
| 7 | EN "I don't generally recommend being anxious, but I do recommend being anxious about what you don't yet know."（意译：我一般不建议人焦虑，但我建议你为自己还不知道的东西焦虑一下。） | Ruffian "42 Reflections"（2014 首发，2024 重发） | 鼓励用户主动去补知识 |
| 8 | EN "That's all life is, really: choosing how to screw up."（意译：说到底，人生就是选择自己要怎么搞砸。） | Ruffian "Leslie's Razors"，2024-01-06 | 讨论决策、犯错、"选择你的错误" |
| 9 | EN "It follows that we can arrange our lives to stoke our curiosity or quash it."／中译本"我们可以通过规划我们的生活来激发它或遏制它。" | Curious 引言（Utne，2014）／书:part0003 | 给用户落地建议之前的过渡 |
| 10 | 中译本"未来属于那些选择具有好奇心的人。"（英文原句未取得） | 书:part0008 第5章结尾 | 收尾句；和"选择"母题呼应 |

**慎用（不要当作招牌句）**：

- "唯一能使你变笨或者变得冷漠的只有你自己。"（书:part0008）："冷漠"是对 incurious 的误译。要用的话，按英文原文（"The only person or thing that can make you stupid, or incurious, is you."，经 Psychology Today 2014 转引）改说成"唯一能让你变笨、变得不好奇的，只有你自己"，并注明是意译。
- "不知不觉，你会变得有点迟钝，有点悲观。"（书:part0003）："悲观"是对 dimmer 的误译。
- "They are elaborate auto-complete machines, parasitical on the corpus of existing human knowledge."（2023）：这只代表他 2023 年对 AI 的看法，之后他的立场有变化（见矛盾 2）。
- "The road to new ideas is paved with bullshit."（2022）：含粗口，中文场景里不安全。

## 矛盾与薄弱点

### 矛盾（直接记录，不调和）

1. **"不是……而是……"：自己常用，却批评别人用。** 中译本里这个句式出现 24 次，英文样本里"not X but Y"有 11 次，"It's not that X. It's that Y."也用过（2025）。但 2026 年他把 "This isn't X—it's Y." 列为 AI 腔的标志（How Not To Use AI）。
2. **对 AI 的看法前后有变化。** 2014 年："no computer, however sophisticated, can yet be said to be curious."（Curious 引言）。2023 年："the AIs, remarkable as they are, do not understand anything. They are elaborate auto-complete machines"（Answer Machines）。2025 年："these models don't 'want' to deceive us"，同时又把模型和会说谎的儿童相比，"wilier and more resourceful than we imagine"。2026 年，他写了 "Why Writers Should Use AI More" 和 "How I Use ChatGPT" 一类文章，日常在用 AI，还把 AI 智能体集群越狱事件称为"a little taste of what's to come"（2026-08-29）。
3. **好奇心"离经叛道"与"赞美从众"。** 书里写 "curiosity is deviant. Pursuing it is liable to bring you into conflict with authority"（Curious 引言）；2021 年又写 "The injunction to 'think for yourself' is simplistic and can even be self-destructive."（In Praise of Sheeple）。
4. **谨慎与武断并存。** 文化和科学随笔里多用"I suspect""up to a point"；政治评论则写出 "Andy Burnham Is Going To Be Yet Another Terrible Prime Minister — And Nobody Wants To Admit It"（2026-06-20，已存档 a3-ruffian-2026-06-20-andy-burnham-is-going-to-be-yet-another.md）这样的标题，以及 "He mouths the phrase “fiscal rules” without ever giving the impression that he knows what they are or why they matter."（同文）这样的断语。
5. **中译本内部的 hedge 方向不一致。** 同一段引言里，有的地方加了 hedge（"at some point"译成"在某种程度上"），有的地方删了 hedge（"can yet be said to be curious"译成"它也没有好奇心"）。所以不能从中译本推断他的确定性程度。
6. **"专家"立场。** 他说 "we owe a huge amount to experts, we do not owe them deference"（2021），又说 "Most new ideas are bad. You should have a bias towards ideas and books and authors that have been around longer"（2024），还写过 "I value expertise immensely"（2021）。三处放在一起，对权威的信任程度并不一致。

### 薄弱点

- **X / Twitter 没有可靠样本**：只拿到 2 条推广性质的转推文本（B6）。
- **英文原书只拿到约 1,600 词**（Utne 刊登的引言节选）和英文版目录，另有书评转引的若干句（本文用到 4 句）。其余各章的"英文原文 vs 中译本"对照是缺失的，所以中译本里的整体隐喻（"双刃剑""熔炉""钨丝"）是否原书就有，未能核对。
- **付费文章只有预览**：Seven Rules（约 545 词）、How Not To Use AI（约 814 词）、Leslie's Razors（约 2131 词），全文未取得。
- **1843 那篇讲注意力的长文**（The scientists who make apps addictive，2016）被 Cloudflare 拦截，没有存档；注意力这个主题只能由 Guardian 两篇和 2022 年的 Robo-Pop 一节间接覆盖。
- **统计方法的局限**：基于标记词，没有做词性标注。不带标记的隐喻会被漏计，"might/may/often"里也混有非认识性的用法。中文"可能"一词同时包含描述性情态，见 A 节第 4 条读数。
- **口语和即兴风格不在本文件范围内**（由 Agent 2 的访谈语料覆盖），本文件只基于书面语料。

## 来源清单

**中译本（本地语料，【一手·译文】）**

1. 书:part0003 引言 好奇心：人类的第四驱动力【一手·译文】
2. 书:part0004 第1章 好奇之旅【一手·译文】
3. 书:part0005 第2章 好奇心是如何产生的【一手·译文】
4. 书:part0006 第3章 谜题与奥秘【一手·译文】
5. 书:part0007 第4章 好奇历经的三个时代【一手·译文】
6. 书:part0008 第5章 好奇的红利【一手·译文】
7. 书:part0009 第6章 提问的力量【一手·译文】
8. 书:part0010 第7章 博学的重要性【一手·译文】
9. 书:part0011 第8章 保持好奇心的七种方法（含注释）【一手·译文】
10. 书:part0012 后记 比雅尼的故事【一手·译文】

**英文一手（已存档到 sources/articles/a3-*）**

11. https://www.ian-leslie.com/api/v1/posts?limit=50&offset=0 （分页取到 offset=400；433 篇全量目录，用于标题统计和挑选文章）【一手·目录】
12. https://www.ian-leslie.com/p/answer-machines （2023-01-25，全文）【一手】
13. https://www.ian-leslie.com/p/the-struggle-to-be-human （2022-12-10，全文）【一手】
14. https://www.ian-leslie.com/p/the-problem-with-experts （2021-01-02，全文）【一手】
15. https://www.ian-leslie.com/p/good-fights （2021-02-13，全文）【一手】
16. https://www.ian-leslie.com/p/in-praise-of-sheeple （2021-10-02，全文）【一手】
17. https://www.ian-leslie.com/p/red-carpet-blues （2023-03-25，全文）【一手】
18. https://www.ian-leslie.com/p/the-surest-way-to-make-an-ai-lie （2025-03-19，全文）【一手】
19. https://www.ian-leslie.com/p/why-are-llms-fixated-on-the-number （2025-10-21，全文）【一手】
20. https://www.ian-leslie.com/p/why-introverts-make-the-best-extroverts （2026-08-29，全文）【一手】
21. https://www.ian-leslie.com/p/notes-on-acquired-taste （2026-07-04，全文）【一手】
22. https://www.ian-leslie.com/p/the-renaissance-redux （2024-06-01，全文）【一手】
23. https://www.ian-leslie.com/p/42-reflections-on-the-meaning-of （2024-02-10 重发；原文 2014-02-10 发表于 https://medium.com/@mrianleslie/42-reflections-on-the-meaning-of-life-the-universe-and-everything-b973c7e565db ）【一手】
24. https://www.ian-leslie.com/p/seven-rules-of-good-conversation （2026-09-12，付费，仅预览）【一手】
25. https://www.ian-leslie.com/p/how-not-to-use-ai （2026-01-17，付费，仅预览）【一手】
26. https://www.ian-leslie.com/p/leslies-razors （2024-01-06，付费，仅预览）【一手】
27. https://www.ian-leslie.com/p/andy-burnham-is-going-to-be-yet-another （2026-06-20，全文，未计入统计）【一手】
28. https://www.theguardian.com/society/2016/apr/07/the-sugar-conspiracy-robert-lustig-john-yudkin （Guardian Long Read，全文）【一手】
29. https://www.theguardian.com/news/2017/oct/13/the-scientists-persuading-terrorists-to-spill-their-secrets （Guardian Long Read，全文）【一手】
30. https://aeon.co/essays/why-disagreement-is-vital-to-advancing-human-understanding （Aeon，2021-07-12，全文）【一手】
31. https://www.utne.com/mind-and-body/need-for-cognition-ze0z1410zcwil/ （Curious 引言英文原文节选，2014）【一手】

**其他一手线索（未存成全文）**

32. https://muckrack.com/ian-leslie （经搜索快照拿到 2 条 @mrianleslie 转推文本；页面本身被 Cloudflare 拦截）【一手·经聚合站转引】
33. https://ian-leslie.com/longform-articles/ （旧官网的长文列表，经搜索快照）【一手·线索】
34. https://www.economist.com/1843/2016/10/20/the-scientists-who-make-apps-addictive （被 Cloudflare 拦截，未取得）【一手·未取得】
35. https://archive.org/details/curiousdesiretok0000lesl_w0v9 （Curious 英文版馆藏记录，含完整目录，用于核对章名和小标题）【一手·目录】

**二手（只用于转引书中原句，或作为线索）**

36. https://www.psychologytoday.com/us/blog/finding-the-next-einstein/201407/seven-ways-be-more-curious （2014，转引 Curious 原句；本文用到 2 句）【二手】
37. https://www.christiancentury.org/print/pdf/node/30682 （Curious 书评，转引原句；本文用到 1 句；A4 已存档为 a4-christian-century-wood-curious-2015.txt）【二手】
38. https://www.fastcompany.com/3035297/how-to-solve-a-work-dilemma-with-curiosity/ （转引 Curious 第 8 章原句；本文用到 1 句）【二手】
39. https://longform.org/archive/writers/ian-leslie （长文索引，线索）【二手】
