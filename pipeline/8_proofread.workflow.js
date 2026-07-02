export const meta = {
  name: 'feihua-proofread',
  description: '用每集作者手写 description 校对 ASR 听岔的店名/地名/物品名',
  phases: [{ title: 'Proofread', detail: '逐集对照描述纠错名字' }],
}

// 每集一个 agent：读取该集 proofread 输入（描述 + 抽出的名字/quote），
// 找出 ASR 明显听岔、且描述或 quote 上下文能定正的名字。保守：拿不准就不改。
const ROOT = '/home/zlx/projects/personal/podcast-insights'

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    corrections: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          id: { type: 'string', description: '条目 id，原样照抄输入里的 id' },
          old_name: { type: 'string', description: '输入里的原名（ASR 名）' },
          new_name: { type: 'string', description: '修正后的正确名字' },
          confidence: { type: 'number', description: '0~1，对这条修正有多确定' },
          evidence: { type: 'string', description: '依据：描述/quote 里的哪段支持改名' },
        },
        required: ['id', 'old_name', 'new_name', 'confidence', 'evidence'],
      },
    },
  },
  required: ['corrections'],
}

// args 可能以数组、逗号串或对象({vols:[...]})传入，统一归一为整数数组；缺省=全量 1..234
const vols = Array.isArray(args) ? args
  : (args && Array.isArray(args.vols)) ? args.vols
  : (typeof args === 'string' && args.trim()) ? args.split(',').map((s) => parseInt(s.trim(), 10)).filter(Number.isFinite)
  : Array.from({ length: 234 }, (_, i) => i + 1)
log(`校对 ${vols.length} 集`)

const prompt = (vol) => {
  const f = `${ROOT}/data/feihua/proofread/${String(vol).padStart(3, '0')}.json`
  return `你是中文播客《肥话连篇》的校对。先用 Read 工具读取这个文件：
${f}

文件内含该集作者手写的 description（拼写可信）和一组从语音转写(ASR)里抽出的推荐条目，
每条有 id / category(place 地点 / product 物品 / media 影视剧) / name(ASR 抽到的名字) / quote(对应原话片段)。

任务：找出 name 里 ASR 明显听岔、且能定正的，给出修正。判断依据优先级：
1) description 里出现了对应的正确写法（最可信）；
2) quote 上下文 + 常识能确定正名（如人名/作品名/知名品牌的同音误写）。

铁律（护住「对照原文核验过」的招牌）：
- 拿不准就不要改。宁可漏报，不可错报。
- 只改“听岔的字”，不要改写、扩写、规范化正确的名字（如别把「喜顶」改成「喜顶饺子馆」）。
- 地名/城市本身不在校对范围（只看 place 的 name 店名）。
- confidence：描述里有直接证据→0.85~0.98；仅靠 quote+常识→0.5~0.8；勉强→<0.5。
- evidence 用一句话点明依据来自描述还是 quote、对应哪几个字。

没有需要修正的，返回 {"corrections": []}。id/old_name 必须原样照抄输入。`
}

const results = await pipeline(
  vols,
  (vol) => agent(prompt(vol), {
    label: `proofread:${String(vol).padStart(3, '0')}`,
    phase: 'Proofread',
    model: 'sonnet',
    schema: SCHEMA,
  }).then((r) => (r && Array.isArray(r.corrections)) ? r.corrections : []),
)

const all = results.filter(Boolean).flat()
const epsWithFixes = results.filter((r) => r && r.length).length
log(`共提出 ${all.length} 条修正，涉及 ${epsWithFixes} 集`)
return { corrections: all, total: all.length, episodes_with_fixes: epsWithFixes }
