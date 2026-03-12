import { client } from './client'
import type { NewsArticleResponse, NewsListResponse } from './generated/hey-api/types.gen'

export type { NewsArticleResponse, NewsListResponse }

export const news = {
	list: (params: { limit?: number; offset?: number }) =>
		client.get<NewsListResponse>(client.withQuery('/api/v1/news/articles', params))
}
