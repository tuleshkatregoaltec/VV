import { api } from './client'

export interface NewsArticle {
	id: number
	url: string
	headline: string
	thumbnail_url: string
	thumbnail_base64?: string
	publish_date: string | null
	source?: string
}

export interface NewsListResponse {
	articles: NewsArticle[]
	total: number
	limit: number
	offset: number
}

export const news = {
	list: (params: { limit?: number; offset?: number }) => {
		const query = new URLSearchParams()
		if (params.limit) query.append('limit', params.limit.toString())
		if (params.offset) query.append('offset', params.offset.toString())
		return api<NewsListResponse>(`/api/v1/news/articles?${query}`)
	}
}
