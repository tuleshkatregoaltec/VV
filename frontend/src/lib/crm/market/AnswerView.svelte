<script lang="ts">
import { type Answer, num } from './data'

/** One example answer: text, figures, a small chart, source and a link into Market. */
let { a, onnav }: { a: Answer; onnav?: () => void } = $props()
const max = $derived(Math.max(1, ...(a.chart?.points.map((p) => p[1]) ?? [1])))
</script>

<p>{a.text}</p>
{#if a.rows && !a.chart?.horizontal}
	<dl class="mk-kv">{#each a.rows as [k, v] (k)}<dt>{k}</dt><dd><b>{v}</b></dd>{/each}</dl>
{/if}
{#if a.table}
	<div class="tblwrap">
		<table class="tbl">
			<thead><tr>{#each a.table.head as h, i (h)}<th class={i ? 'r' : ''}>{h}</th>{/each}</tr></thead>
			<tbody>{#each a.table.body as r, j (j)}<tr>{#each r as c, i (i)}<td class={i ? 'r' : ''}>{c}</td>{/each}</tr>{/each}</tbody>
		</table>
	</div>
{/if}
{#if a.chart?.horizontal}
	<div class="mk-hbars" role="img" aria-label="{a.chart.title}. {a.chart.points.map((p) => `${p[0]}: ${p[1]}%`).join(', ')}">
		{#each a.chart.points as [k, v] (k)}
			<div class="mk-hbar"><span>{k}</span><span class="mk-htrack"><i style:width="{(v / (max * 1.15)) * 100}%"></i></span><b>{v.toFixed(1)}%</b></div>
		{/each}
	</div>
{:else if a.chart}
	<div class="mk-minititle">{a.chart.title}</div>
	<div class="mk-bars sm" role="img" aria-label="{a.chart.title}. {a.chart.points.map((p) => `${p[0]}: ${num(p[1])}`).join(', ')}">
		{#each a.chart.points as [k, v], i (k)}
			<div class="mk-bcol">
				<div class="mk-bstack"><i class={['mk-b', i === (a.chart?.points.length ?? 0) - 1 && 'sel']} style:height="{(v / (max * 1.08)) * 100}%"></i></div>
				<span class="mk-bv">{num(v)}</span><span class="mk-bq">{k}</span>
			</div>
		{/each}
	</div>
{/if}
{#if a.note}<p class="note">{a.note}</p>{/if}
<div class="mk-row mk-src">
	{#if a.source}<span>Source: {a.source}</span>{/if}
	<span class="mk-ex">{a.label}</span>
	{#if a.ref}<a class="btn ghost sm" href={a.ref.href} onclick={onnav}>{a.ref.label}</a>{/if}
</div>
