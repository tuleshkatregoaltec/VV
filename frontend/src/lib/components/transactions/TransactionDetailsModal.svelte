<script lang="ts">
import Modal from '$lib/components/ui/Modal.svelte'
import { formatAed, formatSqm } from '$lib/constants/transactions'
import type { SaleRow } from '$lib/utils/transactionPages'

let {
	transaction,
	onClose
}: {
	transaction: SaleRow | null
	onClose: () => void
} = $props()

// DXBI records the unit of every sale, so the unit is shown as recorded, not inferred.
const fields = $derived(
	transaction
		? [
				{ label: 'Transaction ID', value: transaction.transaction_id },
				{ label: 'Date', value: transaction.date },
				{ label: 'Unit', value: transaction.unit },
				{ label: 'Building', value: transaction.building },
				{ label: 'Location', value: transaction.location },
				{ label: 'Project', value: transaction.project },
				{ label: 'Property Type', value: transaction.propertyType },
				{ label: 'Bedrooms', value: transaction.bedrooms },
				{ label: 'Status', value: transaction.status },
				{ label: 'Size', value: `${formatSqm(transaction.size)} m²` },
				{ label: 'Price', value: `${formatAed(transaction.price)} AED` },
				{ label: 'Price/m²', value: `${formatAed(transaction.pricePerSqM)} AED/m²` }
			]
		: []
)
</script>

<Modal open={transaction !== null} {onClose} title="Transaction Details" size="xl">
	{#if transaction}
		<div class="mb-2">
			<h3 class="mb-3 text-lg font-semibold text-fg-1">Transaction Information</h3>
			<div class="grid grid-cols-2 gap-4 rounded-lg border border-border bg-slate-50 p-4 md:grid-cols-3">
				{#each fields as field (field.label)}
					<div>
						<span class="text-sm text-fg-4">{field.label}</span>
						<p class="font-medium text-fg-1">{field.value}</p>
					</div>
				{/each}
			</div>
			<p class="mt-3 text-xs text-fg-4">
				Source: DXBInteract (DXBI) sold-transaction record. Price/m² is the price divided by
				the size.
			</p>
		</div>
	{/if}
</Modal>
