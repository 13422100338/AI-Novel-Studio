/**
 * 100 golden samples for the restricted novel Markdown subset.
 */
export const GOLDEN_SAMPLES: string[] = [];

function add(sample: string) {
  GOLDEN_SAMPLES.push(sample);
}

// Headings
add("# 第一章 雾港的清晨\n\n正文");
add("## 小节\n\n内容");
add("# 标题\n\n## 副标题\n\n正文");

// Paragraphs with CJK, punctuation, latin, digits
add("清晨的雾港还浸在灰蓝色的光线里。");
add("渡轮靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。");
add("他没想到，二十年后回到这里的第一个清晨，会先听见钟声。");
add("林默把最后一封信塞进外套内袋。");
add("Hello world 123 测试。");
add("第 1 章 · 雾港来信（修订版）");

// Bold and italic
add("**加粗** 正文");
add("正文 *斜体* 结尾");
add("**加粗** 与 *斜体* 同段");
add("*只有斜体*");
add("**只有加粗**");
add("中文**加粗**中文");
add("中文*斜体*中文");
add("**开头加粗**，后面普通，*中间斜体*，**再粗**。");
add("段落内的**强调**不应改变句读。");

// Blockquote
add("> 引用第一行\n\n正文");
add("> 多段\n>\n> 引用第二段\n\n正文");
add("> 一段引用");
add("> 引用\n>\n> 第二段\n>\n> 第三段");

// Horizontal rule
add("第一段\n\n---\n\n第二段");
add("---\n\n正文");
add("正文\n\n---");
add("正文\n\n---\n\n正文\n\n---\n\n正文");

// Soft line breaks
add("第一行\n第二行");
add("第一行\n第二行\n第三行");
add("段落一\n\n段落二");
add("行一\n行二\n行三");

// Combinations
add("# 标题\n\n> 引用\n\n正文");
add("## 标题\n\n第一段 **加粗**\n\n---\n\n第二段 *斜体*");
add("# 大标题\n\n## 小节\n\n正文\n\n> 引用\n\n---\n\n收尾");
add("正文\n\n---\n\n**强调段**\n\n> 引用");
add("第一段\n第二行\n\n---\n\n第三段");

// CJK punctuation safety
add("「双引号」与『单引号』不改变。");
add("省略号……与破折号——应保留。");
add("引号“中文引号”与括号（中文括号）。");
add("。，！？：；、");
add("他问：“什么时候回来？”她没回答。");

// Long single paragraph
add("这是一段很长的中文正文。" .repeat(20).trimEnd());
add(("雾港" + "潮汐" + "灯塔" + "旧信").repeat(60));

// Multiple paragraphs
add("一\n\n二\n\n三\n\n四");
add("第一段。\n\n第二段。\n\n第三段。");
add(Array.from({ length: 30 }, (_, i) => `第 ${i + 1} 段内容。`).join("\n\n"));

// Whitespace edge cases
add("正文  \n\n下一段");
add("");
add(" ");
add("\n\n");
add("正文\n\n\n\n另一段");
add("  ");

// Markdown tokens that must remain literal
add("价格是 3 元，不是 #标签。");
add("5 * 8 = 40，星号是乘号。");
add("C:\\Users\\测试\\路径");
add("邮箱 a@b.com 与网址 example.com。");
add("下划线 _ 不改变。");
add("数字 1_000 与 1,000 保留。");
add("百分比 50% 与 3.14%。");

// Dialogue and scene structure
add("“林默。”她叫住他。\n\n他停住脚步。");
add("“明天见。”\n\n“明天见。”");
add("他说：“走吧。”她点点头。");

// Titles likely in manuscripts
add("第一章 雾港的清晨\n\n正文");
add("第 1 章：起风\n\n正文");
add("卷·一 雾港来信\n\n正文");

// Heading + inline marks
add("# **加粗标题**\n\n正文");
add("## *斜体标题*\n\n正文");
add("### 三级标题\n\n正文");

// Mixed scene breaks
add("场景一。\n\n---\n\n场景二。");
add("场景一。\n\n* * *\n\n场景二。");

// Empty-ish documents
add("# 只有标题");
add("> 只有引用");
add("---");
add("**只有加粗**");

// Stress paragraphs
add(("雾" + "港").repeat(200));
add(("第一章 雾港来信\n\n" + "清晨的雾港。\n\n").repeat(3));

// Chapter-like body (representative of real manuscript)
add(
  "# 第一章 雾港的清晨\n\n" +
    "清晨的雾港还浸在灰蓝色的光线里。渡轮靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。\n\n" +
    "林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。\n\n" +
    "他没想到，二十年后回到这里的第一个清晨，会先听见钟声。\n\n" +
    "---\n\n" +
    "> 老人说，灯塔已经三年没有亮过。\n\n" +
    "**钟声是从塔顶传来的。**"
);

// Fill remaining samples to exactly 100 with safe variants.
while (GOLDEN_SAMPLES.length < 100) {
  add(`补充样本 ${GOLDEN_SAMPLES.length}：正文段落，含**加粗**与*斜体*。\n\n---\n\n> 引用`);
}

export const GOLDEN_SAMPLES_COUNT = GOLDEN_SAMPLES.length;
