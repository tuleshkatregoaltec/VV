<script lang="ts">
import FileUp from 'lucide-svelte/icons/file-up'
import { extractContactNumbers, type FileContact } from '$lib/whatsapp/blocklist'
import { formatPhone } from '$lib/whatsapp/chat'

// Meta only shares the phone's address book within 24 hours of connecting, so this is the way
// to block personal contacts afterwards: export them from the phone and drop the file here.
let { working, onblock }: { working: boolean; onblock: (numbers: string[]) => Promise<boolean> } =
	$props()

const CODES = [
	{ code: '971', label: 'UAE +971' },
	{ code: '966', label: 'Saudi Arabia +966' },
	{ code: '91', label: 'India +91' },
	{ code: '44', label: 'UK +44' },
	{ code: '1', label: 'US / Canada +1' }
]

let input = $state<HTMLInputElement | null>(null)
let fileName = $state('')
let fileText = $state('')
let country = $state('971')
let error = $state('')
let dragging = $state(false)

const found = $derived<FileContact[]>(fileText ? extractContactNumbers(fileText, country) : [])

async function read(file: File | undefined) {
	error = ''
	if (!file) return
	if (file.size > 5_000_000) {
		error = 'That file is over 5 MB. Export only your contacts, as a .vcf or .csv file.'
		return
	}
	fileName = file.name
	fileText = await file.text()
	if (extractContactNumbers(fileText, country).length === 0) {
		error = `No phone numbers found in ${file.name}. Use a contacts export (.vcf) or a spreadsheet with a phone column (.csv).`
		fileText = ''
	}
}

function reset() {
	fileName = ''
	fileText = ''
	error = ''
	if (input) input.value = ''
}

async function blockAll() {
	if (await onblock(found.map((c) => c.number))) reset()
}
</script>

<div class="imp">
	{#if found.length === 0}
		<label
			class={['drop', dragging && 'over']}
			ondragover={(e) => { e.preventDefault(); dragging = true }}
			ondragleave={() => (dragging = false)}
			ondrop={(e) => { e.preventDefault(); dragging = false; void read(e.dataTransfer?.files[0]) }}
		>
			<FileUp size={18} aria-hidden="true" />
			<span><b>Import contacts from a file</b> Drop a .vcf or .csv here, or choose one</span>
			<input bind:this={input} type="file" accept=".vcf,.vcard,.csv,.txt,text/vcard,text/csv,text/plain" onchange={(e) => read(e.currentTarget.files?.[0])} />
		</label>
		<p class="help">On iPhone: Contacts → select contacts → Share → save the .vcf. On Android: Contacts → Export to .vcf.</p>
	{:else}
		<div class="found" role="status">
			<div class="fh">
				<b>{found.length} {found.length === 1 ? 'number' : 'numbers'} in {fileName}</b>
				<label class="cc">Numbers without a country code are
					<select bind:value={country} aria-label="Country code for local numbers">
						{#each CODES as c (c.code)}<option value={c.code}>{c.label}</option>{/each}
					</select>
				</label>
			</div>
			<ul class="peek">
				{#each found.slice(0, 6) as c (c.number)}
					<li><span>{c.name ?? 'No name'}</span><span class="num">{formatPhone(c.number)}</span></li>
				{/each}
				{#if found.length > 6}<li class="more">and {found.length - 6} more</li>{/if}
			</ul>
			<div class="acts">
				<button type="button" class="btn" disabled={working} onclick={blockAll}>{working ? 'Blocking…' : `Block all ${found.length}`}</button>
				<button type="button" class="btn plain" disabled={working} onclick={reset}>Choose another file</button>
			</div>
		</div>
	{/if}
	{#if error}<p class="err" role="alert">{error}</p>{/if}
</div>

<style>
.imp { display: grid; gap: 6px; }
.drop { position: relative; display: flex; align-items: center; gap: 12px; padding: 14px 16px; border: 1.5px dashed var(--sep-strong); border-radius: 8px; color: var(--text2); font-size: 13px; cursor: pointer; }
.drop:hover, .drop.over { border-color: var(--accent); background: var(--sel); }
.drop:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
.drop b { display: block; color: var(--text); font-weight: 600; font-size: 13.5px; }
.drop input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.help { margin: 0; font-size: 12px; color: var(--text3); }
.found { display: grid; gap: 10px; padding: 12px 14px; border: 1px solid var(--sep); border-radius: 8px; background: var(--sunk); }
.fh { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; align-items: center; font-size: 13.5px; }
.cc { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text2); }
.cc select { padding: 3px 6px; border: 1px solid var(--sep-strong); border-radius: 6px; background: var(--card); color: var(--text); font: inherit; }
.peek { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; font-size: 13px; }
.peek li { display: flex; justify-content: space-between; gap: 12px; }
.peek span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.num { font-variant-numeric: tabular-nums; color: var(--text2); }
.peek .more { color: var(--text3); }
.acts { display: flex; gap: 8px; flex-wrap: wrap; }
.err { margin: 0; color: var(--red); font-size: 12.5px; }
</style>
