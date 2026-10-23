function normalize(value: string): string {
	return value
		.normalize('NFKD')
		.replace(/\p{M}/gu, '')
		.toLowerCase()
		.replace(/[^\p{L}\p{N}]+/gu, ' ')
		.trim()
}

// One insertion, deletion, replacement or adjacent transposition. Short words and numbers
// must match literally, so searching for Tower 1 never suggests Tower 2 as a typo.
function nearbyWord(query: string, word: string): boolean {
	if (query.length < 4 || /\d/.test(query) || Math.abs(query.length - word.length) > 1) return false
	let i = 0
	while (i < query.length && query[i] === word[i]) i++
	if (query.length === word.length) {
		return (
			query.slice(i + 1) === word.slice(i + 1) ||
			(query[i] === word[i + 1] &&
				query[i + 1] === word[i] &&
				query.slice(i + 2) === word.slice(i + 2))
		)
	}
	return query.length > word.length
		? query.slice(i + 1) === word.slice(i)
		: query.slice(i) === word.slice(i + 1)
}

export function searchFilterOptions(options: string[], search: string): string[] {
	const query = normalize(search)
	if (!query) return options
	const tokens = query.split(/\s+/)
	return options
		.map((option) => {
			const name = normalize(option)
			const words = name.split(/\s+/)
			const exact = name.includes(query)
			const partial = tokens.every((token) => words.some((word) => word.includes(token)))
			const approximate = tokens.every((token) =>
				words.some((word) => word.includes(token) || nearbyWord(token, word))
			)
			return { option, rank: exact ? 0 : partial ? 1 : approximate ? 2 : 3 }
		})
		.filter(({ rank }) => rank < 3)
		.sort((a, b) => a.rank - b.rank)
		.map(({ option }) => option)
}
