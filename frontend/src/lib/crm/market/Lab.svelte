<script lang="ts">
import { LABELS, type Src } from './data'

/** "Platform demo, Sep 2026" or "Example": every Market figure says where it comes from. */
let { src }: { src: Src } = $props()
</script>

<span class={src === 'demo' ? 'mk-demo' : 'mk-ex'}>{LABELS[src]}</span>
